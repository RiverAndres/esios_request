import logging
import os
import time
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
from .indicators import common_archives, common_indicators
from .req_cache import get_session

logger = logging.getLogger("esios_request")

BASE_URL = "https://api.esios.ree.es"
DATE_FMT = "%Y/%m/%dT%H:%M:%SZ"
TOKEN_ENV_VAR = "ESIOS_API_KEY"
BLOCK_SIZE = relativedelta(months = 6)
# With ``time_trunc=year`` a 6-month block would split the year, so 12-month blocks are used
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


# --------------------------------------------------------------------------- helpers


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

    response = session.get(url = url, headers = request_headers, params = params, timeout = (5, 180))
    return response


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


def _next_block_boundary(start:datetime, yearly:bool) -> datetime:
    """
    Next block boundary after ``start`` (naive UTC): the Madrid-time month start ``BLOCK_SIZE``
    after ``start``'s month (or the next year start if ``yearly``). Returns naive UTC.
    """
    local = start.replace(tzinfo = UTC).astimezone(API_TZ)
    if yearly:
        floor, step = datetime(local.year, 1, 1, tzinfo = API_TZ), YEAR_BLOCK_SIZE
    else:
        floor, step = datetime(local.year, local.month, 1, tzinfo = API_TZ), BLOCK_SIZE
    return (floor + step).astimezone(UTC).replace(tzinfo = None)


def _block_ranges(start:datetime, end:datetime, time_trunc:str | None = None) -> list[tuple[datetime, datetime]]:
    """
    Split ``[start, end]`` (both inclusive, naive UTC) into **non-overlapping** blocks whose
    boundaries fall on month starts (year starts with ``time_trunc="year"``) in Madrid time.

    This way no ``time_trunc`` period (day, month, year…) is split between two blocks: if it were,
    the API would return a partial aggregate in each block.
    Each block ends 1 s before the boundary because ``end_date`` is inclusive.
    """
    yearly = time_trunc == "year"
    blocks = []
    block_start = start
    while block_start <= end:
        boundary = _next_block_boundary(block_start, yearly)
        blocks.append((block_start, min(boundary - timedelta(seconds = 1), end)))
        block_start = boundary
    return blocks


