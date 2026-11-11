"""
Phase 4 tests (v1.4.0): 1-month default blocks and the response cache (lazy session, persistent
directory, per-request expiry, whole calendar blocks and ``clear_cache``).

The ``isolated_cache`` fixture (autouse, in ``conftest.py``) points the cache to a temporary directory.
"""

import json
import time
from datetime import datetime

import pandas as pd
import pytest
import requests

import esios_request
from esios_request import (
    EsiosClient,
    EsiosConfigError,
    _core,
    clear_cache,
    esios_get_indicator,
    req_cache,
)
from esios_request._core import DEFAULT_BLOCK_MONTHS, _block_bounds, _block_ranges

from .conftest import (
    BASE_URL,
    FMT,
    archive_url,
    boundary_callback,
    indicator_url,
    make_indicator_payload,
    make_value,
    query_params,
    sent_blocks,
)

# "Now" for the tests that depend on which blocks are closed: mid June 2025.
NOW = datetime(2025, 6, 15, 12)


@pytest.fixture
def now(monkeypatch):
    monkeypatch.setattr(_core, "_utcnow", lambda: NOW)
    return NOW


def hourly_callback(indicator_id: int):
    """Mimics the API: one value per hour inside [start_date, end_date] (both inclusive)."""

    def _cb(request):
        params = query_params(request)
        start = datetime.strptime(params["start_date"], FMT)
        end = datetime.strptime(params["end_date"], FMT)
        hours = pd.date_range(pd.Timestamp(start).ceil("h"), end, freq="h")
        values = [make_value(hour.to_pydatetime(), hour.timestamp() / 3600) for hour in hours]
        return 200, {}, json.dumps(make_indicator_payload(indicator_id, values))

    return _cb


def cached_expiries(client) -> list:
    """``expires`` of every response stored in the client's cache (None = never expires)."""
    return [response.expires for response in client.session.cache.filter(expired=True)]


# --------------------------------------------------------------------------- default block size


