# Notas de la documentación oficial de la API e·sios

> Fuente: https://api.esios.ree.es/ (91 páginas leídas el 2026-11-10).
> La documentación es antigua (ejemplos de 2015, datos ficticios, cabeceras de respuesta copiadas,
> algunas descripciones corruptas). **La API real puede diferir**: lo verificado contra la API real
> está en `CLAUDE.md` y prevalece sobre esto.

## Qué NO documenta (hay que averiguarlo empíricamente)
- Rate limit, códigos de error y formato de errores (solo aparece 200).
- Paginación (solo `meta.size`) y rango máximo de fechas.
- Inclusividad de `end_date` (nosotros lo verificamos: es inclusivo).
- Zona horaria de los parámetros de entrada y regla de alineación del truncado.
- Qué indicadores admiten filtros geográficos.
- `tz_time` no aparece en la doc, pero la API real lo devuelve.

## Autenticación y cabeceras
- `x-api-key: <token>` (algunas páginas antiguas usan `Authorization: Token token=...`).
- `Accept: application/json; application/vnd.esios-api-v1+json` (los widgets usan `v2`), `Content-Type: application/json`.
- Token: https://www.esios.ree.es/es/token
- La doc publica valores de `x-api-key` de ejemplo en claro: no usarlos.

## Indicadores
- `GET /indicators` — lista. Params: `locale`, `text` (búsqueda por nombre), `taxonomy_terms[]` / `taxonomy_ids[]`.
  Respuesta: `{"indicators":[{name, short_name, id}], "meta":{"size":…}}`.
- `GET /indicators/{id}` — valores. Params:
  - `start_date`, `end_date`, `datetime` (instante concreto) — ISO 8601.
  - `time_trunc`: `five_minutes|ten_minutes|fifteen_minutes|hour|day|month|year`.
  - `time_agg`: `sum|average` (def. `sum`; los ejemplos usan `avg`).
  - `geo_ids[]` (arrays como `geo_ids[]=1&geo_ids[]=2`).
  - `geo_agg`: `sum|average` (def. `sum`); `geo_trunc` (solo con `geo_agg`): `country`, `electric_system`,
    `electric_system_peninsula|canary|balearic|ceuta|melilla` (+ `_ccaa`), `autonomous_community`, `province`,
    `electric_subsystem`, `town`, `drainage_basin`.
  - `locale`: `es|en`.
  - `values=false` (no está en las tablas): solo metadatos, sin `values`; incluye `operation`, `universe`, `nivel`.
- Respuesta: `indicator` → `name, short_name, id, composited, step_type, disaggregated, magnitud, tiempo, geos[{geo_id,geo_name}], values_updated_at, values_sum, values`.
  - Cada valor: `value, datetime (offset local), datetime_utc (Z), geo_id, geo_name` (+ `tz_time` en la API real).
  - **Con `geo_agg`**: cada fila trae `geo_ids` (lista) en vez de `geo_id`/`geo_name` → una fila por instante.
  - **Con `time_trunc`**: una fila por periodo; los periodos se alinean a hora local peninsular
    (p.ej. día = 22:00Z en verano). La doc dice que el primer periodo empieza en `start_date`; **en la API real**
    (2026-11-10) el periodo se etiqueta en su inicio natural y el **último** periodo sale parcial si `end_date`
    lo corta (ver `CLAUDE.md`).
  - Sin `time_trunc` pero con `geo_agg`/`time_agg`: puede devolver una única fila para todo el rango.

## Archivos
- `GET /archives` — lista. Params: `date`, o `start_date`+`end_date`+`date_type` (`datos|publicacion`),
  `taxonomy_terms[]`, `vocabularies[]`, `locale`. Cada archivo: `id, name, horizon, archive_type, download{url}, date, date_times, publication_date, taxonomy_terms, vocabularies`.
- `GET /archives/{id}` — metadatos (`description`, `updated_at`, `json_download`…), no valores.
- `GET /archives/{id}/download` — fichero (pdf, etc.). Params: `date`, `start_date`, `end_date`, `date_type`.
- `GET /archives/{id}/download_json` — valores en JSON. **El ejemplo de la doc es un array plano**
  (`[{"Indicadores":"Precio","31/03/2014":"0,119941",…}]`, fechas dd/mm/yyyy, decimales con coma),
  no un objeto con una clave.
- `GET /archives_json` — lista de archivos de tipo JSON (`taxonomy_terms[]`).
- `GET /calculator-data/{id}?start_date&end_date` — `{"data":{"archive_values":[{datetime, json_data:[…]}]}}`.

## Otros endpoints (fuera del alcance actual de la librería)
- `GET /offer_indicators/{id}` — `start_date|end_date|datetime`; valores con `orden, price, offer, assignation, offer_sum, assignation_sum, datetime, datetime_utc`.
- `GET /auctions?year=YYYY` — `event_date, data_date, event_type, geo_id, download_links`.
- `GET /search?query=` (contenidos + indicadores), `GET /contents?query=`.
- Widgets v2 (`/widgets`, `/widgets/{id|slug}`, `/cached_widgets/{id}`); widgets v1 deshabilitados.
- Contenidos CMS: `/es/{news|maps|documentations|glossaries|static_pages|umms}[/{slug}]`, `/contents/{id}`
  (params `taxonomy_*`, `vocabulary_*`, `order`, `sticky`).
