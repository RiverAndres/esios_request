# Roadmap a corto plazo — esios_request

> Restricción fija: la salida pública de la librería es siempre un `pandas.DataFrame`.
> Estado de partida: v1.0.3 (noviembre 2026). Bugs verificados contra la API real el 2026-11-09.

---

## Fase 0 — Higiene del repositorio · v1.0.4

Objetivo: dejar el repo limpio antes de tocar lógica.

- [x] Sustituir el `.gitignore` (plantilla Next.js) por uno de Python (`__pycache__/`, `*.egg-info/`, `.venv/`, `env/`, `.pytest_cache/`, `*.sqlite`).
- [x] Quitar del índice los `__pycache__/` versionados (`git rm -r --cached`).
- [x] Declarar dependencias que faltan en `pyproject.toml`: `python-dateutil`. Añadir extras opcionales: `dev = [pytest, responses, ruff, mypy]`.
- [x] Añadir `__version__` en `esios_request/__init__.py`.
- [x] Actualizar el README: `use_cache`, `id` acepta `str | int`, ejemplo mínimo de uso.
- [x] Infraestructura de tests: `tests/` con pytest + `responses` (nunca llama a la API real), config en `pyproject.toml` (`xfail_strict = true`).
- [x] Tests del comportamiento actual (alias, URL, token, troceo en bloques de 6 meses, borde sin duplicados, errores HTTP, archivos).
- [x] Bugs conocidos documentados como tests `xfail(strict=True)`: al arreglar uno, el test pasa a XPASS → falla, y hay que quitar el `xfail`.
- [x] Regla de trabajo en `CLAUDE.md`: tras cualquier cambio de código, ejecutar la suite completa antes de dar el trabajo por terminado.

**Hecho cuando:** `git status` limpio tras ejecutar, `pip install -e .[dev]` funciona en un venv nuevo y `pytest` pasa (18 passed, 4 xfailed).

---

## Fase 1 — Corrección de bugs críticos · v1.1.0

Objetivo: que los datos devueltos sean correctos y la función no tenga efectos secundarios.

- [x] **Pérdida de geos:** deduplicar por `(datetime_utc, geo_id)` en lugar de solo por índice. Hoy `p_pmd` devuelve únicamente Portugal.
- [x] **Defaults mutables:** `headers=None` y `params=None` en las firmas; trabajar siempre sobre copias. El token no debe quedar guardado en el default de `headers`.
- [x] No modificar el `params` que pasa el usuario (`params.update` → diccionario local por bloque).
- [x] Eliminar `except:` desnudos: capturar solo `KeyError`/`ValueError` para respuestas vacías legítimas y lanzar un error claro en el resto.
- [x] Eliminar el parámetro muerto `max_cache_entries` y el `session=requests.Session()` evaluado al importar.
- [x] Construir la lista de DataFrames y hacer un único `pd.concat` al final.

**Tests mínimos (pytest + respuestas grabadas, sin llamar a la API):**
- [x] Indicador con varios geos por timestamp → no se pierde ninguno.
- [x] Rango que cruza varios bloques de 6 meses → sin duplicados en el borde (end_date es inclusivo).
- [x] Llamar dos veces seguidas → `headers`/`params` del usuario y los defaults intactos.
- [x] Respuesta mal formada → error claro en vez de DataFrame vacío.
- [x] Respuesta con `values: []` → DataFrame vacío con las columnas esperadas.

**Hecho cuando:** los tests pasan y `esios_get_indicator(token, "p_pmd", ...)` devuelve 6 geos para 2025-01-01.
✅ Completada 2026-11-10: 39 tests pasan; comprobado contra la API real (1 h de `p_pmd` → 6 geos × 5 filas).
Nota: los errores de formato lanzan `ValueError` de momento; en la Fase 2 pasarán a `EsiosSchemaError` (subclase de `ValueError` para no romper compatibilidad).

---

## Fase 1.1 — Hallazgos de la documentación de la API · v1.1.1

Objetivo: corregir lo que la revisión de la documentación oficial (2026-11-10) destapó.

- [x] Verificar contra la API real si `time_trunc` parte periodos en las fronteras de bloque → **confirmado** (01/07/2025: 123,3 en vez de 111,2).
- [x] Bloques **sin solapamiento** (cada uno acaba 1 s antes del siguiente) con fronteras en inicio de mes en hora de Madrid.
- [x] Con `time_trunc=year`, bloques de 12 meses alineados al 1 de enero de Madrid (verificado: la API acepta un año en una petición).
- [x] `esios_get_archive` acepta la respuesta de `download_json` como lista plana de filas (formato del ejemplo oficial).
- [x] Declarar `tzdata` (necesario para `zoneinfo` en Windows).