def test_default_block_is_one_month(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    with EsiosClient(token) as client:
        client.indicator(600, "2025/01/01T00:00:00Z", "2025/03/15T00:00:00Z")

    assert DEFAULT_BLOCK_MONTHS == 1
    assert client.block_months == 1
    assert sent_blocks(mocked) == [
        ("2025/01/01T00:00:00Z", "2025/01/31T22:59:59Z"),
        ("2025/01/31T23:00:00Z", "2025/02/28T22:59:59Z"),
        ("2025/02/28T23:00:00Z", "2025/03/15T00:00:00Z"),
    ]


def test_calendar_blocks_do_not_depend_on_the_range_start():
    start, end = datetime(2025, 2, 15), datetime(2025, 8, 1)

    from_start = _block_ranges(start, end, None, 3)
    calendar = _block_ranges(start, end, None, 3, calendar=True)

    # Without ``calendar`` the first boundary is 3 months after the start's month (May 1st, Madrid).
    assert from_start[1][0] == datetime(2025, 4, 30, 22)
    # With ``calendar`` boundaries fall on the quarters (April 1st, July 1st, Madrid).
    assert [block_start for block_start, _ in calendar] == [start, datetime(2025, 3, 31, 22), datetime(2025, 6, 30, 22)]
    assert _block_bounds(start, 3, calendar=True) == (datetime(2024, 12, 31, 23), datetime(2025, 3, 31, 22))


# --------------------------------------------------------------------------- lazy session and directory


def test_cached_session_is_created_lazily(token, isolated_cache):
    assert req_cache._sessions == {}

    with EsiosClient(token) as client:
        assert client.cache_dir is None
    assert req_cache._sessions == {}
    assert not isolated_cache.exists()

    client = EsiosClient(token, use_cache=True)

    assert list(req_cache._sessions) == [isolated_cache.resolve()]
    assert client.cache_dir == isolated_cache.resolve()
    assert isolated_cache.is_dir()


def test_clients_with_the_same_cache_dir_share_the_session(token, tmp_path):
    first = EsiosClient(token, use_cache=True)
    second = EsiosClient(token, use_cache=True)
    other = EsiosClient(token, use_cache=True, cache_dir=tmp_path / "other")

    assert first.session is second.session
    assert other.session is not first.session
    assert other.cache_dir == (tmp_path / "other").resolve()
    assert (tmp_path / "other").is_dir()


def test_cache_dir_priority_argument_then_environment_then_user_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(req_cache.CACHE_DIR_ENV_VAR, str(tmp_path / "from_env"))
    assert req_cache.resolve_cache_dir(tmp_path / "from_arg") == (tmp_path / "from_arg").resolve()
    assert req_cache.resolve_cache_dir() == (tmp_path / "from_env").resolve()

    monkeypatch.delenv(req_cache.CACHE_DIR_ENV_VAR)
    default = req_cache.resolve_cache_dir()
    assert "esios_request" in default.parts
    assert tmp_path not in default.parents


@pytest.mark.parametrize("ttl", [-1, True, "600", None, float("inf"), float("nan")])
def test_invalid_cache_recent_ttl_raises_error(token, ttl):
    with pytest.raises(EsiosConfigError, match="cache_recent_ttl"):
        EsiosClient(token, use_cache=True, cache_recent_ttl=ttl)


def test_user_session_is_used_as_is_even_with_use_cache(mocked, token, isolated_cache):
    mocked.add_callback("GET", indicator_url(600), callback=hourly_callback(600))
    session = requests.Session()

    with EsiosClient(token, session=session, use_cache=True) as client:
        client.indicator(600, "2025/01/10T00:00:00Z", "2025/01/12T00:00:00Z")

    assert client.session is session
    assert sent_blocks(mocked) == [("2025/01/10T00:00:00Z", "2025/01/12T00:00:00Z")]  # exact dates
    assert not isolated_cache.exists()


# --------------------------------------------------------------------------- closed blocks


def test_repeating_a_historical_download_makes_no_requests(mocked, token, now):
    mocked.add_callback("GET", indicator_url(600), callback=hourly_callback(600))
    client = EsiosClient(token, use_cache=True)

    first = client.indicator(600, "2025/01/10T00:00:00Z", "2025/03/20T00:00:00Z")
    requests_made = len(mocked.calls)
    second = client.indicator(600, "2025/01/10T00:00:00Z", "2025/03/20T00:00:00Z")

    assert requests_made == 3
    assert len(mocked.calls) == requests_made
    pd.testing.assert_frame_equal(first, second)
    assert cached_expiries(client) == [None, None, None]  # closed blocks never expire


def test_closed_blocks_are_requested_whole_and_trimmed(mocked, token, now):
    mocked.add_callback("GET", indicator_url(600), callback=hourly_callback(600))

    with EsiosClient(token) as plain:
        expected = plain.indicator(600, "2025/01/10T00:00:00Z", "2025/03/20T00:00:00Z")
    mocked.calls.reset()
    result = EsiosClient(token, use_cache=True).indicator(600, "2025/01/10T00:00:00Z", "2025/03/20T00:00:00Z")

    # Whole calendar months (Madrid time), whatever the requested range.
    assert sent_blocks(mocked) == [
        ("2024/12/31T23:00:00Z", "2025/01/31T22:59:59Z"),
        ("2025/01/31T23:00:00Z", "2025/02/28T22:59:59Z"),
        ("2025/02/28T23:00:00Z", "2025/03/31T21:59:59Z"),
    ]
    pd.testing.assert_frame_equal(result, expected)
    assert result.index.min() == pd.Timestamp("2025-01-10T00:00Z")
    assert result.index.max() == pd.Timestamp("2025-03-20T00:00Z")


def test_a_different_range_reuses_the_cached_blocks(mocked, token, now):
    mocked.add_callback("GET", indicator_url(600), callback=hourly_callback(600))
    client = EsiosClient(token, use_cache=True)
    client.indicator(600, "2025/01/10T00:00:00Z", "2025/03/20T00:00:00Z")
    requests_made = len(mocked.calls)

    result = client.indicator(600, "2025/01/25T06:00:00Z", "2025/02/03T18:00:00Z")

    assert len(mocked.calls) == requests_made
    assert result.index.min() == pd.Timestamp("2025-01-25T06:00Z")
    assert result.index.max() == pd.Timestamp("2025-02-03T18:00Z")
    assert len(result) == 9 * 24 + 13


def test_legacy_function_uses_the_cache(mocked, token, now):
    mocked.add_callback("GET", indicator_url(600), callback=hourly_callback(600))
    params = {"start_date": "2025/01/10T00:00:00Z", "end_date": "2025/01/12T00:00:00Z"}

    first = esios_get_indicator(token, 600, params=params, use_cache=True)
    second = esios_get_indicator(token, 600, params=params, use_cache=True)

    assert len(mocked.calls) == 1
    pd.testing.assert_frame_equal(first, second)


def test_parallel_download_with_cache_matches_download_without_cache(mocked, token, now):
    mocked.add_callback("GET", indicator_url(600), callback=hourly_callback(600))
    date_range = ("2024/03/10T00:00:00Z", "2025/02/20T00:00:00Z")

    with EsiosClient(token, max_workers=1) as plain:
        expected = plain.indicator(600, *date_range)
    cached = EsiosClient(token, use_cache=True, max_workers=4)
    first = cached.indicator(600, *date_range)
    requests_made = len(mocked.calls)
    second = cached.indicator(600, *date_range)

    pd.testing.assert_frame_equal(first, expected)
    pd.testing.assert_frame_equal(second, expected)
    assert len(mocked.calls) == requests_made


# --------------------------------------------------------------------------- open blocks


def test_open_block_is_requested_with_exact_dates_and_always_refreshed(mocked, token, now):
    mocked.add_callback("GET", indicator_url(600), callback=hourly_callback(600))
    client = EsiosClient(token, use_cache=True, cache_recent_ttl=0)
    date_range = ("2025/05/20T00:00:00Z", "2025/06/15T18:00:00Z")  # ends after "now"

    client.indicator(600, *date_range)
    assert sent_blocks(mocked) == [
        ("2025/04/30T22:00:00Z", "2025/05/31T21:59:59Z"),  # May is closed: whole block
        ("2025/05/31T22:00:00Z", "2025/06/15T18:00:00Z"),  # June is open: exact dates
    ]

    mocked.calls.reset()
    client.indicator(600, *date_range)

    assert sent_blocks(mocked) == [("2025/05/31T22:00:00Z", "2025/06/15T18:00:00Z")]


def test_open_block_is_cached_until_the_recent_ttl_passes(mocked, token, now):
    mocked.add_callback("GET", indicator_url(600), callback=hourly_callback(600))
    # requests-cache works in whole seconds: 0.4 is rounded up to 1 s (not down to "do not cache").
    client = EsiosClient(token, use_cache=True, cache_recent_ttl=0.4)
    date_range = ("2025/06/10T00:00:00Z", "2025/06/15T18:00:00Z")

    client.indicator(600, *date_range)
    client.indicator(600, *date_range)
    assert len(mocked.calls) == 1
    expiries = cached_expiries(client)
    assert len(expiries) == 1 and expiries[0] is not None

    time.sleep(1.2)
    client.indicator(600, *date_range)
    assert len(mocked.calls) == 2


def test_past_range_inside_the_open_block_never_expires(mocked, token, now):
    mocked.add_callback("GET", indicator_url(600), callback=hourly_callback(600))
    client = EsiosClient(token, use_cache=True, cache_recent_ttl=0)

    client.indicator(600, "2025/06/02T00:00:00Z", "2025/06/05T00:00:00Z")
    client.indicator(600, "2025/06/02T00:00:00Z", "2025/06/05T00:00:00Z")

    # June is still open, so it is not requested whole; but the requested window is closed.
    assert sent_blocks(mocked) == [("2025/06/02T00:00:00Z", "2025/06/05T00:00:00Z")]
    assert cached_expiries(client) == [None]


def test_aggregated_calls_keep_exact_dates(mocked, token, now):
    mocked.add_callback("GET", indicator_url(600), callback=hourly_callback(600))
    client = EsiosClient(token, use_cache=True)
    date_range = ("2025/01/10T00:00:00Z", "2025/02/20T00:00:00Z")

    client.indicator(600, *date_range, time_trunc="day", time_agg="average")
    client.indicator(600, *date_range, time_trunc="day", time_agg="average")

    # Not requested whole (the aggregates at the edges would change), but cached all the same.
    assert sent_blocks(mocked) == [
        ("2025/01/10T00:00:00Z", "2025/01/31T22:59:59Z"),
        ("2025/01/31T23:00:00Z", "2025/02/20T00:00:00Z"),
    ]


# --------------------------------------------------------------------------- other endpoints


def test_metadata_is_cached_and_archives_follow_the_recent_ttl(mocked, token):
    mocked.add("GET", indicator_url(600), json={"indicator": {"id": 600, "name": "test"}})
    mocked.add("GET", f"{BASE_URL}/indicators", json={"indicators": [{"id": 600, "name": "test"}]})
    mocked.add("GET", archive_url(110), json=[{"a": 1}])
    client = EsiosClient(token, use_cache=True, cache_recent_ttl=0)

    for _ in range(2):
        client.indicator_info(600)
        client.search("test")
        client.archive(110)

    urls = [call.request.url.split("?")[0] for call in mocked.calls]
    assert urls.count(indicator_url(600)) == 1
    assert urls.count(f"{BASE_URL}/indicators") == 1
    assert urls.count(archive_url(110)) == 2


# --------------------------------------------------------------------------- redirects

# The API answers large requests with a 307 to a pre-signed temporary file in S3 (verified 2026-11-11).
S3_FILE = "https://s3.eu-west-1.amazonaws.com/bucket/temp/file.json"


@pytest.mark.parametrize("use_cache", [False, True])
def test_token_is_not_forwarded_to_another_host_on_redirect(mocked, token, now, use_cache):
    values = [make_value(datetime(2025, 1, 10, 12), 1.0)]
    mocked.add("GET", indicator_url(600), status=307, headers={"Location": f"{S3_FILE}?X-Amz-Signature=abc"})
    mocked.add("GET", S3_FILE, json=make_indicator_payload(600, values))
    client = EsiosClient(token, use_cache=use_cache)

    df = client.indicator(600, "2025/01/10T00:00:00Z", "2025/01/12T00:00:00Z")

    to_api, to_s3 = (call.request for call in mocked.calls)
    assert to_api.headers["x-api-key"] == token
    assert to_s3.url.startswith(S3_FILE)
    assert "x-api-key" not in to_s3.headers
    assert df["value"].tolist() == [1.0]

    if use_cache:  # the redirected response is cached under the original URL
        again = client.indicator(600, "2025/01/10T00:00:00Z", "2025/01/12T00:00:00Z")
        assert len(mocked.calls) == 2
        pd.testing.assert_frame_equal(again, df)
    client.close()


def test_token_is_kept_on_a_redirect_within_the_api_host(mocked, token):
    values = [make_value(datetime(2025, 1, 10, 12), 1.0)]
    mocked.add("GET", indicator_url(600), status=307, headers={"Location": f"{BASE_URL}/moved/600"})
    mocked.add("GET", f"{BASE_URL}/moved/600", json=make_indicator_payload(600, values))

    with EsiosClient(token) as client:
        df = client.indicator(600, "2025/01/10T00:00:00Z", "2025/01/12T00:00:00Z")

    assert [call.request.headers.get("x-api-key") for call in mocked.calls] == [token, token]
    assert df["value"].tolist() == [1.0]


def test_legacy_request_function_does_not_forward_the_token_either(mocked, token):
    from esios_request.esios_request import esios_get_request

    mocked.add("GET", indicator_url(600), status=307, headers={"Location": S3_FILE})
    mocked.add("GET", S3_FILE, json=make_indicator_payload(600, []))

    response = esios_get_request(token, indicator_url(600))

    assert response.status_code == 200
    assert "x-api-key" not in mocked.calls[1].request.headers


# --------------------------------------------------------------------------- clearing and privacy


def test_clear_cache_forces_a_new_download(mocked, token, now):
    mocked.add_callback("GET", indicator_url(600), callback=hourly_callback(600))
    client = EsiosClient(token, use_cache=True)
    date_range = ("2025/01/10T00:00:00Z", "2025/01/12T00:00:00Z")
    client.indicator(600, *date_range)

    client.clear_cache()
    client.indicator(600, *date_range)
    assert len(mocked.calls) == 2

    clear_cache()  # module-level function, default (isolated) directory
    client.indicator(600, *date_range)
    assert len(mocked.calls) == 3
    assert esios_request.clear_cache is clear_cache


def test_clear_cache_expired_only_keeps_what_has_not_expired(mocked, token, now):
    mocked.add_callback("GET", indicator_url(600), callback=hourly_callback(600))
    client = EsiosClient(token, use_cache=True, cache_recent_ttl=1)
    closed = ("2025/01/10T00:00:00Z", "2025/01/12T00:00:00Z")
    still_open = ("2025/06/10T00:00:00Z", "2025/06/15T18:00:00Z")
    client.indicator(600, *closed)
    client.indicator(600, *still_open)
    assert len(cached_expiries(client)) == 2
    time.sleep(1.2)

    client.clear_cache(expired_only=True)

    assert cached_expiries(client) == [None]
    client.indicator(600, *closed)
    assert len(mocked.calls) == 2


def test_clear_cache_does_not_create_a_cache(token, tmp_path):
    clear_cache(tmp_path / "never_used")
    with EsiosClient(token) as client:
        client.clear_cache()

    assert not (tmp_path / "never_used").exists()
    assert req_cache._sessions == {}


def test_token_is_not_written_to_the_cache(mocked, isolated_cache, now):
    mocked.add_callback("GET", indicator_url(600), callback=hourly_callback(600))
    secret = "very-secret-token-1234567890"

    EsiosClient(secret, use_cache=True).indicator(600, "2025/01/10T00:00:00Z", "2025/01/12T00:00:00Z")
    req_cache._close_sessions()

    files = [path for path in isolated_cache.iterdir() if path.is_file()]
    assert files
    assert all(secret.encode() not in path.read_bytes() for path in files)
