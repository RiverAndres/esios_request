# esios_request — contexto para Claude

Librería Python (>=3.12) que hace GET a la API pública de REE (e·sios, `https://api.esios.ree.es`)
y devuelve **siempre un `pandas.DataFrame`** (requisito no negociable del autor).
Se instala por git: `pip install git+https://github.com/RiverAndres/esios_request.git`.

## Estructura
- `esios_request/__init__.py` — exporta `esios_get_indicator`, `esios_get_archive`.
- `esios_request/esios_request.py` — toda la lógica:
  - `esios_get_request(token, url, headers=None, params=None, session=None)` → copia headers (o `DEFAULT_HEADERS`),
    añade `x-api-key` y hace `session.get` (timeout (5,180)). No modifica nada de lo que recibe.
  - `esios_get_indicator(token, id, params, headers, use_cache)` → `/indicators/{id}`. Trocea
    `start_date`–`end_date` con `_block_ranges`: bloques **sin solapamiento** de 6 meses (`BLOCK_SIZE`; 12 con
    `time_trunc=year`) con fronteras en inicio de mes/año en hora de Madrid (`API_TZ`); cada bloque acaba 1 s antes
    de la frontera. Un único `pd.concat`, índice `datetime_utc` (tz UTC) y deduplica por `(datetime_utc, geo_id)`
    como red de seguridad. Sin datos → DataFrame vacío con `INDICATOR_COLUMNS`. Formato inesperado o faltan
    fechas → `ValueError`.
  - `esios_get_archive(token, id, params, headers, use_cache)` → `/archives/{id}/download_json`,
    DataFrame de una lista plana de filas o de la primera clave de un objeto (`ValueError` en otro caso).
- `esios_request/indicators.py` — alias legibles → id numérico (`p_pmd`=600, `uf`=110…).
  `common_indicators/common_archives` aceptan str (alias) o int.
- `esios_request/req_cache.py` — `requests_cache.CachedSession` global (sqlite en temp, 24 h,
  creado al importar). `get_session(use_cache)`.
- `main.py` — script local de prueba (ignorado en git).
- `env/` — **secretos** (`env/.env` con `ESIOS_API_KEY`, cargado por `env/__init__.py` con python-dotenv).
  Ignorado por git. **No leer ni imprimir el valor del token**; usar `from env import ESIOS_API_KEY`.

## Detalles de la API comprobados
- Formato de fechas que usa la librería: `"%Y/%m/%dT%H:%M:%SZ"` (la API también acepta ISO 8601).
- `end_date` es **inclusivo** (por eso cada bloque acaba 1 s antes de la frontera del siguiente).
- `time_trunc` agrega **solo lo que cae dentro de [start_date, end_date]**, en periodos de hora de Madrid.
  Comprobado 2026-11-10 (600, España, `day`+`average`): 01/07/2025 completo = 111,201; pedido hasta
  01/07 00:00Z = 123,322 (parcial, 2 h). Pedido **desde** 01/07 00:00Z devolvió 111,201 (día completo,
  etiquetado 30/06 22:00Z). Por eso las fronteras de bloque deben caer en inicio de mes de Madrid.
- `time_trunc=year` con un año completo (12 meses) en una sola petición funciona (200, <1 s).
- Un indicador puede devolver **varias filas por timestamp** (una por `geo_id`): p.ej. 600 devuelve
  Portugal, Francia, España, Alemania, Bélgica, Países Bajos. Granularidad actual 15 min.
- Filtro por geografía en la propia API: `params["geo_ids[]"] = [3]` (3 = España). Comprobado 2026-11-10
  con 600: devuelve solo ese geo. **No funciona en todos los indicadores** (según el autor): no asumir
  que filtra; la deduplicación por `(datetime_utc, geo_id)` tiene que seguir funcionando sin él.
  La librería reenvía todos los `params` en cada bloque.

## Documentación oficial de la API
- https://api.esios.ree.es/ — documentación de endpoints y parámetros.
- Resumen completo ya hecho (2026-11-10) en `.claude/api_docs.md`: mirar ahí primero.
- Consultar la web **solo cuando haga falta** y el resumen no baste; no por defecto.
- Columnas típicas de `values`: `value, datetime, datetime_utc, tz_time, geo_id, geo_name`.

## Bugs conocidos (verificados 2026-11-09; estado actualizado 2026-11-10)
1. ~~Deduplicar solo por índice descartaba geos~~ → resuelto en v1.1.0.
2. ~~Defaults mutables / `params` del usuario modificado~~ → resuelto en v1.1.0.
3. ~~`except:` desnudo~~ → resuelto en v1.1.0.
4. Sin reintentos/backoff ante 429/5xx; peticiones secuenciales (Fases 2–3). ~~`pd.concat` en el bucle~~ → resuelto en v1.1.0.
5. ~~`python-dateutil` no declarado~~ → resuelto en v1.0.4 (`python-dotenv` solo lo usa `env/` local).
6. ~~`__pycache__/` versionado y `.gitignore` de Next.js~~ → resuelto en v1.0.4.
7. ~~Con `time_trunc`, el periodo del corte entre bloques salía con un agregado parcial~~ → resuelto en v1.1.1.
8. ~~`download_json` con lista plana lanzaba `ValueError`~~ → resuelto en v1.1.1.

## Hoja de ruta
Plan a corto plazo por fases (v1.0.4 → v1.1.1 → v1.4.0) en `.claude/roadmap.md`. Consultarlo antes de
proponer cambios y marcar las casillas `[x]` al completar tareas.

## Tests (obligatorio)
- **Tras cualquier cambio de código, al terminar los cambios, ejecutar la suite completa** y no dar el
  trabajo por terminado hasta que pase:
  `.venv/Scripts/python.exe -m pytest`
- Informar al usuario del resultado (passed / xfailed / failed). Si algo falla, arreglarlo o decirlo claramente.
- Los tests usan `responses` y **nunca llaman a la API real** (no gastan cuota ni necesitan token).
- Bugs conocidos = tests `xfail(strict=True)`. Al arreglar uno, el test da XPASS → fallo: quitar el `xfail`.
- Todo cambio de comportamiento o bug nuevo debe venir con su test.
- Para probar contra la API real (solo si hace falta), usar rangos cortos (1 h) para no gastar cuota.

## Entorno
- Windows; venv en `.venv` → `.venv/Scripts/python.exe` (dependencias `dev` instaladas).
- Sin CI todavía.
- Usuario escribe en español; responder en español.
