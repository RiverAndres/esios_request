# Short-term roadmap — esios_request

> Fixed constraint: the library's public output is always a `pandas.DataFrame`.
> Starting point: v1.0.3 (November 2026). Bugs verified against the real API on 2026-11-09.

---

## Phase 0 — Repository hygiene · v1.0.4

Goal: leave the repo clean before touching any logic.

- [x] Replace the `.gitignore` (Next.js template) with a Python one (`__pycache__/`, `*.egg-info/`, `.venv/`, `env/`, `.pytest_cache/`, `*.sqlite`).
- [x] Remove the versioned `__pycache__/` from the index (`git rm -r --cached`).
- [x] Declare missing dependencies in `pyproject.toml`: `python-dateutil`. Add optional extras: `dev = [pytest, responses, ruff, mypy]`.
- [x] Add `__version__` to `esios_request/__init__.py`.
- [x] Update the README: `use_cache`, `id` accepts `str | int`, minimal usage example.
- [x] Test infrastructure: `tests/` with pytest + `responses` (never calls the real API), config in `pyproject.toml` (`xfail_strict = true`).
- [x] Tests for the current behaviour (aliases, URL, token, 6-month block splitting, no duplicates at the boundary, HTTP errors, archives).
- [x] Known bugs documented as `xfail(strict=True)` tests: when one is fixed the test XPASSes → fails, and the `xfail` must be removed.
- [x] Working rule in `CLAUDE.md`: after any code change, run the full suite before considering the work finished.

**Done when:** `git status` is clean after running, `pip install -e .[dev]` works in a fresh venv and `pytest` passes (18 passed, 4 xfailed).

---

## Phase 1 — Critical bug fixes · v1.1.0

Goal: correct returned data and no side effects.

- [x] **Lost geos:** dedupe by `(datetime_utc, geo_id)` instead of by index only. `p_pmd` currently returns only Portugal.
- [x] **Mutable defaults:** `headers=None` and `params=None` in the signatures; always work on copies. The token must not be stored in the `headers` default.
- [x] Do not modify the user's `params` (`params.update` → local dict per block).
- [x] Remove bare `except:`: catch only `KeyError`/`ValueError` for legitimate empty responses and raise a clear error otherwise.
- [x] Remove the dead `max_cache_entries` parameter and the `session=requests.Session()` evaluated at import time.
- [x] Build a list of DataFrames and do a single `pd.concat` at the end.

**Minimum tests (pytest + recorded responses, no API calls):**
- [x] Indicator with several geos per timestamp → none is lost.
- [x] Range spanning several 6-month blocks → no duplicates at the boundary (end_date is inclusive).
- [x] Calling twice in a row → user's `headers`/`params` and the defaults untouched.
- [x] Malformed response → clear error instead of an empty DataFrame.
- [x] Response with `values: []` → empty DataFrame with the expected columns.

**Done when:** tests pass and `esios_get_indicator(token, "p_pmd", ...)` returns 6 geos for 2025-01-01.
✅ Completed 2026-11-10: 39 tests pass; verified against the real API (1 h of `p_pmd` → 6 geos × 5 rows).
Note: format errors raise `ValueError` for now; in Phase 2 they become `EsiosSchemaError` (a `ValueError` subclass to keep compatibility).

---

## Phase 1.1 — Findings from the API documentation · v1.1.1

Goal: fix what the review of the official documentation (2026-11-10) uncovered.

- [x] Verify against the real API whether `time_trunc` splits periods at block boundaries → **confirmed** (2025-07-01: 123.3 instead of 111.2).
- [x] **Non-overlapping** blocks (each ends 1 s before the next) with boundaries on month starts in Madrid time.
- [x] With `time_trunc=year`, 12-month blocks aligned to January 1st in Madrid (verified: the API accepts a full year in one request).
- [x] `esios_get_archive` accepts the `download_json` response as a flat list of rows (format of the official example).
- [x] Declare `tzdata` (required by `zoneinfo` on Windows).

