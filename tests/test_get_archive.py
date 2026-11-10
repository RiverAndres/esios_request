import pandas as pd
import pytest
import requests

from esios_request import esios_get_archive

from .conftest import archive_url

PAYLOAD = {"UF": [{"codigo": "UF1", "nombre": "Uno"}, {"codigo": "UF2", "nombre": "Dos"}]}


def test_devuelve_dataframe_con_la_primera_clave(mocked, token):
    mocked.add("GET", archive_url(110), json=PAYLOAD)

    df = esios_get_archive(token, 110)

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["codigo", "nombre"]
    assert len(df) == 2


def test_alias_de_archivo(mocked, token):
    mocked.add("GET", archive_url(110), json=PAYLOAD)

    esios_get_archive(token, "uf")

    assert mocked.calls[0].request.url.startswith(archive_url(110))
    assert mocked.calls[0].request.headers["x-api-key"] == token


def test_error_http_se_propaga(mocked, token):
    mocked.add("GET", archive_url(110), status=404, json={"message": "not found"})

    with pytest.raises(requests.HTTPError):
        esios_get_archive(token, 110)


def test_params_y_headers_del_usuario_no_se_modifican(mocked, token):
    mocked.add("GET", archive_url(110), json=PAYLOAD)
    params = {"date": "2025-01-01"}
    headers = {"Accept": "application/json"}

    esios_get_archive(token, 110, params=params, headers=headers)
    esios_get_archive(token, 110, params=params, headers=headers)

    assert params == {"date": "2025-01-01"}
    assert headers == {"Accept": "application/json"}


@pytest.mark.parametrize(
    "body", ["{}", '"texto"', "42", "[1, 2]", '{"UF": [1, 2]}', "<html>error</html>"]
)
def test_respuesta_mal_formada_lanza_error(mocked, token, body):
    mocked.add("GET", archive_url(110), body=body)

    with pytest.raises(ValueError):
        esios_get_archive(token, 110)


def test_lista_vacia_devuelve_dataframe_vacio(mocked, token):
    mocked.add("GET", archive_url(110), json={"UF": []})

    df = esios_get_archive(token, 110)

    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_lista_plana_de_filas_devuelve_dataframe(mocked, token):
    # Formato del ejemplo de la documentación oficial de download_json.
    filas = [
        {"Indicadores": "Precio", "31/03/2014": "0,119941"},
        {"Indicadores": "Energía", "31/03/2014": "1,5"},
    ]
    mocked.add("GET", archive_url(110), json=filas)

    df = esios_get_archive(token, 110)

    assert list(df.columns) == ["Indicadores", "31/03/2014"]
    assert list(df["Indicadores"]) == ["Precio", "Energía"]


def test_lista_plana_vacia_devuelve_dataframe_vacio(mocked, token):
    mocked.add("GET", archive_url(110), json=[])

    df = esios_get_archive(token, 110)

    assert isinstance(df, pd.DataFrame)
    assert df.empty
