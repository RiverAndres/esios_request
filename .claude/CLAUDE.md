# esios_request — context for Claude

Python library (>=3.12) that makes GET requests to REE's public API (e·sios, `https://api.esios.ree.es`)
and **always returns a `pandas.DataFrame`** (non-negotiable requirement from the author).
Installed via git: `pip install git+https://github.com/RiverAndres/esios_request.git`.

## Language
- **All project files are written in English**: docs (`.md`), code comments, docstrings, error and log
  messages, test names.
- The user writes in Spanish: **reply to the user in Spanish**.

## Structure
- `esios_request/__init__.py` — exports `esios_get_indicator`, `esios_get_archive`, the exceptions and
  `__version__`; adds a `NullHandler` to the `esios_request` logger.
- `esios_request/exceptions.py` — `EsiosError` → `EsiosConfigError`/`EsiosSchemaError` (also `ValueError`)
  and `EsiosHTTPError` (also `requests.HTTPError`) → `EsiosAuthError` (401/403), `EsiosNotFound` (404),
  `EsiosRateLimited` (429). The double inheritance keeps backward compatibility with v1.1.
- `esios_request/esios_request.py` — all the logic:
  - `esios_get_request(token, url, headers=None, params=None, session=None)` → copies headers (or `DEFAULT_HEADERS`),
    adds `x-api-key` and calls `session.get` (timeout (5,180)). Never modifies its inputs.
  - `_resolve_token`: explicit token or the `ESIOS_API_KEY` environment variable; none → `EsiosConfigError`.
  - `_to_utc`: dates as `str` (ISO 8601 or the legacy format)/`datetime`/`date`/`pd.Timestamp` → naive UTC.
    **No time zone = Madrid time** (`API_TZ`). Ambiguous/non-existent → `EsiosConfigError`.
  - `_raise_for_status`: maps HTTP status codes to the exceptions (the message never includes the token).
  - `esios_get_indicator(token=None, id, params, headers, use_cache)` → `/indicators/{id}`. Validates dates
    (`start <= end`), splits with `_block_ranges`: **non-overlapping** 6-month blocks (`BLOCK_SIZE`; 12 with
    `time_trunc=year`) whose boundaries fall on month/year starts in Madrid time; each block ends 1 s before
    the boundary. A single `pd.concat`, dedupes by `(datetime_utc, geo_id)` as a safety net.
    Types: index `datetime64[ns, UTC]`, `value` float64, `geo_id` Int64 (also in the empty DataFrame).
    Logging: INFO per call, DEBUG per block.
  - `esios_get_archive(token=None, id, params, headers, use_cache)` → `/archives/{id}/download_json`,
    DataFrame from a flat list of rows or from the first key of an object (`EsiosSchemaError` otherwise).
- `esios_request/indicators.py` — readable aliases → numeric id (`p_pmd`=600, `uf`=110…).
  `common_indicators/common_archives` accept str (alias) or int.
- `esios_request/req_cache.py` — `make_retry()` (5 retries, backoff, 429/5xx, `Retry-After`,
  `raise_on_status=False`) mounted with `mount_retries()` on every session. Global `CachedSession`
  (sqlite in temp, 24 h, created at import; Phase 4 will make it lazy). `get_session(use_cache)`.
- `main.py` — local test script (git-ignored).
- `env/` — **secrets** (`env/.env` with `ESIOS_API_KEY`, loaded by `env/__init__.py` with python-dotenv).
  Git-ignored. **Never read or print the token value**; use `from env import ESIOS_API_KEY`.

## Verified API details
- Date format the library **sends** to the API: `"%Y/%m/%dT%H:%M:%SZ"` in UTC (the API also accepts
  ISO 8601). Users may pass any format accepted by `_to_utc`.
- `end_date` is **inclusive** (that is why each block ends 1 s before the next block's boundary).
- `time_trunc` aggregates **only what falls inside [start_date, end_date]**, in Madrid-time periods.
  Verified 2026-11-10 (600, Spain, `day`+`average`): full 2025-07-01 = 111.201; requested up to
  07-01 00:00Z = 123.322 (partial, 2 h). Requested **from** 07-01 00:00Z returned 111.201 (full day,
  labelled 06-30 22:00Z). Hence block boundaries must fall on Madrid month starts.
- `time_trunc=year` with a full year (12 months) in a single request works (200, <1 s).
- Invalid token → **403** `{"Status":403,"message":"Forbidden"}` (verified 2026-11-10), not 401.
- `env/__init__.py` loads `env/.env` into `os.environ`: after `import env`, `token=None` works.
- Rate limit and 429/5xx codes are still neither documented nor observed; retries are a default policy.
- An indicator may return **several rows per timestamp** (one per `geo_id`): e.g. 600 returns
  Portugal, France, Spain, Germany, Belgium, Netherlands. Current granularity 15 min.
- Geography filter in the API itself: `params["geo_ids[]"] = [3]` (3 = Spain). Verified 2026-11-10
  with 600: returns only that geo. **Does not work for every indicator** (per the author): do not assume
  it filters; deduplication by `(datetime_utc, geo_id)` must keep working without it.
  The library forwards all `params` in every block.

## Official API documentation
- https://api.esios.ree.es/ — endpoint and parameter docs.
- Full summary already done (2026-11-10) in `.claude/api_docs.md`: look there first.
- Check the website **only when needed** and the summary is not enough; not by default.
- Typical `values` columns: `value, datetime, datetime_utc, tz_time, geo_id, geo_name`.

## Known bugs (verified 2026-11-09; status updated 2026-11-10)
1. ~~Deduplicating by index only dropped geos~~ → fixed in v1.1.0.
2. ~~Mutable defaults / user's `params` modified~~ → fixed in v1.1.0.
3. ~~Bare `except:`~~ → fixed in v1.1.0.
4. Sequential requests (Phase 3). ~~No retries/backoff on 429/5xx~~ → fixed in v1.2.0. ~~`pd.concat` inside the loop~~ → fixed in v1.1.0.
5. ~~`python-dateutil` not declared~~ → fixed in v1.0.4 (`python-dotenv` is only used by the local `env/`).
6. ~~Versioned `__pycache__/` and a Next.js `.gitignore`~~ → fixed in v1.0.4.
7. ~~With `time_trunc`, the period at a block boundary came back as a partial aggregate~~ → fixed in v1.1.1.
8. ~~`download_json` returning a flat list raised `ValueError`~~ → fixed in v1.1.1.

## Roadmap
Short-term phased plan (v1.0.4 → v1.4.0, with v1.1.1 in between) in `.claude/roadmap.md`. Check it before
proposing changes and tick the `[x]` boxes when tasks are completed.

## Tests (mandatory)
- **After any code change, once the changes are done, run the full suite** and do not consider the
  work finished until it passes:
  `.venv/Scripts/python.exe -m pytest`
- Report the result to the user (passed / xfailed / failed). If something fails, fix it or say so clearly.
- Tests use `responses` and **never call the real API** (no quota used, no token needed).
- Known bugs = `xfail(strict=True)` tests. When one is fixed the test XPASSes → failure: remove the `xfail`.
- Every behaviour change or new bug must come with its test.
- To test against the real API (only when needed), use short ranges (1 h) to save quota.

## Environment
- Windows; venv in `.venv` → `.venv/Scripts/python.exe` (`dev` dependencies installed).
- No CI yet.
