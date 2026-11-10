import pytest

from esios_request.indicators import (
    archives,
    common_archives,
    common_indicators,
    indicators,
)


def test_alias_de_indicador_se_traduce_a_id():
    assert common_indicators("p_pmd") == 600


def test_id_numerico_de_indicador_se_devuelve_igual():
    assert common_indicators(600) == 600


def test_alias_de_archivo_se_traduce_a_id():
    assert common_archives("uf") == 110


def test_id_numerico_de_archivo_se_devuelve_igual():
    assert common_archives(110) == 110


def test_alias_desconocido_lanza_keyerror():
    with pytest.raises(KeyError):
        common_indicators("no_existe")


@pytest.mark.parametrize("catalogo", [indicators, archives])
def test_catalogos_sin_ids_repetidos(catalogo):
    ids = list(catalogo.values())
    assert len(ids) == len(set(ids))
