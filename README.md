# esios_request

Download data from REE's public e·sios API (`https://api.esios.ree.es`) as a `pandas.DataFrame`.

- Every public function returns a `pandas.DataFrame`.
- Date ranges of any length: they are split into monthly requests, downloaded in parallel and joined.
- Optional on-disk cache, so the same data is not downloaded twice.
- Readable aliases for common indicators (`"p_pmd"` instead of `600`).

The library focuses on time series (indicators) and JSON archives. Other endpoints of the API are not covered.

## Installation

Requires Python 3.12 or later.

```bash
pip install git+https://github.com/RiverAndres/esios_request.git
```

You need a personal e·sios token, which REE issues on request (<https://www.esios.ree.es/es/token>). Pass it to the client or, better, set it in the `ESIOS_API_KEY` environment variable.

## Quick start

```python
from esios_request import EsiosClient

# The token is read from the ESIOS_API_KEY environment variable (or pass EsiosClient("your-token")).
with EsiosClient(use_cache=True) as client:
    # One indicator, by alias or numeric id. Dates without a time zone are Madrid time.
    df = client.indicator("p_pmd", "2025-01-01", "2025-12-31T23:45", geo_ids=[3])

    # Daily averages
    daily = client.indicator(600, "2025-01-01", "2025-12-31", time_trunc="day", time_agg="average")

    # Several indicators: long format, or one column per (indicator, geo_id)
    long = client.indicators(["p_pmd", "e_pmd"], "2025-01-01", "2025-01-02")
    wide = client.indicators(["p_pmd", "e_pmd"], "2025-01-01", "2025-01-02", wide=True)

    # Metadata and search (no values)
    info = client.indicator_info(["p_pmd", "e_pmd"])
    found = client.search("precio marginal")

    # Archive
    uf = client.archive("uf")
```

`EsiosClient` is the recommended way to use the library. The functions of earlier versions (`esios_get_indicator`, `esios_get_archive`) still work; see [Legacy functions](#legacy-functions).

## EsiosClient

```python
EsiosClient(
    token: str | None = None,     # None -> ESIOS_API_KEY environment variable
    *,
    use_cache: bool = False,      # keep responses on disk (see "Cache")
    headers: dict | None = None,  # Accept, Content-Type and User-Agent by default
    max_workers: int = 4,         # requests made in parallel (1 = sequential)
    block_months: int = 1,        # maximum months per request
    session: requests.Session | None = None,  # use your own session as-is
    cache_dir: str | Path | None = None,      # None -> ESIOS_CACHE_DIR, else the user's cache directory
    cache_recent_ttl: float = 600,            # seconds a response that includes "now" is kept
)
```

| Method | Returns |
|---|---|
| `indicator(id, start, end, *, geo_ids=None, params=None, **api_params)` | Values of one indicator, indexed by `datetime_utc`; one row per instant and `geo_id` |
| `indicators(ids, start, end, wide=False, *, geo_ids=None, params=None, **api_params)` | Values of several indicators: long format with an `indicator` column, or with `wide=True` one column per (`indicator`, `geo_id`) |
| `indicator_info(id_or_ids)` | Metadata, one row per indicator indexed by `id`: `name`, `short_name`, `unit`, `granularity`, `universe`, `geos`, `composited`, `disaggregated`, `values_updated_at`, `description` |
| `search(text=None, *, params=None, **api_params)` | Indicators whose name matches `text` (all of them without `text`), indexed by `id`: `name`, `short_name`, `description` |
| `archive(id, *, params=None, **api_params)` | Rows of a JSON archive (`download_json`) |
| `clear_cache(*, expired_only=False)` | Nothing. Deletes the client's cached responses (see [Cache](#cache)) |
| `close()` | Nothing. Releases the HTTP connections; called automatically when the client is used with `with` |

- `id` is an alias (`"p_pmd"`) or a numeric id (`600` or `"600"`). See [Aliases](#aliases).
- `**api_params` are sent to the API as they are: `time_trunc="day"`, `time_agg="average"`, `geo_agg="sum"`, `locale="en"`… They can also be passed as a dict in `params`. Dates always go in `start` and `end`, never inside `params`.
- `geo_ids=[3]` asks the API for those geographies only (3 = Spain), which downloads less data. Not every indicator supports the filter: if it has no effect, filter afterwards with `df[df["geo_id"] == 3]`.
- The `params` and `headers` dicts you pass are never modified.
- The token is only sent to the API. The API answers large requests by redirecting to a temporary file on another host, and the library follows that redirect without the token. If you pass your own `session`, it is used as it is: `requests` will forward the `x-api-key` header on such redirects, and `use_cache` and the cache settings are ignored.

## Dates

`start` and `end` accept:

- `str`: any ISO 8601 string (`"2025-01-01"`, `"2025-01-01T00:00:00+01:00"`…) or the format `"2025/01/01T00:00:00Z"`.
- `datetime`, `date` or `pd.Timestamp`.

Dates **without a time zone are Madrid time**, the time zone the API uses to group days and months: `"2025-01-01"` is 2024-12-31 23:00 UTC. To mean UTC, include the zone (`"…Z"`, `tzinfo=UTC`).

`end` is inclusive and must be equal to or later than `start`. A local time that is ambiguous or does not exist because of a daylight-saving change raises `EsiosConfigError`.

## Result

`indicator()` returns a DataFrame with:

- Index `datetime_utc` (`datetime64[ns, UTC]`).
- Columns `value` (`float64`), `datetime`, `tz_time`, `geo_id` (`Int64`) and `geo_name`.

Things to keep in mind:

- An indicator may have several geographies (`p_pmd`: Spain, Portugal, France…). There is then **one row per instant and `geo_id`**, so the index repeats.
- With `geo_agg` the API returns a `geo_ids` column (a list) instead of `geo_id` and `geo_name`. With `wide=True` those rows get `geo_id` = `<NA>`.
- If there is no data in the range, the result is an empty DataFrame with the same columns and types.
- `archive()` accepts both shapes the API uses for `download_json`: a flat list of rows, or an object whose first key holds the rows.

## Blocks and parallel downloads

A range is split into non-overlapping requests ("blocks") of one month, which are downloaded in parallel with `max_workers` threads and joined. The result is the same as with a single request.

- Blocks start at the beginning of a month in Madrid time, so with `time_trunc` (`day`, `month`…) no period is split between two requests and every aggregate is complete. With `time_trunc="year"` blocks are whole years.
- One month is the default because the API serves small responses much faster than large ones. Raise `block_months` to make fewer, larger requests.
- `time_agg` or `geo_agg` **without** `time_trunc` aggregate within each block: for a long range you get one row per block, not one row for the whole range.

## Cache

`use_cache=True` keeps the responses in a sqlite file so the same data is not downloaded twice. It saves you time and saves the API traffic.

```python
from esios_request import EsiosClient, clear_cache

client = EsiosClient(use_cache=True)                       # default directory
client = EsiosClient(use_cache=True, cache_dir="./cache")  # your own directory

client.clear_cache()                   # delete everything cached in the client's directory
client.clear_cache(expired_only=True)  # delete only what has already expired
clear_cache("./cache")                 # the same without a client (default directory if omitted)
```

**Where it is stored.** In `cache_dir`; if not given, in the directory named by the `ESIOS_CACHE_DIR` environment variable; otherwise in the user's cache directory:

| System | Default directory |
|---|---|
| Windows | `%LOCALAPPDATA%\esios_request\Cache` |
| Linux | `~/.cache/esios_request` |
| macOS | `~/Library/Caches/esios_request` |

The cache persists between sessions and is created the first time it is used. The token is never written to it.

**How long a response is kept.**

| Request | Kept for |
|---|---|
| Indicator values whose time window ends before now | Forever |
| Indicator values whose time window ends now or in the future | `cache_recent_ttl` seconds (600 by default) |
| `indicator_info()` and `search()` | 24 hours |
| `archive()` | `cache_recent_ttl` seconds |

`cache_recent_ttl=0` means those responses are always downloaded. Fractions of a second are rounded up.

**Whole months.** With the cache, indicator values are downloaded in whole calendar months (Madrid time) and trimmed to the range you asked for, so different ranges share the same cached months:

```python
client.indicator("p_pmd", "2025-01-10", "2025-03-20")  # downloads January, February and March
client.indicator("p_pmd", "2025-02-01", "2025-02-15")  # no requests: February is already cached
```

Two cases keep your exact dates instead:

- The month that includes "now", because it is not complete yet.
- Calls that aggregate (`time_trunc`, `time_agg`, `geo_agg`, `geo_trunc`), because trimming would change the aggregates at the edges. They are cached too, but only reused when the same range is requested again.

**Limitations.**

- A closed window is never downloaded again. Values the API publishes or corrects afterwards are not picked up until you call `clear_cache()`. Keep this in mind for indicators that are published with a delay.
- The first request for a short range in a past month downloads the whole month.
- Responses that never expire accumulate in the file; there is no size limit.

## Aliases

```python
from esios_request import indicator_catalogue, archive_catalogue

indicator_catalogue()   # indexed by alias: id, unit, description
archive_catalogue()     # indexed by alias: id, description
```

| Aliases | What they are |
|---|---|
| `p_pmd`, `e_pmd` | Day-ahead market: marginal price and energy traded |
| `p_pmi1` … `p_pmi7`, `e_pmi1` … `e_pmi7` | Intraday sessions 1 to 7: marginal price and energy traded |
| `p_afrr_up`, `p_afrr_down`, `band_afrr_up`, `band_afrr_down` | aFRR reserve: price and allocated band |
| `p_afrr_act_up`, `p_afrr_act_down`, `e_afrr_act_up`, `e_afrr_act_down` | aFRR activation: price and activated energy |
| `uf`, `up`, `brp`, `entitled_participants` | Archives: physical units, programming units, balance responsible parties, entitled market participants |

An unknown alias raises `EsiosUnknownAlias` with suggestions, for example `Unknown indicator alias 'p_pmdd'. Did you mean: p_pmd?`. Numeric ids are always accepted, whether or not they have an alias; use `client.search()` to find them.

## Errors and retries

Transient errors (429 and 500, 502, 503, 504) and connection failures are retried up to 5 times with exponential backoff, honouring the `Retry-After` header. If they persist, or on any other error, one of these exceptions is raised. All of them can be imported from `esios_request` and inherit from `EsiosError`.

| Exception | When | Also inherits from |
|---|---|---|
| `EsiosAuthError` | 401 or 403 (an invalid token gives 403) | `EsiosHTTPError` |
| `EsiosNotFound` | 404 | `EsiosHTTPError` |
| `EsiosRateLimited` | 429 after the retries are exhausted | `EsiosHTTPError` |
| `EsiosHTTPError` | Any other HTTP error | `requests.HTTPError` |
| `EsiosSchemaError` | The API returns an unexpected format | `ValueError` |
| `EsiosUnknownAlias` | Alias not in the catalogue | `EsiosConfigError`, `KeyError` |
| `EsiosConfigError` | Missing token or dates, invalid dates or settings | `ValueError` |

Error messages never include the token.

## Logging

The library prints nothing. It logs the requests and their timings to the `esios_request` logger:

```python
import logging

logging.basicConfig(level=logging.INFO)                     # one summary per call
logging.getLogger("esios_request").setLevel(logging.DEBUG)  # one line per block
```

## Legacy functions

The functions of versions 1.0 to 1.2 keep their signatures. Each call creates an `EsiosClient` with the default settings and uses it once.

```python
esios_get_indicator(
    token: str | None = None,     # None -> ESIOS_API_KEY environment variable
    id: str | int,                # required: alias or numeric id
    params: dict,                 # must include "start_date" and "end_date"
    headers: dict | None = None,
    use_cache: bool = False,
) -> pd.DataFrame                 # same as EsiosClient.indicator()

esios_get_archive(
    token: str | None = None,
    id: str | int,                # required: alias or numeric id
    params: dict | None = None,
    headers: dict | None = None,
    use_cache: bool = False,
) -> pd.DataFrame                 # same as EsiosClient.archive()
```

```python
from esios_request import esios_get_archive, esios_get_indicator

df = esios_get_indicator(
    "your-token",
    "p_pmd",
    params={"start_date": "2025-01-01", "end_date": "2025-01-31", "geo_ids[]": [3]},
)
uf = esios_get_archive("your-token", "uf")
```

`start_date` and `end_date` follow the rules in [Dates](#dates). Every other key of `params` is sent to the API as it is.

## Upgrading to 1.4.0

Code written for earlier versions runs unchanged. Two defaults behave differently:

- **`block_months` is 1 instead of 6.** The data is the same, except with `time_agg` or `geo_agg` without `time_trunc`, where you now get one row per month instead of one per six months. Pass `block_months=6` to an `EsiosClient` for the old behaviour.
- **`use_cache=True` is persistent.** It used to keep everything for 24 hours in the system's temporary directory. See [Cache](#cache) for the new location and expiry.

## Development

```bash
pip install -e ".[dev]"
python -m pytest                                   # the tests never call the real API
python -m ruff check .
python -m mypy esios_request --ignore-missing-imports
```

```python
import esios_request
esios_request.__version__
```

## License

MIT. See [LICENSE](LICENSE).
