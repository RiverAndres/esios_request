# esios_request — context for Claude

Python library (>=3.12) that makes GET requests to REE's public API (e·sios, `https://api.esios.ree.es`)
and **always returns a `pandas.DataFrame`** (non-negotiable requirement from the author).
Installed via git: `pip install git+https://github.com/RiverAndres/esios_request.git`.

## Language
- **All project files are written in English**: docs (`.md`), code comments, docstrings, error and log
  messages, test names.
- The user writes in Spanish: **reply to the user in Spanish**.

## Structure
- `esios_request/__init__.py` — exports `EsiosClient`, `esios_get_indicator`, `esios_get_archive`, the
  exceptions, `indicator_catalogue`/`archive_catalogue`, `clear_cache` and `__version__`; adds a
  `NullHandler` to the `esios_request` logger.
- `esios_request/exceptions.py` — `EsiosError` → `EsiosConfigError`/`EsiosSchemaError` (also `ValueError`)
  and `EsiosHTTPError` (also `requests.HTTPError`) → `EsiosAuthError` (401/403), `EsiosNotFound` (404),
  `EsiosRateLimited` (429); `EsiosUnknownAlias` (`EsiosConfigError` + `KeyError`). The double inheritance
  keeps backward compatibility with v1.x.
- `esios_request/client.py` — `EsiosClient(token=None, *, use_cache, headers, max_workers=4, block_months=1,
  session, cache_dir, cache_recent_ttl=600)`: `indicator`, `indicators` (long / `wide=True` with
  (`indicator`, `geo_id`) columns), `indicator_info` (`values=false`), `search` (`/indicators?text=`),
  `archive`, `clear_cache`. `_run` downloads tasks with a `ThreadPoolExecutor` keeping task order
  (`max_workers=1` = sequential). Context manager; closes only sessions it created (never the shared
  cached one or a user session).
  - Cache (`use_cache=True` and no user `session`): `_block_tasks` builds `_BlockTask`s on the calendar
    grid; a closed block is requested **whole** and trimmed in `_fetch_block` (`keep`), unless the call has
    an aggregation parameter (`time_trunc`, `time_agg`, `geo_agg`, `geo_trunc`) or the block is still open
    (exact dates). Expiry per request: window ends before `_core._utcnow()` → `NEVER_EXPIRE`; otherwise
    `cache_recent_ttl` (whole seconds, `0` → `DO_NOT_CACHE`). `indicator_info`/`search` 24 h; `archive`
    `cache_recent_ttl`. A user `session` is used as-is (no expiry argument, exact dates).
- `esios_request/esios_request.py` — legacy `esios_get_indicator` / `esios_get_archive`: thin wrappers
  around `EsiosClient` (same signatures as v1.2); re-exports constants and `esios_get_request`.
- `esios_request/_core.py` — shared internals:
  - `esios_get_request(token, url, headers=None, params=None, session=None)` → copies headers (or `DEFAULT_HEADERS`),
    adds `x-api-key` and calls `session.get` (timeout (5,180)). Never modifies its inputs.
  - `_resolve_token`: explicit token or the `ESIOS_API_KEY` environment variable; none → `EsiosConfigError`.
  - `_to_utc`: dates as `str` (ISO 8601 or the legacy format)/`datetime`/`date`/`pd.Timestamp` → naive UTC.
    **No time zone = Madrid time** (`API_TZ`). Ambiguous/non-existent → `EsiosConfigError`.
  - `_raise_for_status`: maps HTTP status codes to the exceptions (the message never includes the token).
  - `_resolve_range`: required `start`/`end`, `start <= end`.
  - `_block_ranges(start, end, time_trunc, block_months=1, calendar=False)`: **non-overlapping** blocks whose
    boundaries fall on month starts in Madrid time (year starts with `time_trunc=year`, block length rounded
    up to whole years); each block ends 1 s before the boundary. `calendar=True` (used with the cache) puts
    the boundaries on a fixed calendar grid instead of counting from the start's month (`_block_bounds`).
  - `_utcnow()`: current naive UTC instant; tests monkeypatch it to decide which blocks are closed.
  - `_combine_blocks`: single `pd.concat`, dedupes by `(datetime_utc, geo_id)` as a safety net.
    Types: index `datetime64[ns, UTC]`, `value` float64, `geo_id` Int64 (also in the empty DataFrame).
  - `_parse_archive`: flat list of rows or first key of an object (`EsiosSchemaError` otherwise).
  - `_parse_indicator_info` / `_parse_search`: metadata → flat columns; HTML descriptions → plain text.
  - Logging: INFO per call, DEBUG per block.
- `esios_request/indicators.py` — catalogue: `INDICATORS`/`ARCHIVES` (frozen dataclasses: alias, id, unit,
  description), backward compatible `indicators`/`archives` dicts (alias → id), `common_indicators` /
  `common_archives` (alias, int or digit string; unknown → `EsiosUnknownAlias` with suggestions),
  `indicator_catalogue()` / `archive_catalogue()` DataFrames.
