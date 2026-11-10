import pandas as pd
import pytest
import requests

from esios_request import esios_get_archive

from .conftest import archive_url

PAYLOAD = {"UF": [{"codigo": "UF1", "nombre": "Uno"}, {"codigo": "UF2", "nombre": "Dos"}]}


def test_returns_dataframe_from_first_key(mocked, token):
    mocked.add("GET", archive_url(110), json=PAYLOAD)

    df = esios_get_archive(token, 110)

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["codigo", "nombre"]
    assert len(df) == 2


def test_archive_alias(mocked, token):
    mocked.add("GET", archive_url(110), json=PAYLOAD)

    esios_get_archive(token, "uf")

    assert mocked.calls[0].request.url.startswith(archive_url(110))
    assert mocked.calls[0].request.headers["x-api-key"] == token


def test_http_error_is_propagated(mocked, token):
    mocked.add("GET", archive_url(110), status=404, json={"message": "not found"})

    with pytest.raises(requests.HTTPError):
        esios_get_archive(token, 110)


def test_user_params_and_headers_are_not_modified(mocked, token):
    mocked.add("GET", archive_url(110), json=PAYLOAD)
    params = {"date": "2025-01-01"}
    headers = {"Accept": "application/json"}

    esios_get_archive(token, 110, params=params, headers=headers)
    esios_get_archive(token, 110, params=params, headers=headers)

    assert params == {"date": "2025-01-01"}
    assert headers == {"Accept": "application/json"}


@pytest.mark.parametrize(
    "body", ["{}", '"text"', "42", "[1, 2]", '{"UF": [1, 2]}', "<html>error</html>"]
)
def test_malformed_response_raises_error(mocked, token, body):
    mocked.add("GET", archive_url(110), body=body)

    with pytest.raises(ValueError):
        esios_get_archive(token, 110)


def test_empty_list_returns_empty_dataframe(mocked, token):
    mocked.add("GET", archive_url(110), json={"UF": []})

    df = esios_get_archive(token, 110)

    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_flat_list_of_rows_returns_dataframe(mocked, token):
    # Format of the official download_json documentation example (the API returns Spanish labels).
    rows = [
        {"Indicadores": "Precio", "31/03/2014": "0,119941"},
        {"Indicadores": "Energía", "31/03/2014": "1,5"},
    ]
    mocked.add("GET", archive_url(110), json=rows)

    df = esios_get_archive(token, 110)

    assert list(df.columns) == ["Indicadores", "31/03/2014"]
    assert list(df["Indicadores"]) == ["Precio", "Energía"]


def test_empty_flat_list_returns_empty_dataframe(mocked, token):
    mocked.add("GET", archive_url(110), json=[])

    df = esios_get_archive(token, 110)

    assert isinstance(df, pd.DataFrame)
    assert df.empty
