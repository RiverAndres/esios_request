"""
Phase 2 tests (v1.2.0): retries, custom exceptions, logging, optional token,
flexible dates and normalised output types.

``responses`` emulates ``urllib3`` retries (without waiting for the backoff), so these tests
are fast and never call the real API.
"""

import logging
from datetime import UTC, date, datetime, timedelta, timezone

import pandas as pd
import pytest
import requests

from esios_request import (
    EsiosAuthError,
    EsiosConfigError,
    EsiosError,
    EsiosHTTPError,
    EsiosNotFound,
    EsiosRateLimited,
    EsiosSchemaError,
    esios_get_archive,
    esios_get_indicator,
)
from esios_request.req_cache import RETRY_STATUSES, get_session

from .conftest import (
    archive_url,
    boundary_callback,
    indicator_url,
    make_indicator_payload,
    make_value,
    query_params,
)

ONE_HOUR = {"start_date": "2025/01/01T00:00:00Z", "end_date": "2025/01/01T01:00:00Z"}
OK_PAYLOAD = make_indicator_payload(600, [make_value(datetime(2025, 1, 1), 1.0)])


# --------------------------------------------------------------------------- retries


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_transient_error_followed_by_200_succeeds(mocked, token, status):
    mocked.add("GET", indicator_url(600), status=status, body="temporary error")
    mocked.add("GET", indicator_url(600), json=OK_PAYLOAD)

    df = esios_get_indicator(token, 600, params=dict(ONE_HOUR))

    assert len(mocked.calls) == 2
    assert list(df["value"]) == [1.0]


def test_429_with_retry_after_is_retried(mocked, token):
    mocked.add("GET", indicator_url(600), status=429, headers={"Retry-After": "0"}, body="slow down")
    mocked.add("GET", indicator_url(600), json=OK_PAYLOAD)

    df = esios_get_indicator(token, 600, params=dict(ONE_HOUR))

    assert len(mocked.calls) == 2
    assert not df.empty


def test_persistent_503_raises_esios_http_error_after_5_retries(mocked, token):
    mocked.add("GET", indicator_url(600), status=503, body="down")

    with pytest.raises(EsiosHTTPError) as info:
        esios_get_indicator(token, 600, params=dict(ONE_HOUR))

    assert len(mocked.calls) == 6  # 1 attempt + 5 retries
    assert info.value.response.status_code == 503
    assert isinstance(info.value, requests.HTTPError)  # compatibility with v1.1.x


def test_persistent_429_raises_esios_rate_limited(mocked, token):
    mocked.add("GET", indicator_url(600), status=429, headers={"Retry-After": "0"})

    with pytest.raises(EsiosRateLimited):
        esios_get_indicator(token, 600, params=dict(ONE_HOUR))

    assert len(mocked.calls) == 6


@pytest.mark.parametrize(("status", "exc"), [(401, EsiosAuthError), (403, EsiosAuthError), (404, EsiosNotFound)])
def test_client_errors_are_not_retried_and_raise_their_exception(mocked, token, status, exc):
    mocked.add("GET", indicator_url(600), status=status, json={"message": "no"})

    with pytest.raises(exc) as info:
        esios_get_indicator(token, 600, params=dict(ONE_HOUR))

    assert len(mocked.calls) == 1
    assert info.value.response.status_code == status
    assert isinstance(info.value, EsiosHTTPError)
    assert isinstance(info.value, requests.HTTPError)


def test_other_http_error_raises_esios_http_error(mocked, token):
    mocked.add("GET", indicator_url(600), status=400, body="bad request")

    with pytest.raises(EsiosHTTPError, match="400"):
        esios_get_indicator(token, 600, params=dict(ONE_HOUR))
    assert len(mocked.calls) == 1


def test_error_message_does_not_include_the_token(mocked, token):
    mocked.add("GET", indicator_url(600), status=401, body="unauthorized")

    with pytest.raises(EsiosAuthError) as info:
        esios_get_indicator(token, 600, params=dict(ONE_HOUR))

    assert token not in str(info.value)
    assert "401" in str(info.value)


def test_archive_also_retries_and_maps_errors(mocked, token):
    mocked.add("GET", archive_url(110), status=502)
    mocked.add("GET", archive_url(110), json=[{"a": 1}])
    assert len(esios_get_archive(token, 110)) == 1

    mocked.add("GET", archive_url(111), status=404)
    with pytest.raises(EsiosNotFound):
        esios_get_archive(token, 111)


