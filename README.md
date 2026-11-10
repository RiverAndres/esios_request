# esios_request

Easily obtain data published by REE in its public ESIOS API as a `pandas.DataFrame`.

This module was created mainly to obtain time series; there are features and endpoints that are not included in this version. They will be added as needed.

## Installation

```bash
pip install git+https://github.com/RiverAndres/esios_request.git
```

For development (tests, linters):

```bash
pip install -e ".[dev]"
```

## Quick start

```python
from datetime import date

from esios_request import esios_get_indicator, esios_get_archive

# The token can be passed as an argument or set in the ESIOS_API_KEY environment variable.
token = "YOUR_ESIOS_API_KEY"

# Indicator by alias (str) or numeric id (int)
df = esios_get_indicator(
    token,
    "p_pmd",  # same as 600
    params={
        "start_date": "2025/01/01T00:00:00Z",
        "end_date": "2025/01/01T01:00:00Z",
    },
    use_cache=True,
)

# With ESIOS_API_KEY set and dates as date objects (Madrid time)
df = esios_get_indicator(id="p_pmd", params={"start_date": date(2025, 1, 1), "end_date": date(2025, 1, 2)})

# Archive
df_uf = esios_get_archive(token, "uf")  # same as 110
```

## Functions

```python
esios_get_indicator(
    token: str | None = None,     # None -> ESIOS_API_KEY environment variable
    id: str | int,                # required: alias (e.g. "p_pmd") or numeric id (600)
    params: dict,                 # must include "start_date" and "end_date"
    headers: dict | None = None,  # Accept, Content-Type and User-Agent by default
    use_cache: bool = False,
) -> pd.DataFrame

esios_get_archive(
    token: str | None = None,
    id: str | int,                # required: alias (e.g. "uf") or numeric id (110)
    params: dict | None = None,
    headers: dict | None = None,
    use_cache: bool = False,
) -> pd.DataFrame
```

### Dates

`start_date` and `end_date` accept:

- `str`: the legacy format `"2025/01/01T00:00:00Z"` or any ISO 8601 string (`"2025-01-01"`, `"2025-01-01T00:00:00+01:00"`…).
- `datetime`, `date` or `pd.Timestamp`.

Dates **without a time zone** are interpreted in **Madrid time** (the same time zone the API uses to group days and months): `date(2025, 1, 1)` is 2024-12-31 23:00 UTC. To mean UTC, include the zone (`"...Z"`, `tzinfo=UTC`). A time that is ambiguous or does not exist because of a DST change raises `EsiosConfigError`. `end_date` is inclusive and must be equal to or later than `start_date`.

### Result

- `esios_get_indicator` handles ranges of any size: it splits them into non-overlapping blocks of up to 6 months (12 with `time_trunc="year"`) that start at the beginning of a month (or year) in **Madrid time**, and concatenates the result. This way, with `time_trunc` (`day`, `month`…) no period is split between two requests and aggregates are complete. The index is `datetime_utc` (`datetime64[ns, UTC]`), `value` is `float64` and `geo_id` is `Int64`.
- `time_agg`/`geo_agg` **without** `time_trunc` aggregate within each block: for long ranges you get one row per block, not a single row for the whole range.
- If an indicator has several geographies (e.g. `p_pmd`: Spain, Portugal, France…), there is **one row per instant and `geo_id`**, so the index may repeat. To request only some zones you can use the API's own filter, which downloads less data (not every indicator supports it; if it has no effect, filter afterwards with `df[df["geo_id"] == 3]`):

  ```python
  params = {"start_date": "...", "end_date": "...", "geo_ids[]": [3]}  # 3 = Spain
  ```

  Any other API parameter (`time_trunc`, `geo_agg`…) is forwarded unchanged in every block.
- If there is no data in the range, an empty `DataFrame` with the same columns is returned.
- The `params` and `headers` dicts you pass are **never modified**.
- `esios_get_archive` accepts both `download_json` response shapes: a flat list of rows or an object whose first key holds the rows.
- `use_cache=True` stores responses for 24 h with `requests-cache`, avoiding identical repeated requests.

### Errors and retries

Transient errors (429 and 500/502/503/504) and connection failures are **retried** up to 5 times with exponential backoff, honouring the `Retry-After` header. If they persist, or on other errors, one of these exceptions is raised (all available from `esios_request`):

| Exception | When | Also inherits from |
|---|---|---|
| `EsiosAuthError` | 401 / 403 (invalid token) | `EsiosHTTPError` |
| `EsiosNotFound` | 404 | `EsiosHTTPError` |
| `EsiosRateLimited` | 429 after retries are exhausted | `EsiosHTTPError` |
| `EsiosHTTPError` | any other HTTP error | `requests.HTTPError` |
| `EsiosSchemaError` | the API returns an unexpected format | `ValueError` |
| `EsiosConfigError` | missing token or dates, invalid dates | `ValueError` |

All of them inherit from `EsiosError`. Code that caught `requests.HTTPError` or `ValueError` (v1.1) keeps working.

### Logging

The library prints nothing; it logs the requested blocks and their timings to the `esios_request` logger:

```python
import logging
logging.basicConfig(level=logging.INFO)                     # one summary per call
logging.getLogger("esios_request").setLevel(logging.DEBUG)  # one line per block
```

The list of available aliases is in `esios_request/indicators.py`.

## Version

```python
import esios_request
esios_request.__version__
```
