"""
Legacy functional API (v1.x). Both functions are thin wrappers around ``EsiosClient``.

The constants and helpers below are re-exported for backward compatibility.
"""

import pandas as pd

from ._core import (  # noqa: F401  (re-exported for backward compatibility)
    API_TZ,
    BASE_URL,
    BLOCK_SIZE,
    DATE_FMT,
    DEFAULT_HEADERS,
    INDICATOR_COLUMNS,
    TOKEN_ENV_VAR,
    YEAR_BLOCK_SIZE,
    _block_ranges,
    esios_get_request,
)
from .client import EsiosClient
from .exceptions import EsiosConfigError


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
    so that no ``time_trunc`` period is split between two requests. Blocks are downloaded
    in parallel (see ``EsiosClient`` to configure it).

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
    params = dict(params or {})
    start = params.pop("start_date", None)
    end = params.pop("end_date", None)
    with EsiosClient(token, use_cache = use_cache, headers = headers) as client:
        return client.indicator(id, start, end, params = params)


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
    with EsiosClient(token, use_cache = use_cache, headers = headers) as client:
        return client.archive(id, params = params)
