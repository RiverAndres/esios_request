"""
Phase 3 tests (v1.3.0): ``EsiosClient``, parallel block download, ``indicators()`` (long/wide),
``indicator_info()``, ``search()`` and the alias catalogue.
"""

import json
import threading
import time
from datetime import datetime

import pandas as pd
import pytest
import requests

from esios_request import (
    EsiosClient,
    EsiosConfigError,
    EsiosNotFound,
    EsiosSchemaError,
    EsiosUnknownAlias,
    archive_catalogue,
    esios_get_indicator,
    indicator_catalogue,
)
from esios_request.indicators import (
    ARCHIVES,
    INDICATORS,
    archives,
    common_archives,
    common_indicators,
    indicators,
)

from .conftest import (
    BASE_URL,
    archive_url,
    boundary_callback,
    indicator_url,
    make_indicator_payload,
    make_value,
    payload_by_start,
    query_params,
    sent_blocks,
)

ONE_HOUR = ("2025/01/01T00:00:00Z", "2025/01/01T01:00:00Z")
YEAR = ("2025/01/01T00:00:00Z", "2025/12/31T22:59:59Z")


@pytest.fixture
def client(token):
    with EsiosClient(token) as c:
        yield c


# --------------------------------------------------------------------------- client setup


def test_client_uses_environment_token(mocked, monkeypatch):
    monkeypatch.setenv("ESIOS_API_KEY", "env-token")
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    with EsiosClient() as client:
        client.indicator(600, *ONE_HOUR)

    assert mocked.calls[0].request.headers["x-api-key"] == "env-token"


def test_client_without_token_fails_at_construction(monkeypatch):
    monkeypatch.delenv("ESIOS_API_KEY", raising=False)
    with pytest.raises(EsiosConfigError, match="ESIOS_API_KEY"):
        EsiosClient()


def test_client_repr_does_not_show_the_token(token):
    assert token not in repr(EsiosClient(token))


@pytest.mark.parametrize("kwargs", [{"max_workers": 0}, {"max_workers": True}, {"block_months": 0}, {"block_months": 1.5}])
def test_invalid_client_settings_raise_error(token, kwargs):
    with pytest.raises(EsiosConfigError):
        EsiosClient(token, **kwargs)


def test_context_manager_closes_its_own_session(token, monkeypatch):
    client = EsiosClient(token)
    closed = []
    monkeypatch.setattr(client.session, "close", lambda: closed.append(True))

    with client:
        pass

    assert closed == [True]


def test_external_and_cached_sessions_are_not_closed(token, monkeypatch):
    external = requests.Session()
    closed = []
    monkeypatch.setattr(external, "close", lambda: closed.append("external"))
    with EsiosClient(token, session=external) as client:
        assert client.session is external

    cached = EsiosClient(token, use_cache=True)
    monkeypatch.setattr(cached.session, "close", lambda: closed.append("cached"))
    cached.close()

    assert closed == []


def test_client_headers_are_copied(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))
    headers = {"Accept": "application/json"}

    with EsiosClient(token, headers=headers) as client:
        client.indicator(600, *ONE_HOUR)

    assert headers == {"Accept": "application/json"}
    assert mocked.calls[0].request.headers["Accept"] == "application/json"
    assert mocked.calls[0].request.headers["x-api-key"] == token


# --------------------------------------------------------------------------- indicator()


def test_indicator_matches_legacy_function(mocked, token, client):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    df_client = client.indicator("p_pmd", *YEAR)
    df_legacy = esios_get_indicator(token, 600, params={"start_date": YEAR[0], "end_date": YEAR[1]})

    pd.testing.assert_frame_equal(df_client, df_legacy)


def test_indicator_geo_ids_and_api_params_are_forwarded(mocked, client):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    client.indicator(600, *ONE_HOUR, geo_ids=[3, 1], time_trunc="hour", params={"locale": "en"})

    request = mocked.calls[0].request
    assert "geo_ids%5B%5D=3&geo_ids%5B%5D=1" in request.url
    assert query_params(request)["time_trunc"] == "hour"
    assert query_params(request)["locale"] == "en"


def test_indicator_rejects_dates_inside_params(client):
    with pytest.raises(EsiosConfigError, match="start/end"):
        client.indicator(600, *ONE_HOUR, params={"start_date": "2025-01-01"})


