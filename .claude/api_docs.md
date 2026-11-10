# Notes on the official e·sios API documentation

> Source: https://api.esios.ree.es/ (91 pages read on 2026-11-10).
> The documentation is old (2015 examples, fake data, copied response headers, some corrupted
> descriptions). **The real API may differ**: what has been verified against the real API is in
> `CLAUDE.md` and takes precedence over this.

## What it does NOT document (must be found out empirically)
- Rate limit, error codes and error format (only 200 appears).
- Pagination (only `meta.size`) and maximum date range.
- Whether `end_date` is inclusive (we verified it: it is inclusive).
- Time zone of input parameters and the truncation alignment rule.
- Which indicators support geographic filters.
- `tz_time` is not in the docs, but the real API returns it.

## Authentication and headers
- `x-api-key: <token>` (some old pages use `Authorization: Token token=...`).
- `Accept: application/json; application/vnd.esios-api-v1+json` (widgets use `v2`), `Content-Type: application/json`.
- Token: https://www.esios.ree.es/es/token
- The docs publish example `x-api-key` values in plain text: do not use them.

## Indicators
- `GET /indicators` — list. Params: `locale`, `text` (search by name), `taxonomy_terms[]` / `taxonomy_ids[]`.
  Response: `{"indicators":[{name, short_name, id}], "meta":{"size":…}}`.
- `GET /indicators/{id}` — values. Params:
  - `start_date`, `end_date`, `datetime` (a single instant) — ISO 8601.
  - `time_trunc`: `five_minutes|ten_minutes|fifteen_minutes|hour|day|month|year`.
  - `time_agg`: `sum|average` (default `sum`; the examples use `avg`).
  - `geo_ids[]` (arrays as `geo_ids[]=1&geo_ids[]=2`).
  - `geo_agg`: `sum|average` (default `sum`); `geo_trunc` (only with `geo_agg`): `country`, `electric_system`,
    `electric_system_peninsula|canary|balearic|ceuta|melilla` (+ `_ccaa`), `autonomous_community`, `province`,
    `electric_subsystem`, `town`, `drainage_basin`.
  - `locale`: `es|en`.
  - `values=false` (not in the tables): metadata only, no `values`; includes `operation`, `universe`, `nivel`.
- Response: `indicator` → `name, short_name, id, composited, step_type, disaggregated, magnitud, tiempo, geos[{geo_id,geo_name}], values_updated_at, values_sum, values`.
  - Each value: `value, datetime (local offset), datetime_utc (Z), geo_id, geo_name` (+ `tz_time` in the real API).
  - **With `geo_agg`**: each row carries `geo_ids` (list) instead of `geo_id`/`geo_name` → one row per instant.
  - **With `time_trunc`**: one row per period; periods are aligned to peninsular local time
    (e.g. day = 22:00Z in summer). The docs say the first period starts at `start_date`; **in the real API**
    (2026-11-10) the period is labelled at its natural start and the **last** period comes back partial if
    `end_date` cuts it (see `CLAUDE.md`).
  - Without `time_trunc` but with `geo_agg`/`time_agg`: may return a single row for the whole range.

## Archives
- `GET /archives` — list. Params: `date`, or `start_date`+`end_date`+`date_type` (`datos|publicacion`),
  `taxonomy_terms[]`, `vocabularies[]`, `locale`. Each archive: `id, name, horizon, archive_type, download{url}, date, date_times, publication_date, taxonomy_terms, vocabularies`.
- `GET /archives/{id}` — metadata (`description`, `updated_at`, `json_download`…), not values.
- `GET /archives/{id}/download` — file (pdf, etc.). Params: `date`, `start_date`, `end_date`, `date_type`.
- `GET /archives/{id}/download_json` — values as JSON. **The docs example is a flat array**
  (`[{"Indicadores":"Precio","31/03/2014":"0,119941",…}]`, dd/mm/yyyy dates, comma decimals),
  not an object with one key.
- `GET /archives_json` — list of JSON-type archives (`taxonomy_terms[]`).
- `GET /calculator-data/{id}?start_date&end_date` — `{"data":{"archive_values":[{datetime, json_data:[…]}]}}`.

## Other endpoints (outside the library's current scope)
- `GET /offer_indicators/{id}` — `start_date|end_date|datetime`; values with `orden, price, offer, assignation, offer_sum, assignation_sum, datetime, datetime_utc`.
- `GET /auctions?year=YYYY` — `event_date, data_date, event_type, geo_id, download_links`.
- `GET /search?query=` (contents + indicators), `GET /contents?query=`.
- Widgets v2 (`/widgets`, `/widgets/{id|slug}`, `/cached_widgets/{id}`); widgets v1 disabled.
- CMS contents: `/es/{news|maps|documentations|glossaries|static_pages|umms}[/{slug}]`, `/contents/{id}`
  (params `taxonomy_*`, `vocabulary_*`, `order`, `sticky`).
