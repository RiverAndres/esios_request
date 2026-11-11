"""
Internal building blocks shared by ``EsiosClient`` and the legacy functions: constants, token and
date handling, HTTP error mapping, response parsing and block splitting.
"""

import html
import logging
import math
import os
import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import requests_cache
from dateutil.relativedelta import relativedelta

from .exceptions import (
    EsiosAuthError,
    EsiosConfigError,
    EsiosHTTPError,
    EsiosNotFound,
    EsiosRateLimited,
    EsiosSchemaError,
)
from .req_cache import get_session

logger = logging.getLogger("esios_request")

BASE_URL = "https://api.esios.ree.es"
DATE_FMT = "%Y/%m/%dT%H:%M:%SZ"
TOKEN_ENV_VAR = "ESIOS_API_KEY"
DEFAULT_TIMEOUT = (5, 180)
# Default block length in months. One month keeps every response small: large responses are
# served through a slow redirect to a temporary file (verified against the real API on 2026-11-11:
# two years of indicator 600, Spain only, took 7.9 s in 24 one-month blocks and 13.1 s in 4
# six-month blocks, with no 429).
DEFAULT_BLOCK_MONTHS = 1
BLOCK_SIZE = relativedelta(months = DEFAULT_BLOCK_MONTHS)
# With ``time_trunc=year`` a shorter block would split the year, so 12-month blocks are used
# (verified against the real API on 2026-11-10: it accepts a full year with time_trunc=year).
YEAR_BLOCK_SIZE = relativedelta(years = 1)
# The API aligns ``time_trunc`` periods to Spanish peninsular time. It is also the time zone used
# to interpret dates without a time zone passed by the user.
API_TZ = ZoneInfo("Europe/Madrid")

DEFAULT_HEADERS: dict[str, str] = {
    "Accept": "application/json; application/vnd.esios-api-v1+json",
    "Content-Type": "application/json",
    "User-Agent": "PostmanRuntime/7.39.1",
}

# Columns of ``indicator.values`` (without ``datetime_utc``, which becomes the index).
INDICATOR_COLUMNS = ["value", "datetime", "tz_time", "geo_id", "geo_name"]

_HTTP_ERRORS: dict[int, type[EsiosHTTPError]] = {
    401: EsiosAuthError,
    403: EsiosAuthError,
    404: EsiosNotFound,
    429: EsiosRateLimited,
}


# --------------------------------------------------------------------------- input handling


def _resolve_token(token:str | None) -> str:
    """Return ``token`` or, if not given, the one in the ``ESIOS_API_KEY`` environment variable."""
    token = token or os.environ.get(TOKEN_ENV_VAR)
    if not token:
        raise EsiosConfigError(
            f"Missing e·sios token: pass it as an argument or set the {TOKEN_ENV_VAR} environment variable."
        )
    return token


def _to_utc(value, name:str) -> datetime:
    """
    Convert a date to a naive UTC ``datetime``.

    Accepts ``str`` (ISO 8601 or ``"%Y/%m/%dT%H:%M:%SZ"``), ``datetime``, ``date`` and ``pd.Timestamp``.
    Dates **without a time zone** are interpreted in Madrid time (``Europe/Madrid``).
    """
    if not isinstance(value, (str, datetime, date)):
        raise EsiosConfigError(f"{name} must be str, datetime, date or pd.Timestamp; got {type(value).__name__}.")
    try:
        ts = pd.Timestamp(value)
    except (ValueError, TypeError) as exc:
        raise EsiosConfigError(f"{name} is not a valid date: {value!r}.") from exc
    if pd.isna(ts):
        raise EsiosConfigError(f"{name} is not a valid date: {value!r}.")

    if ts.tzinfo is None:
        try:
            ts = ts.tz_localize(API_TZ)
        except Exception as exc:  # ambiguous or non-existent time due to a DST change
            raise EsiosConfigError(
                f"{name}={value!r} is ambiguous or does not exist in Madrid time (DST change); "
                "specify the time zone explicitly."
            ) from exc
    return ts.tz_convert("UTC").tz_localize(None).to_pydatetime()


def _resolve_range(start, end) -> tuple[datetime, datetime]:
    """Validate and convert ``start``/``end`` to naive UTC. Both are required and ``start <= end``."""
    missing = [name for name, value in (("start_date", start), ("end_date", end)) if value is None or value == ""]
    if missing:
        raise EsiosConfigError(f"Missing required parameters: {', '.join(missing)}.")
    start_utc = _to_utc(start, "start_date")
    end_utc = _to_utc(end, "end_date")
    if start_utc > end_utc:
        raise EsiosConfigError(
            f"start_date ({start_utc:%Y-%m-%d %H:%M:%S} UTC) is later than end_date ({end_utc:%Y-%m-%d %H:%M:%S} UTC)."
        )
    return start_utc, end_utc


# --------------------------------------------------------------------------- HTTP