def test_indicator_missing_dates_raise_error(client):
    with pytest.raises(EsiosConfigError, match="Missing required parameters: end_date"):
        client.indicator(600, "2025-01-01", None)


def test_block_months_is_configurable(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    with EsiosClient(token, block_months=3) as client:
        client.indicator(600, "2025/01/01T00:00:00Z", "2025/07/15T00:00:00Z")

    assert sent_blocks(mocked) == [
        ("2025/01/01T00:00:00Z", "2025/03/31T21:59:59Z"),
        ("2025/03/31T22:00:00Z", "2025/06/30T21:59:59Z"),
        ("2025/06/30T22:00:00Z", "2025/07/15T00:00:00Z"),
    ]


@pytest.mark.parametrize(("block_months", "expected_blocks"), [(3, 3), (12, 3), (24, 2)])
def test_time_trunc_year_rounds_block_months_up_to_whole_years(mocked, token, block_months, expected_blocks):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    with EsiosClient(token, block_months=block_months) as client:
        client.indicator(600, "2022/12/31T23:00:00Z", "2025/12/31T22:59:59Z", time_trunc="year")

    blocks = sent_blocks(mocked)
    assert len(blocks) == expected_blocks
    assert all(start.endswith("12/31T23:00:00Z") or start == "2022/12/31T23:00:00Z" for start, _ in blocks)


# --------------------------------------------------------------------------- parallel download


def _concurrency_callback(indicator_id: int, delay: float = 0.05):
    """Boundary callback that also records the maximum number of simultaneous requests."""
    state = {"active": 0, "max": 0}
    lock = threading.Lock()
    inner = boundary_callback(indicator_id)

    def _cb(request):
        with lock:
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
        time.sleep(delay)
        with lock:
            state["active"] -= 1
        return inner(request)

    return _cb, state


def test_blocks_are_downloaded_in_parallel(mocked, token):
    callback, state = _concurrency_callback(600)
    mocked.add_callback("GET", indicator_url(600), callback=callback)

    with EsiosClient(token, max_workers=4, block_months=3) as client:
        client.indicator(600, *YEAR)

    assert len(mocked.calls) == 4
    assert state["max"] > 1


def test_max_workers_1_is_sequential(mocked, token):
    callback, state = _concurrency_callback(600, delay=0.01)
    mocked.add_callback("GET", indicator_url(600), callback=callback)

    with EsiosClient(token, max_workers=1, block_months=3) as client:
        client.indicator(600, *YEAR)

    assert state["max"] == 1


def test_parallel_and_sequential_give_the_same_result(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600, [(1, "Portugal"), (3, "España")]))

    with EsiosClient(token, max_workers=1, block_months=2) as sequential:
        expected = sequential.indicator(600, *YEAR)
    with EsiosClient(token, max_workers=4, block_months=2) as parallel:
        result = parallel.indicator(600, *YEAR)

    pd.testing.assert_frame_equal(result, expected)
    assert result.index.is_monotonic_increasing


def test_error_in_one_parallel_block_is_raised(mocked, token):
    def callback(request):
        if query_params(request)["start_date"].startswith("2025/06"):
            return 404, {}, "not found"
        return boundary_callback(600)(request)

    mocked.add_callback("GET", indicator_url(600), callback=callback)

    with EsiosClient(token, max_workers=4, block_months=3) as client, pytest.raises(EsiosNotFound):
        client.indicator(600, *YEAR)


# --------------------------------------------------------------------------- indicators()


GEOS = [(1, "Portugal"), (3, "España")]


def test_indicators_long_format(mocked, client):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600, GEOS))
    mocked.add_callback("GET", indicator_url(602), callback=boundary_callback(602))

    df = client.indicators(["p_pmd", 602, 600], *ONE_HOUR)

    assert df.columns[0] == "indicator"
    assert df["indicator"].dtype == "Int64"
    assert df.groupby("indicator").size().to_dict() == {600: 4, 602: 2}  # duplicates removed
    assert len(mocked.calls) == 2
    assert df.index.name == "datetime_utc"