- `esios_request/req_cache.py` — `make_retry()` (5 retries, backoff, 429/5xx, `Retry-After`,
  `raise_on_status=False`) mounted with `mount_retries()` on every session. `EsiosSession` /
  `EsiosCachedSession` override `rebuild_auth` to drop `x-api-key` on a redirect to another host.
  `get_session(use_cache, cache_dir)`: without cache a new `EsiosSession`; with cache one **lazy** shared
  `EsiosCachedSession` per directory
  (sqlite `esios_cache.sqlite`, default expiry 24 h, `x-api-key` ignored and never stored).
  `resolve_cache_dir`: argument → `ESIOS_CACHE_DIR` → `platformdirs.user_cache_dir("esios_request")`.
  `clear_cache(cache_dir=None, expired_only=False)`. `_close_sessions()` is for the tests.
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
  4 parallel requests did not trigger any 429 (2026-11-10).
- Request time grows faster than block size (2026-11-10, one year of `p_pmd`, Spain only, 35 040 rows):
  sequential 6-month blocks 16.5 s, parallel 6-month 10.7 s, parallel 3-month **3.7 s**.
- Two years of `p_pmd` (2026-11-11, Spain only, 65 688 rows, identical results, 4 workers): 24 one-month
  blocks **7.9 s** (0.6–1.8 s each, all 200, no retries) vs 4 six-month blocks 13.1 s. Hence the default
  `block_months=1` since v1.4.0. A month of 600 for Spain is ~0.65 MB; unfiltered (6 geos) ~3.9 MB.
- **Large responses are redirected** (2026-11-11): above roughly 4.2 MB the API takes 8–11 s and answers
  **307** to a pre-signed temporary file in S3 (`s3.eu-west-1.amazonaws.com/ree.pro.newsioswp.doc.s3/temp/…`,
  valid 1 h), which `requests` follows. Blocks of 3.1 and 4.16 MB were served directly. The exact threshold
  (size, rows or time) is unknown. `requests` only strips `Authorization` on a cross-host redirect, so it
  forwarded `x-api-key` to S3 (confirmed with a mocked redirect). Fixed in v1.4.0: the library's sessions
  drop it; the S3 file downloads fine without the token (verified against the real API, 200, 4.24 MB).
  A user-provided `session` still forwards it.
- Repeating an identical request within about a minute came back in 0.26 s instead of several seconds
  (2026-11-11): the API seems to cache on its side, so do not compare first and repeated timings.
- `requests-cache` 1.3.1 rounds `expire_after` to whole seconds (0.5 → not cached); `responses` works with
  `CachedSession`.
- `values=false` metadata: `name, id, composited, disaggregated, operation, universe[{name,id}],
  magnitud[{name,id}], tiempo[{name,id}], nivel, geos, description (HTML)`; no `short_name`. Energy/power
  units are only given as magnitude ("Energía", "Potencia").
- `/indicators?text=` items: `id, name, short_name, description`; `meta.size`.
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
4. ~~Sequential requests~~ → fixed in v1.3.0. ~~No retries/backoff on 429/5xx~~ → fixed in v1.2.0. ~~`pd.concat` inside the loop~~ → fixed in v1.1.0.
5. ~~`python-dateutil` not declared~~ → fixed in v1.0.4 (`python-dotenv` is only used by the local `env/`).
6. ~~Versioned `__pycache__/` and a Next.js `.gitignore`~~ → fixed in v1.0.4.
7. ~~With `time_trunc`, the period at a block boundary came back as a partial aggregate~~ → fixed in v1.1.1.
8. ~~`download_json` returning a flat list raised `ValueError`~~ → fixed in v1.1.1.

## Roadmap
Short-term phased plan (v1.0.4 → v1.4.0, with v1.1.1 in between) in `.claude/roadmap.md`: all phases are
completed (v1.4.0, 2026-11-11); what remains is under "Beyond this horizon". Check it before proposing
changes and tick the `[x]` boxes when tasks are completed.

## Tests (mandatory)
- **After any code change, once the changes are done, run the full suite** and do not consider the
  work finished until it passes:
  `.venv/Scripts/python.exe -m pytest`
- Report the result to the user (passed / xfailed / failed). If something fails, fix it or say so clearly.
- Tests use `responses` and **never call the real API** (no quota used, no token needed). The autouse
  `isolated_cache` fixture points the cache to `tmp_path`, so they never touch the user's real cache.
- Known bugs = `xfail(strict=True)` tests. When one is fixed the test XPASSes → failure: remove the `xfail`.
- Every behaviour change or new bug must come with its test.
- To test against the real API (only when needed), use short ranges (1 h) to save quota.

## Environment
- Windows; venv in `.venv` → `.venv/Scripts/python.exe` (`dev` dependencies installed).
- No CI yet.