def esios_get_request(
    token:str | None,
    url:str,
    headers:dict | None = None,
    params:dict | None = None,
    session:requests.Session | requests_cache.CachedSession | None = None,
    ) -> requests.Response:
    """
    Get request with token type ``x-api-key`` (with retries when ``session`` is None).

    ``headers`` and ``params`` are never modified. If ``token`` is None, ``ESIOS_API_KEY`` is used.

    Returns
    -----
    ``object`` requests.get.response
    """

    request_headers = {**(headers if headers is not None else DEFAULT_HEADERS), "x-api-key": _resolve_token(token)}
    if session is None:
        session = get_session(False)

    response = session.get(url = url, headers = request_headers, params = params, timeout = DEFAULT_TIMEOUT)
    return response


def _raise_for_status(res:requests.Response) -> None:
    """Raise the matching ``EsiosHTTPError`` if the response is an HTTP error."""
    if res.status_code < 400:
        return
    cls = _HTTP_ERRORS.get(res.status_code, EsiosHTTPError)
    detail = (res.text or "").strip()[:200]
    url = (res.url or "").split("?")[0]
    error = cls(f"{res.status_code} {res.reason} at {url}: {detail}")
    error.response = res
    error.request = res.request
    raise error


def _json(res:requests.Response, url:str):
    try:
        return res.json()
    except ValueError as exc:
        raise EsiosSchemaError(f"Unexpected response from {url}: not valid JSON.") from exc


# --------------------------------------------------------------------------- indicators


def _empty_indicator_frame() -> pd.DataFrame:
    """Empty DataFrame with the same shape and types as an indicator with data."""
    index = pd.DatetimeIndex([], tz = "UTC", name = "datetime_utc").as_unit("ns")
    df = pd.DataFrame(columns = INDICATOR_COLUMNS, index = index)
    return df.astype({"value": "float64", "geo_id": "Int64"})


def _normalize_types(df:pd.DataFrame, url:str) -> pd.DataFrame:
    """``value`` → float64, ``geo_id`` → Int64, index → ``datetime64[ns, UTC]``."""
    try:
        df.index = pd.to_datetime(df.index, utc = True).as_unit("ns")
        if "value" in df.columns:
            df["value"] = df["value"].astype("float64")
        if "geo_id" in df.columns:
            df["geo_id"] = df["geo_id"].astype("Int64")
    except (ValueError, TypeError) as exc:
        raise EsiosSchemaError(f"Unexpected response from {url}: invalid types ({exc}).") from exc
    df.index.name = "datetime_utc"
    return df


def _parse_indicator_values(payload, url:str) -> pd.DataFrame:
    """Convert the ``/indicators/{id}`` JSON into a DataFrame. Raises ``EsiosSchemaError`` on an unexpected format."""
    try:
        values = payload["indicator"]["values"]
    except (KeyError, TypeError) as exc:
        raise EsiosSchemaError(f"Unexpected response from {url}: missing 'indicator.values'.") from exc

    if not isinstance(values, list):
        raise EsiosSchemaError(f"Unexpected response from {url}: 'indicator.values' is not a list.")
    if not values:
        return _empty_indicator_frame()

    df = pd.DataFrame(values)
    if "datetime_utc" not in df.columns:
        raise EsiosSchemaError(f"Unexpected response from {url}: values have no 'datetime_utc'.")

    return _normalize_types(df.set_index("datetime_utc"), url)


