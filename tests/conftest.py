"""
Shared test utilities.

No test calls the real API: every request is intercepted with ``responses``.
"""

import json
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest
import responses

BASE_URL = "https://api.esios.ree.es"
FMT = "%Y/%m/%dT%H:%M:%SZ"
FAKE_TOKEN = "test-token"


def indicator_url(indicator_id: int) -> str:
    return f"{BASE_URL}/indicators/{indicator_id}"


def archive_url(archive_id: int) -> str:
    return f"{BASE_URL}/archives/{archive_id}/download_json"


def query_params(request) -> dict[str, str]:
    """Query parameters of an intercepted request, as a plain dict."""
    return {k: v[0] for k, v in parse_qs(urlparse(request.url).query).items()}


def make_value(dt: datetime, value: float, geo_id: int = 3, geo_name: str = "España") -> dict:
    iso = dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {
        "value": value,
        "datetime": iso,
        "datetime_utc": iso.replace(".000Z", "Z"),
        "tz_time": iso,
        "geo_id": geo_id,
        "geo_name": geo_name,
    }


def make_indicator_payload(indicator_id: int, values: list[dict]) -> dict:
    return {"indicator": {"id": indicator_id, "name": "test", "values": values}}


def boundary_callback(indicator_id: int, geos: list[tuple[int, str]] | None = None):
    """
    Callback that mimics the API: returns one value at ``start_date`` and another at ``end_date``
    (``end_date`` is inclusive), one per given geo.
    """
    geos = geos or [(3, "España")]

    def _cb(request):
        params = query_params(request)
        start = datetime.strptime(params["start_date"], FMT)
        end = datetime.strptime(params["end_date"], FMT)
        values = [
            make_value(dt, float(i), geo_id, geo_name)
            for dt in (start, end)
            for i, (geo_id, geo_name) in enumerate(geos)
        ]
        return 200, {}, json.dumps(make_indicator_payload(indicator_id, values))

    return _cb


@pytest.fixture
def token() -> str:
    return FAKE_TOKEN


@pytest.fixture
def mocked():
    """Enable ``responses``: any unregistered request fails."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


def daily_average(start: datetime, end: datetime) -> list[dict]:
    """
    Mimics the real API's ``time_trunc=day`` + ``time_agg=average``: averages a deterministic hourly
    series **only within [start, end]**, grouped by Madrid day. If the range cuts a day in half,
    that day comes back with a partial average (verified against the real API on 2026-11-10 with
    indicator 600: full 2025-07-01 = 111.2; cut at 00:00Z = 123.3).
    """
    hours = pd.date_range(start, end, freq="h", tz="UTC")
    series = pd.Series(hours.hour + hours.day / 100, index=hours, dtype=float)
    local_day = series.index.tz_convert("Europe/Madrid").normalize()
    daily = series.groupby(local_day).mean()
    return [
        make_value(day.tz_convert("UTC").tz_localize(None).to_pydatetime(), round(value, 6))
        for day, value in daily.items()
    ]


def daily_trunc_callback(indicator_id: int):
    def _cb(request):
        params = query_params(request)
        start = datetime.strptime(params["start_date"], FMT)
        end = datetime.strptime(params["end_date"], FMT)
        return 200, {}, json.dumps(make_indicator_payload(indicator_id, daily_average(start, end)))

    return _cb