def test_indicators_wide_format(mocked, client):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600, GEOS))
    mocked.add_callback("GET", indicator_url(602), callback=boundary_callback(602))

    df = client.indicators([600, 602], *ONE_HOUR, wide=True)

    assert list(df.columns.names) == ["indicator", "geo_id"]
    assert set(df.columns) == {(600, 1), (600, 3), (602, 3)}
    assert str(df.index.dtype) == "datetime64[ns, UTC]"
    assert len(df) == 2
    assert (df.dtypes == "float64").all()
    # boundary_callback gives value = position of the geo: Portugal 0.0, España 1.0
    assert df[(600, 1)].tolist() == [0.0, 0.0]
    assert df[(600, 3)].tolist() == [1.0, 1.0]


def test_indicators_wide_with_geo_agg_rows(mocked, client):
    iso = "2025-01-01T00:00:00Z"
    row = {"value": 5.0, "datetime": iso, "datetime_utc": iso, "tz_time": iso, "geo_ids": [1, 3]}
    mocked.add("GET", indicator_url(600), json=make_indicator_payload(600, [row]))

    df = client.indicators([600], *ONE_HOUR, wide=True, geo_agg="sum")

    assert df.shape == (1, 1)
    indicator, geo_id = df.columns[0]
    assert indicator == 600 and pd.isna(geo_id)
    assert df.iloc[0, 0] == 5.0


def test_indicators_without_data(mocked, client):
    mocked.add("GET", indicator_url(600), json=make_indicator_payload(600, []))

    long = client.indicators([600], *ONE_HOUR)
    wide = client.indicators([600], *ONE_HOUR, wide=True)

    assert long.empty and "indicator" in long.columns
    assert wide.empty and list(wide.columns.names) == ["indicator", "geo_id"]
    assert str(wide.index.dtype) == "datetime64[ns, UTC]"


def test_indicators_accepts_a_single_id(mocked, client):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    df = client.indicators("p_pmd", *ONE_HOUR)

    assert set(df["indicator"]) == {600}


def test_indicators_with_empty_list_raises_error(client):
    with pytest.raises(EsiosConfigError):
        client.indicators([], *ONE_HOUR)


def test_indicators_split_each_indicator_into_blocks(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=payload_by_start(600, {
        "2025/01/01T00:00:00Z": [make_value(datetime(2025, 1, 1), 1.0)],
        "2025/06/30T22:00:00Z": [make_value(datetime(2025, 7, 1), 2.0)],
    }))
    mocked.add_callback("GET", indicator_url(602), callback=payload_by_start(602, {
        "2025/01/01T00:00:00Z": [make_value(datetime(2025, 1, 1), 10.0)],
        "2025/06/30T22:00:00Z": [make_value(datetime(2025, 7, 1), 20.0)],
    }))

    with EsiosClient(token, max_workers=4) as client:
        df = client.indicators([600, 602], *YEAR)

    assert len(mocked.calls) == 4
    assert df[df["indicator"] == 600]["value"].tolist() == [1.0, 2.0]
    assert df[df["indicator"] == 602]["value"].tolist() == [10.0, 20.0]


# --------------------------------------------------------------------------- indicator_info() / search()


def _info_payload(indicator_id: int, name: str) -> dict:
    return {"indicator": {
        "id": indicator_id,
        "name": name,
        "composited": False,
        "disaggregated": True,
        "magnitud": [{"name": "Precio €/MWh", "id": 23}],
        "tiempo": [{"name": "Quince minutos", "id": 218}],
        "universe": [{"name": "Mercados y precios", "id": 156}],
        "geos": [{"geo_id": 3, "geo_name": "España"}],
        "description": "<p>Mercado&nbsp;diario de energ&iacute;a.</p>\n<p>Segunda l&iacute;nea.</p>",
    }}


def test_indicator_info_single(mocked, client):
    mocked.add("GET", indicator_url(600), json=_info_payload(600, "Precio mercado SPOT Diario"))

    df = client.indicator_info("p_pmd")

    assert query_params(mocked.calls[0].request) == {"values": "false"}
    assert df.index.tolist() == [600]
    assert df.index.name == "id"
    row = df.loc[600]
    assert row["name"] == "Precio mercado SPOT Diario"
    assert row["unit"] == "Precio €/MWh"
    assert row["granularity"] == "Quince minutos"
    assert row["universe"] == "Mercados y precios"
    assert row["geos"] == [{"geo_id": 3, "geo_name": "España"}]
    assert row["description"] == "Mercado diario de energía. Segunda línea."
    assert pd.isna(row["short_name"])