@pytest.mark.parametrize("use_cache", [False, True])
def test_retry_policy_is_mounted_on_sessions(use_cache):
    retry = get_session(use_cache).get_adapter("https://api.esios.ree.es").max_retries

    assert retry.total == 5
    assert set(retry.status_forcelist) == set(RETRY_STATUSES)
    assert retry.respect_retry_after_header is True
    assert retry.allowed_methods == frozenset({"GET"})
    assert retry.raise_on_status is False


# --------------------------------------------------------------------------- exceptions


def test_exception_hierarchy():
    assert issubclass(EsiosSchemaError, EsiosError) and issubclass(EsiosSchemaError, ValueError)
    assert issubclass(EsiosConfigError, EsiosError) and issubclass(EsiosConfigError, ValueError)
    for exc in (EsiosAuthError, EsiosNotFound, EsiosRateLimited):
        assert issubclass(exc, EsiosHTTPError)
        assert issubclass(exc, requests.HTTPError)
        assert issubclass(exc, EsiosError)


def test_malformed_response_raises_esios_schema_error(mocked, token):
    mocked.add("GET", indicator_url(600), json={"unexpected": True})
    with pytest.raises(EsiosSchemaError):
        esios_get_indicator(token, 600, params=dict(ONE_HOUR))

    mocked.add("GET", archive_url(110), body="<html>error</html>")
    with pytest.raises(EsiosSchemaError):
        esios_get_archive(token, 110)


def test_non_numeric_value_raises_esios_schema_error(mocked, token):
    row = make_value(datetime(2025, 1, 1), 1.0)
    row["value"] = "not a number"
    mocked.add("GET", indicator_url(600), json=make_indicator_payload(600, [row]))

    with pytest.raises(EsiosSchemaError):
        esios_get_indicator(token, 600, params=dict(ONE_HOUR))


def test_missing_id_raises_esios_config_error(token):
    with pytest.raises(EsiosConfigError, match="id"):
        esios_get_indicator(token, params=dict(ONE_HOUR))
    with pytest.raises(EsiosConfigError, match="id"):
        esios_get_archive(token)


# --------------------------------------------------------------------------- optional token


def test_without_token_uses_the_environment_variable(mocked, monkeypatch):
    monkeypatch.setenv("ESIOS_API_KEY", "env-token")
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))
    mocked.add("GET", archive_url(110), json=[{"a": 1}])

    esios_get_indicator(id=600, params=dict(ONE_HOUR))
    esios_get_archive(id=110)

    assert all(c.request.headers["x-api-key"] == "env-token" for c in mocked.calls)


def test_explicit_token_takes_precedence_over_the_environment(mocked, monkeypatch, token):
    monkeypatch.setenv("ESIOS_API_KEY", "env-token")
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    esios_get_indicator(token, 600, params=dict(ONE_HOUR))

    assert mocked.calls[0].request.headers["x-api-key"] == token


@pytest.mark.parametrize("value", [None, ""])
def test_no_token_and_no_environment_variable_raises_clear_error(mocked, monkeypatch, value):
    monkeypatch.delenv("ESIOS_API_KEY", raising=False)

    with pytest.raises(EsiosConfigError, match="ESIOS_API_KEY"):
        esios_get_indicator(value, 600, params=dict(ONE_HOUR))
    with pytest.raises(EsiosConfigError, match="ESIOS_API_KEY"):
        esios_get_archive(value, 110)
    assert len(mocked.calls) == 0


# --------------------------------------------------------------------------- flexible dates


def _sent_dates(mocked) -> tuple[str, str]:
    params = query_params(mocked.calls[0].request)
    return params["start_date"], params["end_date"]


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        # The library's legacy format (UTC).
        ("2025/01/01T00:00:00Z", "2025/01/01T01:00:00Z", ("2025/01/01T00:00:00Z", "2025/01/01T01:00:00Z")),
        # ISO 8601 with a time zone.
        ("2025-01-01T00:00:00Z", "2025-01-01T02:00:00+01:00", ("2025/01/01T00:00:00Z", "2025/01/01T01:00:00Z")),
        # Timezone-aware datetime.
        (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, 1, tzinfo=timezone(timedelta(hours=-1))),
         ("2025/01/01T00:00:00Z", "2025/01/01T02:00:00Z")),
        # Timezone-aware pd.Timestamp.
        (pd.Timestamp("2025-07-01 00:00", tz="Europe/Madrid"), pd.Timestamp("2025-07-01 01:00", tz="UTC"),
         ("2025/06/30T22:00:00Z", "2025/07/01T01:00:00Z")),
    ],
)
def test_dates_with_time_zone(mocked, token, start, end, expected):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    esios_get_indicator(token, 600, params={"start_date": start, "end_date": end})

    assert _sent_dates(mocked) == expected


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        # No time zone → Madrid time (winter UTC+1, summer UTC+2).
        (date(2025, 1, 1), date(2025, 1, 2), ("2024/12/31T23:00:00Z", "2025/01/01T23:00:00Z")),
        (datetime(2025, 7, 1), datetime(2025, 7, 1, 12), ("2025/06/30T22:00:00Z", "2025/07/01T10:00:00Z")),
        ("2025-01-01", "2025-01-01T06:00", ("2024/12/31T23:00:00Z", "2025/01/01T05:00:00Z")),
        (pd.Timestamp("2025-07-01"), pd.Timestamp("2025-07-01 01:00"), ("2025/06/30T22:00:00Z", "2025/06/30T23:00:00Z")),
    ],
)
def test_dates_without_time_zone_are_interpreted_in_madrid_time(mocked, token, start, end, expected):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    esios_get_indicator(token, 600, params={"start_date": start, "end_date": end})

    assert _sent_dates(mocked) == expected


