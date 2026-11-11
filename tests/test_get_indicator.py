"""
Tests for ``esios_get_indicator``.

If a new bug is found, add its test with ``xfail(strict=True)``: once it is fixed the test will
pass (XPASS → error) and the ``xfail`` must be removed.
"""

import copy
import inspect
import json
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
import requests

from esios_request import esios_get_archive, esios_get_indicator
from esios_request.esios_request import esios_get_request

from .conftest import (
    FMT,
    boundary_callback,
    daily_average,
    daily_trunc_callback,
    indicator_url,
    make_indicator_payload,
    make_value,
    payload_by_start,
    query_params,
    sent_blocks,
)

ONE_HOUR = {"start_date": "2025/01/01T00:00:00Z", "end_date": "2025/01/01T01:00:00Z"}


def test_returns_dataframe_with_utc_index(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    df = esios_get_indicator(token, 600, params=dict(ONE_HOUR))

    assert isinstance(df, pd.DataFrame)
    assert df.index.name == "datetime_utc"
    assert isinstance(df.index, pd.DatetimeIndex)
    assert str(df.index.tz) == "UTC"
    assert {"value", "geo_id", "geo_name"} <= set(df.columns)
    assert len(df) == 2


def test_alias_and_numeric_id_request_the_same_url(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    esios_get_indicator(token, "p_pmd", params=dict(ONE_HOUR))
    esios_get_indicator(token, 600, params=dict(ONE_HOUR))

    urls = {c.request.url.split("?")[0] for c in mocked.calls}
    assert urls == {indicator_url(600)}


def test_sends_token_and_dates(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    esios_get_indicator(token, 600, params=dict(ONE_HOUR), headers={"Accept": "application/json"})

    req = mocked.calls[0].request
    assert req.headers["x-api-key"] == token
    assert query_params(req) == ONE_HOUR


def test_extra_params_are_forwarded(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    esios_get_indicator(token, 600, params={**ONE_HOUR, "time_trunc": "hour"})

    assert query_params(mocked.calls[0].request)["time_trunc"] == "hour"


def test_long_range_is_split_into_1_month_blocks_aligned_to_madrid(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    esios_get_indicator(
        token, 600, params={"start_date": "2025/02/15T00:00:00Z", "end_date": "2025/05/10T00:00:00Z"}
    )

    blocks = sent_blocks(mocked)
    # Boundaries = the 1st of each month at 00:00 Madrid time (23:00Z in winter, 22:00Z in summer).
    # Each block ends 1 s before the boundary: end_date is inclusive, so blocks do not overlap.
    assert blocks == [
        ("2025/02/15T00:00:00Z", "2025/02/28T22:59:59Z"),
        ("2025/02/28T23:00:00Z", "2025/03/31T21:59:59Z"),
        ("2025/03/31T22:00:00Z", "2025/04/30T21:59:59Z"),
        ("2025/04/30T22:00:00Z", "2025/05/10T00:00:00Z"),
    ]


def test_consecutive_blocks_have_no_gaps_or_overlaps(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    esios_get_indicator(
        token, 600, params={"start_date": "2020/03/15T10:30:00Z", "end_date": "2024/11/20T05:00:00Z"}
    )

    blocks = [(datetime.strptime(s, FMT), datetime.strptime(e, FMT)) for s, e in sent_blocks(mocked)]
    assert blocks[0][0] == datetime(2020, 3, 15, 10, 30)
    assert blocks[-1][1] == datetime(2024, 11, 20, 5)
    for (_, end), (next_start, _) in pairwise(blocks):
        assert next_start - end == timedelta(seconds=1)
        boundary = next_start.replace(tzinfo=UTC).astimezone(ZoneInfo("Europe/Madrid"))
        assert (boundary.day, boundary.hour, boundary.minute) == (1, 0, 0)
    for start, end in blocks:
        assert start <= end
        assert end - start <= timedelta(days=31, hours=1)  # one month (+1 h when DST ends)


def test_time_trunc_day_does_not_split_days_between_blocks(mocked, token):
    # Regression: with blocks cut at 00:00Z, the day at the cut came back with a partial
    # average and that value was kept (verified against the real API on 2026-11-10).
    mocked.add_callback("GET", indicator_url(600), callback=daily_trunc_callback(600))
    date_range = {"start_date": "2024/12/31T23:00:00Z", "end_date": "2026/02/28T22:59:59Z"}

    df = esios_get_indicator(token, 600, params={**date_range, "time_trunc": "day", "time_agg": "average"})

    expected = pd.DataFrame(daily_average(datetime(2024, 12, 31, 23), datetime(2026, 2, 28, 22, 59, 59)))
    expected = expected.set_index(pd.to_datetime(expected["datetime_utc"], utc=True))["value"]
    assert len(mocked.calls) == 14  # January 2025 to February 2026, one block per month
    assert not df.index.duplicated().any()
    pd.testing.assert_series_equal(df["value"], expected, check_names=False, check_index_type=False)


def test_time_trunc_year_uses_yearly_blocks(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    esios_get_indicator(
        token, 600,
        params={"start_date": "2022/12/31T23:00:00Z", "end_date": "2025/12/31T22:59:59Z", "time_trunc": "year"},
    )

    blocks = sent_blocks(mocked)
    assert blocks == [
        ("2022/12/31T23:00:00Z", "2023/12/31T22:59:59Z"),
        ("2023/12/31T23:00:00Z", "2024/12/31T22:59:59Z"),
        ("2024/12/31T23:00:00Z", "2025/12/31T22:59:59Z"),
    ]


def test_start_equal_to_end_requests_one_block(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    df = esios_get_indicator(
        token, 600, params={"start_date": "2025/01/01T00:00:00Z", "end_date": "2025/01/01T00:00:00Z"}
    )

    assert len(mocked.calls) == 1
    assert not df.empty


def test_no_duplicates_between_blocks(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    df = esios_get_indicator(
        token, 600, params={"start_date": "2025/01/01T00:00:00Z", "end_date": "2026/03/01T00:00:00Z"}
    )

    assert not df.index.duplicated().any()
    assert len(mocked.calls) == 15  # January 2025 to March 2026, one block per month
    assert len(df) == 30  # start and end of each of the 15 blocks
    assert df.index.is_monotonic_increasing


def test_dedupes_if_the_api_repeats_an_instant_between_blocks(mocked, token):
    # Safety net: even though blocks do not overlap, if the API returned the same instant
    # in two blocks it must not appear twice.
    repeated = make_value(datetime(2025, 1, 31, 23), 1.0)
    mocked.add_callback("GET", indicator_url(600), callback=payload_by_start(600, {
        "2025/01/01T00:00:00Z": [make_value(datetime(2025, 1, 1), 0.0), repeated],
        "2025/01/31T23:00:00Z": [repeated, make_value(datetime(2025, 2, 15), 2.0)],
    }))

    df = esios_get_indicator(
        token, 600, params={"start_date": "2025/01/01T00:00:00Z", "end_date": "2025/02/15T00:00:00Z"}
    )

    assert len(mocked.calls) == 2
    assert list(df["value"]) == [0.0, 1.0, 2.0]


def test_http_error_is_propagated(mocked, token):
    mocked.add("GET", indicator_url(600), status=401, json={"message": "unauthorized"})

    with pytest.raises(requests.HTTPError):
        esios_get_indicator(token, 600, params=dict(ONE_HOUR))


def test_response_without_values_returns_empty_dataframe_with_columns(mocked, token):
    mocked.add("GET", indicator_url(600), json=make_indicator_payload(600, []))

    df = esios_get_indicator(token, 600, params=dict(ONE_HOUR))

    assert isinstance(df, pd.DataFrame)
    assert df.empty
    assert list(df.columns) == ["value", "datetime", "tz_time", "geo_id", "geo_name"]
    assert df.index.name == "datetime_utc"
    assert isinstance(df.index, pd.DatetimeIndex)
    assert str(df.index.tz) == "UTC"


# --------------------------------------------------------------------------- Phase 1 (former bugs)

GEOS_600 = [(1, "Portugal"), (2, "Francia"), (3, "España")]
LONG_RANGE = {"start_date": "2025/01/01T00:00:00Z", "end_date": "2026/03/01T00:00:00Z"}


def test_several_geos_per_timestamp_are_not_lost(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600, GEOS_600))

    df = esios_get_indicator(token, 600, params=dict(ONE_HOUR))

    assert set(df["geo_name"]) == {"Portugal", "Francia", "España"}
    assert len(df) == 2 * len(GEOS_600)


def test_several_geos_and_several_blocks_without_duplicates(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600, GEOS_600))

    df = esios_get_indicator(token, 600, params=dict(LONG_RANGE))

    keys = list(zip(df.index, df["geo_id"]))
    assert len(keys) == len(set(keys))
    assert len(df) == 30 * len(GEOS_600)  # 30 distinct instants (15 blocks) x 3 geos
    assert df.groupby("geo_id").size().to_dict() == {1: 30, 2: 30, 3: 30}


def test_user_params_are_not_modified(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))
    params = {**LONG_RANGE, "time_trunc": "hour"}
    original = copy.deepcopy(params)

    esios_get_indicator(token, 600, params=params)
    esios_get_indicator(token, 600, params=params)

    assert params == original


def test_user_headers_are_not_modified(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))
    headers = {"Accept": "application/json"}

    esios_get_indicator(token, 600, params=dict(ONE_HOUR), headers=headers)
    esios_get_indicator(token, 600, params=dict(ONE_HOUR), headers=headers)

    assert headers == {"Accept": "application/json"}
    assert mocked.calls[0].request.headers["x-api-key"] == token


def test_default_headers_do_not_store_the_token(mocked, token):
    from esios_request.esios_request import DEFAULT_HEADERS

    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    esios_get_indicator(token, 600, params=dict(ONE_HOUR))
    esios_get_indicator(token, 600, params=dict(ONE_HOUR))

    assert "x-api-key" not in DEFAULT_HEADERS
    req = mocked.calls[0].request
    assert req.headers["x-api-key"] == token
    assert req.headers["Accept"] == DEFAULT_HEADERS["Accept"]


@pytest.mark.parametrize("func", [esios_get_indicator, esios_get_archive])
def test_signatures_have_no_mutable_defaults(func):
    for p in inspect.signature(func).parameters.values():
        assert not isinstance(p.default, (dict, list, set)), p.name


def test_esios_get_request_has_no_default_session_or_dead_parameter():
    sig = inspect.signature(esios_get_request)
    assert sig.parameters["session"].default is None
    assert "max_cache_entries" not in sig.parameters


@pytest.mark.parametrize(
    "payload",
    [{"unexpected": True}, {"indicator": {}}, {"indicator": {"values": "x"}}, {"indicator": {"values": [{"value": 1}]}}],
)
def test_malformed_response_raises_error(mocked, token, payload):
    mocked.add("GET", indicator_url(600), body=json.dumps(payload))

    with pytest.raises(ValueError, match="Unexpected response"):
        esios_get_indicator(token, 600, params=dict(ONE_HOUR))


def test_non_json_response_raises_error(mocked, token):
    mocked.add("GET", indicator_url(600), body="<html>error</html>")

    with pytest.raises(ValueError):
        esios_get_indicator(token, 600, params=dict(ONE_HOUR))


@pytest.mark.parametrize("params", [{}, {"start_date": "2025/01/01T00:00:00Z"}, {"end_date": "2025/01/01T00:00:00Z"}])
def test_missing_dates_raise_clear_error(params, token):
    with pytest.raises(ValueError, match="Missing required parameters"):
        esios_get_indicator(token, 600, params=params)


def test_geo_ids_filter_is_forwarded_in_every_block(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    esios_get_indicator(token, 600, params={**LONG_RANGE, "geo_ids[]": [3, 1]})

    assert len(mocked.calls) == 15
    for call in mocked.calls:
        qs = parse_qs(urlparse(call.request.url).query)
        assert qs["geo_ids[]"] == ["3", "1"]


def test_geo_agg_rows_with_geo_ids_instead_of_geo_id(mocked, token):
    # With geo_agg the API returns "geo_ids" (list) instead of "geo_id"/"geo_name": one row per instant.
    def row(dt, value):
        iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        return {"value": value, "datetime": iso, "datetime_utc": iso, "tz_time": iso, "geo_ids": [1, 2, 3]}

    mocked.add_callback("GET", indicator_url(600), callback=payload_by_start(600, {
        "2025/01/01T00:00:00Z": [row(datetime(2025, 1, 1), 1.0)],
        "2025/01/31T23:00:00Z": [row(datetime(2025, 2, 15), 2.0)],
    }))

    df = esios_get_indicator(
        token, 600,
        params={"start_date": "2025/01/01T00:00:00Z", "end_date": "2025/02/15T00:00:00Z", "geo_agg": "sum"},
    )

    assert list(df["value"]) == [1.0, 2.0]
    assert "geo_id" not in df.columns
    assert df["geo_ids"].iloc[0] == [1, 2, 3]
    assert query_params(mocked.calls[0].request)["geo_agg"] == "sum"
