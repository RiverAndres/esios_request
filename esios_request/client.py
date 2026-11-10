"""
``EsiosClient``: token, session, retries and download settings configured once.

Every public method returns a ``pandas.DataFrame``.
"""

import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Self

import pandas as pd
import requests
import requests_cache

from ._core import (
    BASE_URL,
    DATE_FMT,
    DEFAULT_BLOCK_MONTHS,
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    INFO_COLUMNS,
    _block_ranges,
    _combine_blocks,
    _json,
    _parse_archive,
    _parse_indicator_info,
    _parse_indicator_values,
    _parse_search,
    _raise_for_status,
    _resolve_range,
    _resolve_token,
    logger,
)
from .exceptions import EsiosConfigError
from .indicators import common_archives, common_indicators
from .req_cache import get_session

DEFAULT_MAX_WORKERS = 4


class EsiosClient:
    """
    Client for the e·sios API.

    Parameters
    -----
    - ``token``: e·sios API key. If None, the ``ESIOS_API_KEY`` environment variable is used.
    - ``use_cache``: store responses for 24 h with ``requests-cache``.
    - ``headers``: request headers (``Accept``, ``Content-Type`` and ``User-Agent`` by default).
    - ``max_workers``: number of blocks downloaded in parallel (``1`` = sequential).
    - ``block_months``: maximum length of each request block, in months (6 by default).
    - ``session``: an existing ``requests.Session`` to use as-is (it is not closed by the client).

    Use it as a context manager to release the HTTP connections::

        with EsiosClient() as client:
            df = client.indicator("p_pmd", "2025-01-01", "2025-02-01", geo_ids=[3])
    """

    def __init__(
        self,
        token:str | None = None,
        *,
        use_cache:bool = False,
        headers:dict | None = None,
        max_workers:int = DEFAULT_MAX_WORKERS,
        block_months:int = DEFAULT_BLOCK_MONTHS,
        session:requests.Session | requests_cache.CachedSession | None = None,
        ) -> None:
        if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
            raise EsiosConfigError(f"max_workers must be a positive integer; got {max_workers!r}.")
        if isinstance(block_months, bool) or not isinstance(block_months, int) or block_months < 1:
            raise EsiosConfigError(f"block_months must be a positive integer; got {block_months!r}.")

        self._token = _resolve_token(token)
        self.headers = dict(headers) if headers is not None else dict(DEFAULT_HEADERS)
        self.max_workers = max_workers
        self.block_months = block_months
        self.use_cache = use_cache
        # Only sessions created here (and not the shared cached one) are closed by ``close()``.
        self._owns_session = session is None and not use_cache
        self.session = session if session is not None else get_session(use_cache)

    def __repr__(self) -> str:  # never show the token
        return (
            f"EsiosClient(use_cache={self.use_cache}, max_workers={self.max_workers}, "
            f"block_months={self.block_months})"
        )

    # ----------------------------------------------------------------------- lifecycle

    def close(self) -> None:
        """Close the HTTP session if it was created by this client."""
        if self._owns_session:
            self.session.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # ----------------------------------------------------------------------- HTTP

    def _get(self, url:str, params:dict | None = None):
        """GET with the client's token/headers; maps HTTP errors and returns the parsed JSON."""
        request_headers = {**self.headers, "x-api-key": self._token}
        res = self.session.get(url, headers = request_headers, params = params, timeout = DEFAULT_TIMEOUT)
        _raise_for_status(res)
        return _json(res, url)

    def _run(self, tasks:list, func) -> list:
        """Run ``func(task)`` for every task, in parallel up to ``max_workers``. Keeps the task order."""
        if self.max_workers == 1 or len(tasks) <= 1:
            return [func(task) for task in tasks]
        with ThreadPoolExecutor(max_workers = min(self.max_workers, len(tasks))) as executor:
            futures = [executor.submit(func, task) for task in tasks]
            try:
                return [future.result() for future in futures]
            except BaseException:
                for future in futures:
                    future.cancel()
                raise

    # ----------------------------------------------------------------------- indicators

    @staticmethod
    def _api_params(geo_ids:Iterable[int] | None, params:dict | None, api_params:dict) -> dict:
        merged = {**(params or {}), **api_params}
        for key in ("start_date", "end_date"):
            if key in merged:
                raise EsiosConfigError(f"Pass the dates as start/end, not as {key!r} inside the parameters.")
        if geo_ids is not None:
            merged["geo_ids[]"] = list(geo_ids)
        return merged

    def _block_tasks(self, indicator:int, start:datetime, end:datetime, params:dict) -> list[tuple[int, dict]]:
        blocks = _block_ranges(start, end, params.get("time_trunc"), self.block_months)
        return [
            (indicator, {**params, "start_date": s.strftime(DATE_FMT), "end_date": e.strftime(DATE_FMT)})
            for s, e in blocks
        ]

    def _fetch_block(self, task:tuple[int, dict]) -> pd.DataFrame:
        indicator, params = task
        url = f"{BASE_URL}/indicators/{indicator}"
        t0 = time.perf_counter()
        frame = _parse_indicator_values(self._get(url, params), url)
        logger.debug(
            "Indicator %s block (%s -> %s): %d rows in %.2f s",
            indicator, params["start_date"], params["end_date"], len(frame), time.perf_counter() - t0,
        )
        return frame

    def indicator(
        self,
        id:str | int,
        start,
        end,
        *,
        geo_ids:Iterable[int] | None = None,
        params:dict | None = None,
        **api_params,
        ) -> pd.DataFrame:
        """
        Values of one indicator between ``start`` and ``end`` (both inclusive).

        - ``id``: alias (e.g. ``"p_pmd"``) or numeric id (e.g. ``600``).
        - ``start``/``end``: ``str`` (ISO 8601 or ``"%Y/%m/%dT%H:%M:%SZ"``), ``datetime``, ``date`` or
          ``pd.Timestamp``. Dates without time zone are interpreted in Europe/Madrid time.
        - ``geo_ids``: optional geography filter (sent as ``geo_ids[]``; not every indicator supports it).
        - ``params`` / ``**api_params``: any other API parameter (``time_trunc="day"``, ``time_agg="average"``…).

        Returns a DataFrame indexed by ``datetime_utc`` (``datetime64[ns, UTC]``), ``value`` float64 and
        ``geo_id`` Int64; one row per (``datetime_utc``, ``geo_id``).
        """
        indicator = common_indicators(id)
        start_utc, end_utc = _resolve_range(start, end)
        merged = self._api_params(geo_ids, params, api_params)
        tasks = self._block_tasks(indicator, start_utc, end_utc, merged)
        logger.info("Indicator %s: %s -> %s UTC in %d block(s)", indicator, start_utc, end_utc, len(tasks))
        return _combine_blocks(self._run(tasks, self._fetch_block))

    def indicators(
        self,
        ids:Iterable[str | int],
        start,
        end,
        wide:bool = False,
        *,
        geo_ids:Iterable[int] | None = None,
        params:dict | None = None,
        **api_params,
        ) -> pd.DataFrame:
        """
        Values of several indicators between ``start`` and ``end``, downloaded in parallel.

        - ``wide=False``: long format, like ``indicator()`` plus an ``indicator`` column (numeric id).
        - ``wide=True``: one column per (``indicator``, ``geo_id``) — a two-level column index —
          with ``value`` as cell values, indexed by ``datetime_utc``. Rows aggregated with ``geo_agg``
          (no ``geo_id``) get ``geo_id`` = ``<NA>``.

        The other arguments are the same as in ``indicator()`` and apply to every indicator.
        """
        if isinstance(ids, (str, int)):
            ids = [ids]
        indicators = list(dict.fromkeys(common_indicators(i) for i in ids))
        if not indicators:
            raise EsiosConfigError("ids must contain at least one indicator.")
        start_utc, end_utc = _resolve_range(start, end)
        merged = self._api_params(geo_ids, params, api_params)

        tasks = [task for i in indicators for task in self._block_tasks(i, start_utc, end_utc, merged)]
        logger.info(
            "Indicators %s: %s -> %s UTC in %d block(s)", indicators, start_utc, end_utc, len(tasks)
        )
        frames = self._run(tasks, self._fetch_block)

        per_indicator = []
        for indicator in indicators:
            df = _combine_blocks([f for (i, _), f in zip(tasks, frames, strict = True) if i == indicator])
            df.insert(0, "indicator", pd.Series(indicator, index = df.index, dtype = "Int64"))
            per_indicator.append(df)
        long = pd.concat(per_indicator)
        long.index.name = "datetime_utc"

        if not wide:
            return long
        return self._to_wide(long)

    @staticmethod
    def _to_wide(long:pd.DataFrame) -> pd.DataFrame:
        if long.empty:
            columns = pd.MultiIndex.from_arrays([[], []], names = ["indicator", "geo_id"])
            index = pd.DatetimeIndex([], tz = "UTC", name = "datetime_utc").as_unit("ns")
            return pd.DataFrame(index = index, columns = columns, dtype = "float64")
        geo_id =long["geo_id"] if "geo_id" in long.columns else pd.Series(pd.NA, index = long.index, dtype = "Int64")
        keys = pd.MultiIndex.from_arrays(
            [long.index, long["indicator"].to_numpy(), geo_id.to_numpy()],
            names = ["datetime_utc", "indicator", "geo_id"],
        )
        values = pd.Series(long["value"].to_numpy(), index = keys)
        wide = values.unstack(["indicator", "geo_id"]).sort_index()
        wide.index = pd.DatetimeIndex(wide.index, name = "datetime_utc").as_unit("ns")
        return wide.astype("float64")

    def indicator_info(self, id:str | int | Iterable[str | int]) -> pd.DataFrame:
        """
        Metadata of one or several indicators (no values), one row per indicator indexed by ``id``:
        name, short_name, unit, granularity, universe, geos, composited, disaggregated,
        values_updated_at and description (plain text).
        """
        ids = [id] if isinstance(id, (str, int)) else list(id)
        indicators = list(dict.fromkeys(common_indicators(i) for i in ids))

        def fetch(indicator:int) -> dict:
            url = f"{BASE_URL}/indicators/{indicator}"
            return _parse_indicator_info(self._get(url, {"values": "false"}), url)

        rows = self._run(indicators, fetch)
        return pd.DataFrame(rows, columns = ["id", *INFO_COLUMNS]).set_index("id")

    def search(self, text:str | None = None, *, params:dict | None = None, **api_params) -> pd.DataFrame:
        """
        Search indicators by name (``GET /indicators?text=``). Without ``text``, lists every indicator.
        Returns a DataFrame indexed by ``id`` with name, short_name and description (plain text).
        """
        merged = {**(params or {}), **api_params}
        if text:
            merged["text"] = text
        url = f"{BASE_URL}/indicators"
        return _parse_search(self._get(url, merged), url)

    # ----------------------------------------------------------------------- archives

    def archive(self, id:str | int, *, params:dict | None = None, **api_params) -> pd.DataFrame:
        """
        Values of an archive (``/archives/{id}/download_json``) as a DataFrame.
        ``params`` / ``**api_params`` are forwarded to the API (e.g. ``date="2025-01-01"``).
        """
        archive = common_archives(id)
        url = f"{BASE_URL}/archives/{archive}/download_json"
        merged = {**(params or {}), **api_params}
        logger.info("Archive %s: params=%s", archive, merged)
        return _parse_archive(self._get(url, merged or None), url)