def esios_get_indicator(
    token:str | None = None,
    id:str | int | None = None,
    params:dict | None = None,
    headers:dict | None = None,
    use_cache: bool = False,
    ) -> pd.DataFrame:
    """
    Get request to an e·sios indicator by specifying the ``id`` (alias ``str`` or ``int``).
    The function can handle time intervals of any size: it splits them into non-overlapping
    blocks aligned to Europe/Madrid month starts (year starts with ``time_trunc="year"``),
    so that no ``time_trunc`` period is split between two requests.

    Parameters
    -----
    - ``token``:str | None --> e·sios API key. If None, the environment variable ``ESIOS_API_KEY`` is used.
    - ``id``:str | int --> Alias (e.g. "p_pmd") or numeric id (e.g. 600).
    - ``params``: dict --> Must contain at least ``start_date`` and ``end_date``. Dates may be ``str``
      (ISO 8601 or "%Y/%m/%dT%H:%M:%SZ"), ``datetime``, ``date`` or ``pd.Timestamp``; dates without
      time zone are interpreted in Europe/Madrid time. ``end_date`` is inclusive. It is not modified.
    - ``headers``: dict --> By default contains "Accept", "Content-Type", & "User-Agent". It is not modified.
    - ``use_cache``: bool --> By default "False". Uses the module requests_cache to store the request and avoid doing the same GET request.

    Returns
    -----
    ``pd.DataFrame`` containing the values of the id specified, indexed by ``datetime_utc``
    (``datetime64[ns, UTC]``), with ``value`` as float64 and ``geo_id`` as Int64.
    When the indicator has several geographies there is one row per (``datetime_utc``, ``geo_id``).

    Raises
    -----
    ``EsiosConfigError`` (missing token/dates, invalid dates), ``EsiosAuthError`` (401/403),
    ``EsiosNotFound`` (404), ``EsiosRateLimited`` (429), ``EsiosHTTPError`` (other HTTP errors),
    ``EsiosSchemaError`` (unexpected response). Transient errors (429/5xx) are retried first.
    """

    if id is None:
        raise EsiosConfigError("Missing indicator id (alias or number).")
    token = _resolve_token(token)
    params = dict(params or {})
    missing = [key for key in ("start_date", "end_date") if not params.get(key)]
    if missing:
        raise EsiosConfigError(f"Missing required parameters: {', '.join(missing)}.")

    start_date = _to_utc(params["start_date"], "start_date")
    end_date = _to_utc(params["end_date"], "end_date")
    if start_date > end_date:
        raise EsiosConfigError(
            f"start_date ({start_date:%Y-%m-%d %H:%M:%S} UTC) is later than end_date ({end_date:%Y-%m-%d %H:%M:%S} UTC)."
        )

    session = get_session(use_cache)
    indicator = common_indicators(id)
    endpoint = f"{BASE_URL}/indicators/{indicator}"
    blocks = _block_ranges(start_date, end_date, params.get("time_trunc"))
    logger.info("Indicator %s: %s -> %s UTC in %d block(s)", indicator, start_date, end_date, len(blocks))

    frames: list[pd.DataFrame] = []
    for n, (block_start, block_end) in enumerate(blocks, start = 1):
        block_params = {
            **params,
            "start_date": block_start.strftime(DATE_FMT),
            "end_date": block_end.strftime(DATE_FMT),
        }
        t0 = time.perf_counter()
        res = esios_get_request(session = session, token = token, url = endpoint, headers = headers, params = block_params)
        _raise_for_status(res)
        frame = _parse_indicator_values(_json(res, endpoint), endpoint)
        logger.debug(
            "Indicator %s block %d/%d (%s -> %s): %d rows in %.2f s",
            indicator, n, len(blocks), block_params["start_date"], block_params["end_date"],
            len(frame), time.perf_counter() - t0,
        )
        frames.append(frame)

    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return _empty_indicator_frame()

    df = pd.concat(frames)

    # Blocks do not overlap, but dedupe anyway as a safety net (in case the API returned an
    # instant outside the requested range). By (instant, geo) so no geography is lost.
    keys = df.index.to_frame(index = False)
    if "geo_id" in df.columns:
        keys["geo_id"] = df["geo_id"].to_numpy()
    df = df[~keys.duplicated(keep = "first").to_numpy()]

    return df


# --------------------------------------------------------------------------- archives


def esios_get_archive(
    token:str | None = None,
    id:str | int | None = None,
    params:dict | None = None,
    headers:dict | None = None,
    use_cache: bool = False,
    ) -> pd.DataFrame:
    """
    Get request to an e·sios archive by specifying the ``id`` (alias ``str`` or ``int``).

    Parameters
    -----
    - ``token``:str | None --> e·sios API key. If None, the environment variable ``ESIOS_API_KEY`` is used.
    - ``id``:str | int --> Alias (e.g. "uf") or numeric id (e.g. 110).
    - ``params``: dict --> Optional query parameters. It is not modified.
    - ``headers``: dict --> By default contains "Accept", "Content-Type", & "User-Agent". It is not modified.
    - ``use_cache``: bool --> By default "False".

    Returns
    -----
    ``pd.DataFrame`` built from the returned JSON: a flat list of rows, or the first key of an object.
    """

    if id is None:
        raise EsiosConfigError("Missing archive id (alias or number).")
    token = _resolve_token(token)
    session = get_session(use_cache)
    archive = common_archives(id)
    endpoint = f"{BASE_URL}/archives/{archive}/download_json"

    logger.info("Archive %s: params=%s", archive, params)
    res = esios_get_request(session = session, token = token, url = endpoint, headers = headers, params = params)
    _raise_for_status(res)
    payload = _json(res, endpoint)

    # The API may return a flat list of rows or an object whose first key holds the rows.
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and payload:
        rows = next(iter(payload.values()))
    else:
        raise EsiosSchemaError(f"Unexpected response from {endpoint}: expected a list or a non-empty JSON object.")

    if isinstance(rows, list) and not all(isinstance(row, dict) for row in rows):
        raise EsiosSchemaError(f"Unexpected response from {endpoint}: rows are not JSON objects.")

    return pd.DataFrame(rows)
