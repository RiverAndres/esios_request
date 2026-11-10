from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import requests_cache
from dateutil.relativedelta import relativedelta

from .indicators import common_archives, common_indicators
from .req_cache import get_session

BASE_URL = "https://api.esios.ree.es"
DATE_FMT = "%Y/%m/%dT%H:%M:%SZ"
BLOCK_SIZE = relativedelta(months = 6)
# Con ``time_trunc=year`` un bloque de 6 meses partiría el año: se usan bloques de 12 meses
# (comprobado contra la API real el 2026-11-10: acepta un año completo con time_trunc=year).
YEAR_BLOCK_SIZE = relativedelta(years = 1)
# La API alinea los periodos de ``time_trunc`` a la hora peninsular española.
API_TZ = ZoneInfo("Europe/Madrid")

DEFAULT_HEADERS: dict[str, str] = {
    "Accept": "application/json; application/vnd.esios-api-v1+json",
    "Content-Type": "application/json",
    "User-Agent": "PostmanRuntime/7.39.1",
}

# Columnas de ``indicator.values`` (sin ``datetime_utc``, que pasa a ser el índice).
INDICATOR_COLUMNS = ["value", "datetime", "tz_time", "geo_id", "geo_name"]


def esios_get_request(
    token:str,
    url:str,
    headers:dict | None = None,
    params:dict | None = None,
    session:requests.Session | requests_cache.CachedSession | None = None,
    ) -> requests.Response:
    """
    Get request with token type ``x-api-key``.

    ``headers`` and ``params`` are never modified.

    Returns
    -----
    ``object`` requests.get.response
    """

    request_headers = {**(headers if headers is not None else DEFAULT_HEADERS), "x-api-key": token}
    if session is None:
        session = requests.Session()

    response = session.get(url = url, headers = request_headers, params = params, timeout = (5, 180))
    return response


def _empty_indicator_frame() -> pd.DataFrame:
    """DataFrame vacío con la misma forma que devuelve un indicador con datos."""
    index = pd.DatetimeIndex([], tz = "UTC", name = "datetime_utc")
    return pd.DataFrame(columns = INDICATOR_COLUMNS, index = index)


