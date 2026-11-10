# esios_request

Easily obtain data published by REE in its public ESIOS API as a `pandas.DataFrame`.

This module was created mainly to obtain time series; there are features and endpoints that are not included in this version. They will be added as needed.

## Instalación

```bash
pip install git+https://github.com/RiverAndres/esios_request.git
```

Para desarrollo (tests, linters):

```bash
pip install -e ".[dev]"
```

## Uso rápido

```python
from esios_request import esios_get_indicator, esios_get_archive

token = "TU_ESIOS_API_KEY"

# Indicador por alias (str) o por id numérico (int)
df = esios_get_indicator(
    token,
    "p_pmd",  # equivalente a 600
    params={
        "start_date": "2025/01/01T00:00:00Z",
        "end_date": "2025/01/01T01:00:00Z",
    },
    use_cache=True,
)

# Archivo
df_uf = esios_get_archive(token, "uf")  # equivalente a 110
```

## Funciones

```python
esios_get_indicator(
    token: str,
    id: str | int,          # alias (p.ej. "p_pmd") o id numérico (600)
    params: dict,           # debe incluir "start_date" y "end_date" en formato "%Y/%m/%dT%H:%M:%SZ"
    headers: dict | None = None,  # por defecto Accept, Content-Type y User-Agent
    use_cache: bool = False,
) -> pd.DataFrame

esios_get_archive(
    token: str,
    id: str | int,          # alias (p.ej. "uf") o id numérico (110)
    params: dict | None = None,
    headers: dict | None = None,
    use_cache: bool = False,
) -> pd.DataFrame
```

- `esios_get_indicator` admite intervalos de cualquier tamaño: los trocea en bloques de hasta 6 meses (12 con `time_trunc="year"`) que no se solapan y que empiezan a principio de mes (o de año) en **hora de Madrid**, y concatena el resultado. Así, con `time_trunc` (`day`, `month`…) ningún periodo queda partido entre dos peticiones y los agregados salen completos. El índice es `datetime_utc` (UTC). `end_date` es inclusivo.
- `time_agg`/`geo_agg` **sin** `time_trunc` agregan dentro de cada bloque: en rangos largos obtendrás una fila por bloque, no una sola para todo el rango.
- Si un indicador tiene varias geografías (p.ej. `p_pmd`: España, Portugal, Francia…), hay **una fila por instante y `geo_id`**, así que el índice puede repetirse. Para pedir solo ciertas zonas puedes usar el filtro de la propia API, que descarga menos datos (no todos los indicadores lo admiten; si no tiene efecto, filtra después con `df[df["geo_id"] == 3]`):

  ```python
  params = {"start_date": "...", "end_date": "...", "geo_ids[]": [3]}  # 3 = España
  ```

  Cualquier otro parámetro de la API (`time_trunc`, `geo_agg`…) se reenvía igual en cada bloque.
- Si no hay datos en el rango, devuelve un `DataFrame` vacío con las mismas columnas.
- Los diccionarios `params` y `headers` que pases **no se modifican**.
- `esios_get_archive` acepta las dos formas de respuesta de `download_json`: una lista plana de filas o un objeto cuya primera clave contiene las filas.
- Errores: un fallo HTTP lanza `requests.HTTPError`; una respuesta con formato inesperado o sin `start_date`/`end_date` lanza `ValueError`.
- `use_cache=True` guarda las respuestas durante 24 h con `requests-cache`, evitando repetir peticiones idénticas.

La lista de alias disponibles está en `esios_request/indicators.py`.

## Versión

```python
import esios_request
esios_request.__version__
```
