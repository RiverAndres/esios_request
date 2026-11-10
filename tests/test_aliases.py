import pytest

from esios_request.indicators import (
    archives,
    common_archives,
    common_indicators,
    indicators,
)


def test_indicator_alias_is_translated_to_id():
    assert common_indicators("p_pmd") == 600


def test_numeric_indicator_id_is_returned_unchanged():
    assert common_indicators(600) == 600


def test_archive_alias_is_translated_to_id():
    assert common_archives("uf") == 110


def test_numeric_archive_id_is_returned_unchanged():
    assert common_archives(110) == 110


def test_unknown_alias_raises_keyerror():
    with pytest.raises(KeyError):
        common_indicators("does_not_exist")


@pytest.mark.parametrize("catalogue", [indicators, archives])
def test_catalogues_have_no_repeated_ids(catalogue):
    ids = list(catalogue.values())
    assert len(ids) == len(set(ids))