def _parse_indicator_values(payload, url:str) -> pd.DataFrame:
    """Convierte el JSON de ``/indicators/{id}`` en DataFrame. Lanza ``ValueError`` si el formato no es el esperado."""
    try:
        values = payload["indicator"]["values"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Respuesta inesperada de {url}: falta 'indicator.values'.") from exc

    if not isinstance(values, list):
        raise ValueError(f"Respuesta inesperada de {url}: 'indicator.values' no es una lista.")
    if not values:
        return _empty_indicator_frame()

    df = pd.DataFrame(values)
    if "datetime_utc" not in df.columns:
        raise ValueError(f"Respuesta inesperada de {url}: los valores no tienen 'datetime_utc'.")

    df = df.set_index("datetime_utc")
    df.index = pd.to_datetime(df.index, utc = True)
    return df


def _next_block_boundary(start:datetime, yearly:bool) -> datetime:
    """
    Siguiente frontera de bloque tras ``start`` (UTC sin tz): inicio de mes en hora de Madrid
    ``BLOCK_SIZE`` después del mes de ``start`` (o inicio de año si ``yearly``). Devuelve UTC sin tz.
    """
    local = start.replace(tzinfo = UTC).astimezone(API_TZ)
    if yearly:
        floor, step = datetime(local.year, 1, 1, tzinfo = API_TZ), YEAR_BLOCK_SIZE
    else:
        floor, step = datetime(local.year, local.month, 1, tzinfo = API_TZ), BLOCK_SIZE
    return (floor + step).astimezone(UTC).replace(tzinfo = None)


def _block_ranges(start:datetime, end:datetime, time_trunc:str | None = None) -> list[tuple[datetime, datetime]]:
    """
    Trocea ``[start, end]`` (ambos inclusivos, UTC sin tz) en bloques **sin solapamiento**
    cuyas fronteras caen en inicio de mes (o de año con ``time_trunc="year"``) en hora de Madrid.

    Así ningún periodo de ``time_trunc`` (día, mes, año…) queda partido entre dos bloques:
    si quedara partido, la API devolvería un agregado parcial en cada bloque.
    Cada bloque termina 1 s antes de la frontera porque ``end_date`` es inclusivo.
    """
    yearly = time_trunc == "year"
    blocks = []
    block_start = start
    while block_start <= end:
        boundary = _next_block_boundary(block_start, yearly)
        blocks.append((block_start, min(boundary - timedelta(seconds = 1), end)))
        block_start = boundary
    return blocks


def esios_get_indicator(
    token:str,
    id:str | int,
    params:dict,
    headers:dict | None = None,
    use_cache: bool = False,
    ) -> pd.DataFrame:
    """
    Get request to an e·sios indicator by specifiying the ``id`` (alias ``str`` or ``int``).
    The function can handle time intervals of any size: it splits them into non-overlapping
    blocks aligned to Europe/Madrid month starts (year starts with ``time_trunc="year"``),
    so that no ``time_trunc`` period is split between two requests.

    Parameters
    -----
    - ``token``:str --> e·sios API key.
    - ``id``:str | int --> Alias (e.g. "p_pmd") or numeric id (e.g. 600).
    - ``params``: dict --> Must contain at least: {"start_date": "%Y/%m/%dT%H:%M:%SZ", "end_date": "%Y/%m/%dT%H:%M:%SZ"}. It is not modified.
    - ``headers``: dict --> By default contains "Accept", "Content-Type", & "User-Agent". It is not modified.
    - ``use_cache``: bool --> By default "False". Uses the module requests_cache to store the request an avoid doing the same GET request.
    Returns
    -----
    ``pd.DataFrame`` containing the values of the id specified, indexed by ``datetime_utc`` (UTC).
    When the indicator has several geographies there is one row per (``datetime_utc``, ``geo_id``).
    """

    params = dict(params or {})
    missing = [key for key in ("start_date", "end_date") if not params.get(key)]
    if missing:
        raise ValueError(f"Faltan parámetros obligatorios: {', '.join(missing)} (formato {DATE_FMT!r}).")

    session = get_session(use_cache)
    indicator = common_indicators(id)
    endpoint = f"{BASE_URL}/indicators/{indicator}"
    start_date = datetime.strptime(params["start_date"], DATE_FMT)
    end_date = datetime.strptime(params["end_date"], DATE_FMT)

    frames: list[pd.DataFrame] = []
    for block_start, block_end in _block_ranges(start_date, end_date, params.get("time_trunc")):
        block_params = {
            **params,
            "start_date": block_start.strftime(DATE_FMT),
            "end_date": block_end.strftime(DATE_FMT),
        }
        res = esios_get_request(session = session, token = token, url = endpoint, headers = headers, params = block_params)
        res.raise_for_status()
        frames.append(_parse_indicator_values(res.json(), endpoint))

    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return _empty_indicator_frame()

    df = pd.concat(frames)

    # Los bloques no se solapan, pero se deduplica por seguridad (por si la API devolviera un
    # instante fuera del rango pedido). Por (instante, geo) para no perder geografías.
    keys = df.index.to_frame(index = False)
    if "geo_id" in df.columns:
        keys["geo_id"] = df["geo_id"].to_numpy()
    df = df[~keys.duplicated(keep = "first").to_numpy()]

    return df


def esios_get_archive(
    token:str,
    id:str | int,
    params:dict | None = None,
    headers:dict | None = None,
    use_cache: bool = False,
    ) -> pd.DataFrame:
    """
    Get request to an e·sios archive by specifiying the ``id`` (alias ``str`` or ``int``).

    Parameters
    -----
    - ``token``:str --> e·sios API key.
    - ``id``:str | int --> Alias (e.g. "uf") or numeric id (e.g. 110).
    - ``params``: dict --> Optional query parameters. It is not modified.
    - ``headers``: dict --> By default contains "Accept", "Content-Type", & "User-Agent". It is not modified.
    - ``use_cache``: bool --> By default "False".

    Returns
    -----
    ``pd.DataFrame`` built from the returned JSON: a flat list of rows, or the first key of an object.
    """

    session = get_session(use_cache)
    archive = common_archives(id)
    endpoint = f"{BASE_URL}/archives/{archive}/download_json"

    res = esios_get_request(session = session, token = token, url = endpoint, headers = headers, params = params)
    res.raise_for_status()
    payload = res.json()

    # La API puede devolver una lista plana de filas o un objeto cuya primera clave contiene las filas.
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and payload:
        rows = next(iter(payload.values()))
    else:
        raise ValueError(f"Respuesta inesperada de {endpoint}: se esperaba una lista o un objeto JSON no vacío.")

    if isinstance(rows, list) and not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"Respuesta inesperada de {endpoint}: las filas no son objetos JSON.")

    return pd.DataFrame(rows)