def test_indicator_info_several(mocked, client):
    mocked.add("GET", indicator_url(600), json=_info_payload(600, "A"))
    mocked.add("GET", indicator_url(602), json=_info_payload(602, "B"))

    df = client.indicator_info([600, "e_pmd"])

    assert df.index.tolist() == [600, 602]
    assert df["name"].tolist() == ["A", "B"]


def test_indicator_info_malformed_raises_schema_error(mocked, client):
    mocked.add("GET", indicator_url(600), json={"unexpected": True})

    with pytest.raises(EsiosSchemaError):
        client.indicator_info(600)


def test_search(mocked, client):
    payload = {"indicators": [
        {"id": 600, "name": "Precio mercado SPOT Diario", "short_name": None, "description": "<p>Precio&nbsp;diario</p>"},
        {"id": 612, "name": "Precio intradiario 1", "short_name": "PMI1", "description": None},
    ], "meta": {"size": 2}}
    mocked.add("GET", f"{BASE_URL}/indicators", json=payload)

    df = client.search("precio")

    assert query_params(mocked.calls[0].request) == {"text": "precio"}
    assert df.index.tolist() == [600, 612]
    assert list(df.columns) == ["name", "short_name", "description"]
    assert df.loc[600, "description"] == "Precio diario"
    assert df.loc[612, "short_name"] == "PMI1"


def test_search_without_text_lists_everything(mocked, client):
    mocked.add("GET", f"{BASE_URL}/indicators", json={"indicators": [], "meta": {"size": 0}})

    df = client.search()

    assert "text" not in query_params(mocked.calls[0].request)
    assert df.empty and list(df.columns) == ["name", "short_name", "description"]


@pytest.mark.parametrize("payload", [{"unexpected": 1}, {"indicators": "x"}, {"indicators": [{"name": "no id"}]}])
def test_search_malformed_raises_schema_error(mocked, client, payload):
    mocked.add("GET", f"{BASE_URL}/indicators", body=json.dumps(payload))

    with pytest.raises(EsiosSchemaError):
        client.search("x")


# --------------------------------------------------------------------------- archive()


def test_client_archive_forwards_params(mocked, client):
    mocked.add("GET", archive_url(110), json=[{"a": 1}])

    df = client.archive("uf", date="2025-01-01", params={"locale": "en"})

    assert query_params(mocked.calls[0].request) == {"date": "2025-01-01", "locale": "en"}
    assert len(df) == 1


# --------------------------------------------------------------------------- catalogue


def test_unknown_alias_raises_clear_error_with_suggestions(mocked, token):
    with pytest.raises(EsiosUnknownAlias, match="Did you mean: p_pmd") as info:
        esios_get_indicator(token, "p_pmdd", params={"start_date": ONE_HOUR[0], "end_date": ONE_HOUR[1]})

    assert isinstance(info.value, KeyError)  # compatibility with v1.x
    assert isinstance(info.value, EsiosConfigError)
    assert not str(info.value).startswith("'")
    assert len(mocked.calls) == 0


def test_unknown_archive_alias(token):
    with pytest.raises(EsiosUnknownAlias, match="archive"):
        common_archives("nope")


@pytest.mark.parametrize(("value", "expected"), [("600", 600), (600, 600), ("p_pmd", 600)])
def test_indicator_id_resolution(value, expected):
    assert common_indicators(value) == expected


@pytest.mark.parametrize("value", [True, 6.0, None, [600]])
def test_invalid_id_type_raises_config_error(value):
    with pytest.raises(EsiosConfigError):
        common_indicators(value)


def test_indicator_catalogue_dataframe():
    df = indicator_catalogue()

    assert df.index.name == "alias"
    assert list(df.columns) == ["id", "unit", "description"]
    assert len(df) == len(INDICATORS) == 24
    assert df.loc["p_pmd", "id"] == 600
    assert df["unit"].isin(["EUR/MWh", "EUR/MW", "MWh", "MW"]).all()
    assert df["description"].str.len().gt(0).all()
    assert df["id"].to_dict() == indicators  # backward compatible dict stays in sync


def test_archive_catalogue_dataframe():
    df = archive_catalogue()

    assert list(df.columns) == ["id", "description"]
    assert len(df) == len(ARCHIVES)
    assert df["id"].to_dict() == archives