**Tests:**
- [x] Exact block boundaries (summer 22:00Z / winter 23:00Z), no gaps or overlaps on arbitrary ranges.
- [x] `time_trunc=day` + `average` simulator: the split result matches a single request (fails with the old splitting).
- [x] `time_trunc=year` → yearly blocks; `start == end` → one block.
- [x] Deduplication still works if the API repeated an instant.
- [x] `geo_agg`: rows with `geo_ids` (list) instead of `geo_id`.
- [x] `download_json` with a flat list / empty list / rows that are not objects.

✅ Completed 2026-11-10: 51 tests pass; verified against the real API (`p_pmd` Spain, `day`+`average`, 2025-01-01 to 2025-07-02 → 183 days, 07-01 = 111.201 as in a single request).

---

## Phase 2 — Network robustness · v1.2.0

Goal: a long download must not fail because of a one-off error.

- [x] Retries with backoff via `HTTPAdapter(max_retries=Retry(...))` for 429/500/502/503/504, honouring `Retry-After` (5 retries, GET only, also on the cached session).
- [x] Custom exceptions in `esios_request/exceptions.py`: `EsiosError`, `EsiosAuthError` (401/403), `EsiosNotFound` (404), `EsiosRateLimited` (429), `EsiosSchemaError`, plus `EsiosHTTPError` (other HTTP errors) and `EsiosConfigError` (invalid input). They inherit from `requests.HTTPError`/`ValueError` so v1.1 code keeps working.
- [x] `logging` with the `esios_request` logger (INFO per call, DEBUG per block with rows and timing; `NullHandler` by default; never the token).
- [x] Optional token: if not given, read the `ESIOS_API_KEY` environment variable.
- [x] Flexible dates: `str` (ISO 8601 and the current format), `datetime`, `date` and `pd.Timestamp`; validate `start <= end`; **no time zone = Madrid time** (documented in the README).
- [x] Normalised output types: `value: float64`, `geo_id: Int64`, index `datetime64[ns, UTC]` (also with pandas 3, which defaults to µs).

**Done when:** a test simulates a 503 followed by a 200 and the call succeeds; a 401 raises `EsiosAuthError`.
✅ Completed 2026-11-10: 95 tests pass (44 new in `tests/test_phase2.py`), ruff and mypy clean. Verified against the real API: token from the environment + naive dates → 6 geos × 5 rows with normalised types; fake token → 403 → `EsiosAuthError` without retries.

---

## Phase 3 — Client and performance · v1.3.0

Goal: a scalable base without breaking the current API.

- [ ] `EsiosClient` class with a reusable session, retries and token configured once; supports `with`.
  - `client.indicator(id, start, end, **params) -> pd.DataFrame`
  - `client.indicators([ids], start, end, wide=False) -> pd.DataFrame`
  - `client.archive(id, **params) -> pd.DataFrame`
  - `client.indicator_info(id) -> pd.DataFrame` (metadata with `values=false`: name, unit, geos, `step_type`…)
  - `client.search(text) -> pd.DataFrame` (`GET /indicators?text=`: id, name, short_name)
- [ ] `esios_get_indicator` / `esios_get_archive` remain as thin wrappers around the client (backward compatibility).
- [ ] Parallel block download with `ThreadPoolExecutor` (configurable `max_workers`, 4 by default) and configurable block size.
- [ ] Alias catalogue as an `Enum`/dataclass (id, unit, description) and a clear error if the alias does not exist.

**Done when:** downloading a year of `p_pmd` is clearly faster than in v1.0.3 and old code keeps working unchanged.

---

## Phase 4 — Smart cache · v1.4.0

Goal: do not repeat downloads and do not serve stale data.

- [ ] Cached session created lazily (not at import time).
- [ ] Configurable, persistent cache path (not in temp by default).
- [ ] Per-block expiry: blocks entirely in the past never expire; blocks including today or the future, 5–15 min.
- [ ] Function to clear the cache.

**Done when:** repeating a historical download makes no network requests and requesting the current day always returns fresh data.

---

## Beyond this horizon (to consider later)

- Local Parquet store with incremental download (the output is still a DataFrame).
- CI on GitHub Actions (ruff, mypy, pytest) and publishing to PyPI.
- Async client (`httpx`).