**Tests:**
- [x] Fronteras de bloque exactas (verano 22:00Z / invierno 23:00Z), sin huecos ni solapes en rangos arbitrarios.
- [x] Simulador de `time_trunc=day` + `average`: el resultado troceado coincide con el de una sola petición (falla con el troceo antiguo).
- [x] `time_trunc=year` → bloques anuales; `start == end` → un bloque.
- [x] La deduplicación sigue funcionando si la API repitiera un instante.
- [x] `geo_agg`: filas con `geo_ids` (lista) en vez de `geo_id`.
- [x] `download_json` con lista plana / lista vacía / filas que no son objetos.

✅ Completada 2026-11-10: 51 tests pasan; comprobado contra la API real (`p_pmd` España, `day`+`average`, 01/01–02/07/2025 → 183 días, 01/07 = 111,201 como en una petición única).

---

## Fase 2 — Robustez de red · v1.2.0

Objetivo: que una descarga larga no falle por un error puntual.

- [ ] Reintentos con backoff mediante `HTTPAdapter(max_retries=Retry(...))` para 429/500/502/503/504, respetando `Retry-After`.
- [ ] Excepciones propias en `esios_request/exceptions.py`: `EsiosError`, `EsiosAuthError` (401/403), `EsiosNotFound` (404), `EsiosRateLimited` (429), `EsiosSchemaError`.
- [ ] `logging` con logger `esios_request` (bloque pedido, reintentos, tiempos) en lugar de `print`.
- [ ] Token opcional: si no se pasa, leer la variable de entorno `ESIOS_API_KEY`.
- [ ] Fechas flexibles: aceptar `str` (ISO 8601 y el formato actual), `datetime`, `date` y `pd.Timestamp`; validar `start < end`; documentar cómo se tratan las fechas sin zona horaria.
- [ ] Normalizar tipos de salida: `value: float64`, `geo_id: Int64`, índice `datetime64[ns, UTC]`.

**Hecho cuando:** un test simula un 503 seguido de 200 y la llamada termina bien; un 401 lanza `EsiosAuthError`.

---

## Fase 3 — Cliente y rendimiento · v1.3.0

Objetivo: base escalable sin romper la API actual.

- [ ] Clase `EsiosClient` con sesión reutilizable, reintentos y token configurados una sola vez; soporta `with`.
  - `client.indicator(id, start, end, **params) -> pd.DataFrame`
  - `client.indicators([ids], start, end, wide=False) -> pd.DataFrame`
  - `client.archive(id, **params) -> pd.DataFrame`
  - `client.indicator_info(id) -> pd.DataFrame` (metadatos con `values=false`: nombre, unidad, geos, `step_type`…)
  - `client.search(text) -> pd.DataFrame` (`GET /indicators?text=`: id, name, short_name)
- [ ] `esios_get_indicator` / `esios_get_archive` se mantienen como envoltorios finos del cliente (compatibilidad hacia atrás).
- [ ] Descarga de bloques en paralelo con `ThreadPoolExecutor` (`max_workers` configurable, 4 por defecto) y tamaño de bloque configurable.
- [ ] Catálogo de alias como `Enum`/dataclass (id, unidad, descripción) y error claro si el alias no existe.

**Hecho cuando:** descargar un año de `p_pmd` es claramente más rápido que en v1.0.3 y el código antiguo sigue funcionando sin cambios.

---

## Fase 4 — Caché inteligente · v1.4.0

Objetivo: no repetir descargas y no servir datos obsoletos.

- [ ] Sesión con caché creada de forma perezosa (no al importar).
- [ ] Ruta de caché configurable y persistente (no en temp por defecto).
- [ ] Caducidad por bloque: bloques completamente en el pasado sin caducidad; bloques que incluyen hoy o futuro, 5–15 min.
- [ ] Función para limpiar la caché.

**Hecho cuando:** repetir una descarga histórica no hace peticiones de red y pedir el día en curso siempre trae datos recientes.

---

## Fuera de este horizonte (a valorar después)

- Almacén local en Parquet con descarga incremental (la salida sigue siendo un DataFrame).
- CI en GitHub Actions (ruff, mypy, pytest) y publicación en PyPI.
- Cliente asíncrono (`httpx`).