def _combine_blocks(frames:list[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate block frames (in block order) and dedupe by (instant, geo)."""
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return _empty_indicator_frame()

    df = pd.concat(frames)

    # Blocks do not overlap, but dedupe anyway as a safety net (in case the API returned an
    # instant outside the requested range). By (instant, geo) so no geography is lost.
    keys = df.index.to_frame(index = False)
    if "geo_id" in df.columns:
        keys["geo_id"] = df["geo_id"].to_numpy()
    return df[~keys.duplicated(keep = "first").to_numpy()]


def _utcnow() -> datetime:
    """Current instant as naive UTC (a function so the tests can replace it)."""
    return datetime.now(UTC).replace(tzinfo = None)


def _block_bounds(instant:datetime, months:int, yearly:bool = False, calendar:bool = False) -> tuple[datetime, datetime]:
    """
    Bounds ``(first instant, next boundary)`` of the block of ``months`` months containing
    ``instant``, all naive UTC. The block starts on the Madrid-time month start of ``instant``
    (year start with ``yearly``). With ``calendar`` it starts on a fixed calendar grid instead
    (months counted from year 0), so the bounds do not depend on where the requested range starts.
    """
    local = instant.replace(tzinfo = UTC).astimezone(API_TZ)
    index = local.year * 12 + (0 if yearly else local.month - 1)
    if calendar:
        index -= index % months
    floor = datetime(index // 12, index % 12 + 1, 1, tzinfo = API_TZ)
    boundary = floor + relativedelta(months = months)
    return floor.astimezone(UTC).replace(tzinfo = None), boundary.astimezone(UTC).replace(tzinfo = None)


def _next_block_boundary(start:datetime, months:int, yearly:bool) -> datetime:
    """
    Next block boundary after ``start`` (naive UTC): the Madrid-time month start ``months`` after
    ``start``'s month (with ``yearly``, the year start ``months`` after ``start``'s year). Returns naive UTC.
    """
    return _block_bounds(start, months, yearly)[1]


def _block_months(time_trunc:str | None, block_months:int) -> tuple[int, bool]:
    """Validated block length in months and whether blocks are yearly (``time_trunc="year"``)."""
    if isinstance(block_months, bool) or not isinstance(block_months, int) or block_months < 1:
        raise EsiosConfigError(f"block_months must be a positive integer; got {block_months!r}.")
    yearly = time_trunc == "year"
    return (12 * math.ceil(block_months / 12) if yearly else block_months), yearly


def _block_ranges(
    start:datetime,
    end:datetime,
    time_trunc:str | None = None,
    block_months:int = DEFAULT_BLOCK_MONTHS,
    calendar:bool = False,
    ) -> list[tuple[datetime, datetime]]:
    """
    Split ``[start, end]`` (both inclusive, naive UTC) into **non-overlapping** blocks of up to
    ``block_months`` months whose boundaries fall on month starts in Madrid time. With
    ``time_trunc="year"`` boundaries fall on year starts (blocks of a whole number of years).

    This way no ``time_trunc`` period (day, month, year…) is split between two blocks: if it were,
    the API would return a partial aggregate in each block.
    Each block ends 1 s before the boundary because ``end_date`` is inclusive.

    With ``calendar`` the boundaries fall on a fixed calendar grid (see ``_block_bounds``), so two
    different ranges produce the same inner blocks; used with the cache.
    """
    months, yearly = _block_months(time_trunc, block_months)
    blocks = []
    block_start = start
    while block_start <= end:
        boundary = _block_bounds(block_start, months, yearly, calendar)[1]
        blocks.append((block_start, min(boundary - timedelta(seconds = 1), end)))
        block_start = boundary
    return blocks


# --------------------------------------------------------------------------- archives and metadata


def _parse_archive(payload, url:str) -> pd.DataFrame:
    """``download_json`` payload → DataFrame (flat list of rows, or first key of an object)."""
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and payload:
        rows = next(iter(payload.values()))
    else:
        raise EsiosSchemaError(f"Unexpected response from {url}: expected a list or a non-empty JSON object.")

    if isinstance(rows, list) and not all(isinstance(row, dict) for row in rows):
        raise EsiosSchemaError(f"Unexpected response from {url}: rows are not JSON objects.")

    return pd.DataFrame(rows)


_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def _html_to_text(value) -> str | None:
    """Strip HTML tags and entities from the API's ``description`` fields."""
    if not isinstance(value, str):
        return None
    return _SPACE_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", value))).strip()


def _names(value) -> str | None:
    """``[{"name": "A", "id": 1}, {"name": "B", …}]`` → ``"A, B"``."""
    if not isinstance(value, list):
        return None
    names = [item["name"] for item in value if isinstance(item, dict) and item.get("name")]
    return ", ".join(names) or None


INFO_COLUMNS = [
    "name", "short_name", "unit", "granularity", "universe", "geos",
    "composited", "disaggregated", "values_updated_at", "description",
]


def _parse_indicator_info(payload, url:str) -> dict:
    """``/indicators/{id}?values=false`` payload → flat dict with ``id`` + ``INFO_COLUMNS``."""
    try:
        meta = payload["indicator"]
        indicator_id = int(meta["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise EsiosSchemaError(f"Unexpected response from {url}: missing 'indicator.id'.") from exc
    return {
        "id": indicator_id,
        "name": meta.get("name"),
        "short_name": meta.get("short_name"),
        "unit": _names(meta.get("magnitud")),
        "granularity": _names(meta.get("tiempo")),
        "universe": _names(meta.get("universe")),
        "geos": meta.get("geos") if isinstance(meta.get("geos"), list) else [],
        "composited": meta.get("composited"),
        "disaggregated": meta.get("disaggregated"),
        "values_updated_at": meta.get("values_updated_at"),
        "description": _html_to_text(meta.get("description")),
    }


SEARCH_COLUMNS = ["name", "short_name", "description"]


def _parse_search(payload, url:str) -> pd.DataFrame:
    """``/indicators`` payload → DataFrame indexed by ``id`` with ``SEARCH_COLUMNS``."""
    try:
        items = payload["indicators"]
    except (KeyError, TypeError) as exc:
        raise EsiosSchemaError(f"Unexpected response from {url}: missing 'indicators'.") from exc
    if not isinstance(items, list) or not all(isinstance(item, dict) and "id" in item for item in items):
        raise EsiosSchemaError(f"Unexpected response from {url}: 'indicators' is not a list of indicators.")

    df = pd.DataFrame(
        [{"id": int(item["id"]), **{col: item.get(col) for col in SEARCH_COLUMNS}} for item in items],
        columns = ["id", *SEARCH_COLUMNS],
    )
    df["description"] = df["description"].map(_html_to_text)
    return df.set_index("id")
