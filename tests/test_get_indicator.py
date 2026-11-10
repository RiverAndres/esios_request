"""
Tests de ``esios_get_indicator``.

Si se descubre un bug nuevo, añadir su test con ``xfail(strict=True)``: cuando se arregle,
el test pasará (XPASS → error) y habrá que quitar el ``xfail``.
"""

import copy
import inspect
import json
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
import requests

from esios_request import esios_get_archive, esios_get_indicator
from esios_request.esios_request import esios_get_request

from .conftest import (
    FMT,
    boundary_callback,
    daily_average,
    daily_trunc_callback,
    indicator_url,
    make_indicator_payload,
    make_value,
    query_params,
)

ONE_HOUR = {"start_date": "2025/01/01T00:00:00Z", "end_date": "2025/01/01T01:00:00Z"}


def test_devuelve_dataframe_con_indice_utc(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    df = esios_get_indicator(token, 600, params=dict(ONE_HOUR))

    assert isinstance(df, pd.DataFrame)
    assert df.index.name == "datetime_utc"
    assert isinstance(df.index, pd.DatetimeIndex)
    assert str(df.index.tz) == "UTC"
    assert {"value", "geo_id", "geo_name"} <= set(df.columns)
    assert len(df) == 2


def test_alias_y_id_numerico_piden_la_misma_url(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    esios_get_indicator(token, "p_pmd", params=dict(ONE_HOUR))
    esios_get_indicator(token, 600, params=dict(ONE_HOUR))

    urls = {c.request.url.split("?")[0] for c in mocked.calls}
    assert urls == {indicator_url(600)}


def test_envia_token_y_fechas(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    esios_get_indicator(token, 600, params=dict(ONE_HOUR), headers={"Accept": "application/json"})

    req = mocked.calls[0].request
    assert req.headers["x-api-key"] == token
    assert query_params(req) == ONE_HOUR


def test_parametros_extra_se_reenvian(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    esios_get_indicator(token, 600, params={**ONE_HOUR, "time_trunc": "hour"})

    assert query_params(mocked.calls[0].request)["time_trunc"] == "hour"


def test_rango_largo_se_trocea_en_bloques_de_6_meses_alineados_a_madrid(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    esios_get_indicator(
        token, 600, params={"start_date": "2025/01/01T00:00:00Z", "end_date": "2026/03/01T00:00:00Z"}
    )

    bloques = [(query_params(c.request)["start_date"], query_params(c.request)["end_date"]) for c in mocked.calls]
    # Fronteras = 1 de julio y 1 de enero a las 00:00 de Madrid (22:00Z en verano, 23:00Z en invierno).
    # Cada bloque acaba 1 s antes de la frontera: end_date es inclusivo y así no se solapan.
    assert bloques == [
        ("2025/01/01T00:00:00Z", "2025/06/30T21:59:59Z"),
        ("2025/06/30T22:00:00Z", "2025/12/31T22:59:59Z"),
        ("2025/12/31T23:00:00Z", "2026/03/01T00:00:00Z"),
    ]


def test_bloques_consecutivos_sin_huecos_ni_solapes(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    esios_get_indicator(
        token, 600, params={"start_date": "2020/03/15T10:30:00Z", "end_date": "2024/11/20T05:00:00Z"}
    )

    bloques = [
        (datetime.strptime(query_params(c.request)["start_date"], FMT),
         datetime.strptime(query_params(c.request)["end_date"], FMT))
        for c in mocked.calls
    ]
    assert bloques[0][0] == datetime(2020, 3, 15, 10, 30)
    assert bloques[-1][1] == datetime(2024, 11, 20, 5)
    for (_, fin), (siguiente, _) in pairwise(bloques):
        assert siguiente - fin == timedelta(seconds=1)
        frontera = siguiente.replace(tzinfo=UTC).astimezone(ZoneInfo("Europe/Madrid"))
        assert (frontera.day, frontera.hour, frontera.minute) == (1, 0, 0)
    for inicio, fin in bloques:
        assert inicio <= fin
        assert fin - inicio <= timedelta(days=185)


def test_time_trunc_day_no_parte_dias_entre_bloques(mocked, token):
    # Regresión: con bloques cortados a las 00:00Z, el día del corte llegaba con un promedio
    # parcial y se quedaba ese valor (verificado contra la API real el 2026-11-10).
    mocked.add_callback("GET", indicator_url(600), callback=daily_trunc_callback(600))
    rango = {"start_date": "2024/12/31T23:00:00Z", "end_date": "2026/02/28T22:59:59Z"}

    df = esios_get_indicator(token, 600, params={**rango, "time_trunc": "day", "time_agg": "average"})

    esperado = pd.DataFrame(daily_average(datetime(2024, 12, 31, 23), datetime(2026, 2, 28, 22, 59, 59)))
    esperado = esperado.set_index(pd.to_datetime(esperado["datetime_utc"], utc=True))["value"]
    assert len(mocked.calls) == 3
    assert not df.index.duplicated().any()
    pd.testing.assert_series_equal(df["value"], esperado, check_names=False, check_index_type=False)


def test_time_trunc_year_usa_bloques_anuales(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    esios_get_indicator(
        token, 600,
        params={"start_date": "2022/12/31T23:00:00Z", "end_date": "2025/12/31T22:59:59Z", "time_trunc": "year"},
    )

    bloques = [(query_params(c.request)["start_date"], query_params(c.request)["end_date"]) for c in mocked.calls]
    assert bloques == [
        ("2022/12/31T23:00:00Z", "2023/12/31T22:59:59Z"),
        ("2023/12/31T23:00:00Z", "2024/12/31T22:59:59Z"),
        ("2024/12/31T23:00:00Z", "2025/12/31T22:59:59Z"),
    ]


def test_inicio_igual_a_fin_pide_un_bloque(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    df = esios_get_indicator(
        token, 600, params={"start_date": "2025/01/01T00:00:00Z", "end_date": "2025/01/01T00:00:00Z"}
    )

    assert len(mocked.calls) == 1
    assert not df.empty


def test_sin_duplicados_entre_bloques(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    df = esios_get_indicator(
        token, 600, params={"start_date": "2025/01/01T00:00:00Z", "end_date": "2026/03/01T00:00:00Z"}
    )

    assert not df.index.duplicated().any()
    assert len(df) == 6  # inicio y fin de cada uno de los 3 bloques
    assert df.index.is_monotonic_increasing


def test_deduplica_si_la_api_repite_un_instante_entre_bloques(mocked, token):
    # Red de seguridad: aunque los bloques no se solapan, si la API devolviera el mismo
    # instante en dos bloques no debe salir repetido.
    repetido = make_value(datetime(2025, 6, 30, 22), 1.0)
    primero = make_indicator_payload(600, [make_value(datetime(2025, 1, 1), 0.0), repetido])
    segundo = make_indicator_payload(600, [repetido, make_value(datetime(2025, 9, 1), 2.0)])
    mocked.add("GET", indicator_url(600), json=primero)
    mocked.add("GET", indicator_url(600), json=segundo)

    df = esios_get_indicator(
        token, 600, params={"start_date": "2025/01/01T00:00:00Z", "end_date": "2025/09/01T00:00:00Z"}
    )

    assert len(mocked.calls) == 2
    assert list(df["value"]) == [0.0, 1.0, 2.0]


def test_error_http_se_propaga(mocked, token):
    mocked.add("GET", indicator_url(600), status=401, json={"message": "unauthorized"})

    with pytest.raises(requests.HTTPError):
        esios_get_indicator(token, 600, params=dict(ONE_HOUR))


def test_respuesta_sin_valores_devuelve_dataframe_vacio_con_columnas(mocked, token):
    mocked.add("GET", indicator_url(600), json=make_indicator_payload(600, []))

    df = esios_get_indicator(token, 600, params=dict(ONE_HOUR))

    assert isinstance(df, pd.DataFrame)
    assert df.empty
    assert list(df.columns) == ["value", "datetime", "tz_time", "geo_id", "geo_name"]
    assert df.index.name == "datetime_utc"
    assert isinstance(df.index, pd.DatetimeIndex)
    assert str(df.index.tz) == "UTC"


# --------------------------------------------------------------------------- Fase 1 (antes bugs)

GEOS_600 = [(1, "Portugal"), (2, "Francia"), (3, "España")]
LONG_RANGE = {"start_date": "2025/01/01T00:00:00Z", "end_date": "2026/03/01T00:00:00Z"}


def test_varios_geos_por_timestamp_no_se_pierden(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600, GEOS_600))

    df = esios_get_indicator(token, 600, params=dict(ONE_HOUR))

    assert set(df["geo_name"]) == {"Portugal", "Francia", "España"}
    assert len(df) == 2 * len(GEOS_600)


def test_varios_geos_y_varios_bloques_sin_duplicados(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600, GEOS_600))

    df = esios_get_indicator(token, 600, params=dict(LONG_RANGE))

    claves = list(zip(df.index, df["geo_id"]))
    assert len(claves) == len(set(claves))
    assert len(df) == 6 * len(GEOS_600)  # 6 instantes distintos x 3 geos
    assert df.groupby("geo_id").size().to_dict() == {1: 6, 2: 6, 3: 6}


def test_params_del_usuario_no_se_modifican(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))
    params = {**LONG_RANGE, "time_trunc": "hour"}
    original = copy.deepcopy(params)

    esios_get_indicator(token, 600, params=params)
    esios_get_indicator(token, 600, params=params)

    assert params == original


def test_headers_del_usuario_no_se_modifican(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))
    headers = {"Accept": "application/json"}

    esios_get_indicator(token, 600, params=dict(ONE_HOUR), headers=headers)
    esios_get_indicator(token, 600, params=dict(ONE_HOUR), headers=headers)

    assert headers == {"Accept": "application/json"}
    assert mocked.calls[0].request.headers["x-api-key"] == token


def test_headers_por_defecto_no_guardan_el_token(mocked, token):
    from esios_request.esios_request import DEFAULT_HEADERS

    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    esios_get_indicator(token, 600, params=dict(ONE_HOUR))
    esios_get_indicator(token, 600, params=dict(ONE_HOUR))

    assert "x-api-key" not in DEFAULT_HEADERS
    req = mocked.calls[0].request
    assert req.headers["x-api-key"] == token
    assert req.headers["Accept"] == DEFAULT_HEADERS["Accept"]


@pytest.mark.parametrize("func", [esios_get_indicator, esios_get_archive])
def test_firmas_sin_defaults_mutables(func):
    for p in inspect.signature(func).parameters.values():
        assert not isinstance(p.default, (dict, list, set)), p.name


def test_esios_get_request_sin_sesion_por_defecto_ni_parametro_muerto():
    sig = inspect.signature(esios_get_request)
    assert sig.parameters["session"].default is None
    assert "max_cache_entries" not in sig.parameters


@pytest.mark.parametrize(
    "payload",
    [{"inesperado": True}, {"indicator": {}}, {"indicator": {"values": "x"}}, {"indicator": {"values": [{"value": 1}]}}],
)
def test_respuesta_mal_formada_lanza_error(mocked, token, payload):
    mocked.add("GET", indicator_url(600), body=json.dumps(payload))

    with pytest.raises(ValueError, match="Respuesta inesperada"):
        esios_get_indicator(token, 600, params=dict(ONE_HOUR))


def test_respuesta_que_no_es_json_lanza_error(mocked, token):
    mocked.add("GET", indicator_url(600), body="<html>error</html>")

    with pytest.raises(ValueError):
        esios_get_indicator(token, 600, params=dict(ONE_HOUR))


@pytest.mark.parametrize("params", [{}, {"start_date": "2025/01/01T00:00:00Z"}, {"end_date": "2025/01/01T00:00:00Z"}])
def test_faltan_fechas_lanza_error_claro(params, token):
    with pytest.raises(ValueError, match="Faltan parámetros"):
        esios_get_indicator(token, 600, params=params)


def test_filtro_geo_ids_se_reenvia_en_cada_bloque(mocked, token):
    mocked.add_callback("GET", indicator_url(600), callback=boundary_callback(600))

    esios_get_indicator(token, 600, params={**LONG_RANGE, "geo_ids[]": [3, 1]})

    assert len(mocked.calls) == 3
    for call in mocked.calls:
        qs = parse_qs(urlparse(call.request.url).query)
        assert qs["geo_ids[]"] == ["3", "1"]


def test_geo_agg_filas_con_geo_ids_en_vez_de_geo_id(mocked, token):
    # Con geo_agg la API devuelve "geo_ids" (lista) y no "geo_id"/"geo_name": una fila por instante.
    def fila(dt, value):
        iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        return {"value": value, "datetime": iso, "datetime_utc": iso, "tz_time": iso, "geo_ids": [1, 2, 3]}

    mocked.add("GET", indicator_url(600), json=make_indicator_payload(600, [fila(datetime(2025, 1, 1), 1.0)]))
    mocked.add("GET", indicator_url(600), json=make_indicator_payload(600, [fila(datetime(2025, 9, 1), 2.0)]))

    df = esios_get_indicator(
        token, 600,
        params={"start_date": "2025/01/01T00:00:00Z", "end_date": "2025/09/01T00:00:00Z", "geo_agg": "sum"},
    )

    assert list(df["value"]) == [1.0, 2.0]
    assert "geo_id" not in df.columns
    assert df["geo_ids"].iloc[0] == [1, 2, 3]
    assert query_params(mocked.calls[0].request)["geo_agg"] == "sum"