def test_params_with_non_str_dates_are_not_modified(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))
    params = {"start_date": date(2025, 1, 1), "end_date": date(2025, 1, 2)}

    esios_get_indicator(token, 600, params=params)

    assert params == {"start_date": date(2025, 1, 1), "end_date": date(2025, 1, 2)}


def test_start_later_than_end_raises_error(mocked, token):
    with pytest.raises(EsiosConfigError, match="later than"):
        esios_get_indicator(token, 600, params={"start_date": "2025-02-01", "end_date": "2025-01-01"})
    assert len(mocked.calls) == 0


@pytest.mark.parametrize("value", ["not a date", "2025-13-45", 20250101, ["2025-01-01"]])
def test_invalid_date_raises_error(mocked, token, value):
    with pytest.raises(EsiosConfigError, match="start_date"):
        esios_get_indicator(token, 600, params={"start_date": value, "end_date": "2025-01-02"})
    assert len(mocked.calls) == 0


@pytest.mark.parametrize("value", ["2025-10-26T02:30", "2025-03-30T02:30"])
def test_ambiguous_or_non_existent_madrid_time_raises_error(mocked, token, value):
    # 2025-10-26 02:30 happens twice; 2025-03-30 02:30 does not exist.
    with pytest.raises(EsiosConfigError, match="time zone"):
        esios_get_indicator(token, 600, params={"start_date": value, "end_date": "2025-12-01"})


# --------------------------------------------------------------------------- output types


def test_output_types_are_normalised(mocked, token):
    rows = [make_value(datetime(2025, 1, 1), 1), make_value(datetime(2025, 1, 1, 1), 2)]  # integers in the JSON
    mocked.add("GET", indicator_url(600), json=make_indicator_payload(600, rows))

    df = esios_get_indicator(token, 600, params=dict(ONE_HOUR))

    assert df["value"].dtype == "float64"
    assert df["geo_id"].dtype == "Int64"
    assert str(df.index.dtype) == "datetime64[ns, UTC]"
    assert df.index.name == "datetime_utc"


def test_output_types_with_empty_dataframe(mocked, token):
    mocked.add("GET", indicator_url(600), json=make_indicator_payload(600, []))

    df = esios_get_indicator(token, 600, params=dict(ONE_HOUR))

    assert df.empty
    assert df["value"].dtype == "float64"
    assert df["geo_id"].dtype == "Int64"
    assert str(df.index.dtype) == "datetime64[ns, UTC]"


def test_null_values_are_kept_as_nan(mocked, token):
    row = make_value(datetime(2025, 1, 1), 1.0)
    row["value"] = None
    mocked.add("GET", indicator_url(600), json=make_indicator_payload(600, [row]))

    df = esios_get_indicator(token, 600, params=dict(ONE_HOUR))

    assert df["value"].isna().all()
    assert df["value"].dtype == "float64"


# --------------------------------------------------------------------------- logging


def test_logging_records_blocks_without_the_token(mocked, token, caplog):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    with caplog.at_level(logging.DEBUG, logger="esios_request"):
        esios_get_indicator(token, 600, params={"start_date": "2025/01/01T00:00:00Z", "end_date": "2026/03/01T00:00:00Z"})

    messages = [r.getMessage() for r in caplog.records if r.name == "esios_request"]
    assert any("3 block(s)" in m for m in messages)
    assert sum("block" in m and "rows" in m for m in messages) == 3
    assert all(token not in m for m in messages)


def test_the_library_prints_nothing(mocked, token, capsys):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    esios_get_indicator(token, 600, params=dict(ONE_HOUR))

    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""
