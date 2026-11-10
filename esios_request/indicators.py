"""
Catalogue of readable aliases for e·sios indicators and archives.

Units come from the API metadata (``magnitud``, checked on 2026-11-10). For energy and power the
API only gives the magnitude ("Energía", "Potencia"); MWh and MW are e·sios' usual units.
"""

import difflib
from dataclasses import asdict, dataclass

import pandas as pd

from .exceptions import EsiosConfigError, EsiosUnknownAlias


@dataclass(frozen=True)
class Indicator:
    alias: str
    id: int
    unit: str
    description: str


@dataclass(frozen=True)
class Archive:
    alias: str
    id: int
    description: str


INDICATORS: dict[str, Indicator] = {i.alias: i for i in (
    Indicator("p_pmd", 600, "EUR/MWh", "Marginal day-ahead market price."),
    Indicator("p_pmi1", 612, "EUR/MWh", "Marginal intraday session 1 market price."),
    Indicator("p_pmi2", 613, "EUR/MWh", "Marginal intraday session 2 market price."),
    Indicator("p_pmi3", 614, "EUR/MWh", "Marginal intraday session 3 market price."),
    Indicator("p_pmi4", 615, "EUR/MWh", "Marginal intraday session 4 market price."),
    Indicator("p_pmi5", 616, "EUR/MWh", "Marginal intraday session 5 market price."),
    Indicator("p_pmi6", 617, "EUR/MWh", "Marginal intraday session 6 market price."),
    Indicator("p_pmi7", 618, "EUR/MWh", "Marginal intraday session 7 market price."),
    Indicator("p_afrr_up", 2130, "EUR/MW", "aFRR up reserve price."),
    Indicator("p_afrr_down", 634, "EUR/MW", "aFRR down reserve price."),
    Indicator("p_afrr_act_up", 682, "EUR/MWh", "aFRR up activation price."),
    Indicator("p_afrr_act_down", 683, "EUR/MWh", "aFRR down activation price."),
    Indicator("e_pmd", 602, "MWh", "Energy traded, day-ahead market."),
    Indicator("e_pmi1", 605, "MWh", "Energy traded, intraday session 1."),
    Indicator("e_pmi2", 606, "MWh", "Energy traded, intraday session 2."),
    Indicator("e_pmi3", 607, "MWh", "Energy traded, intraday session 3."),
    Indicator("e_pmi4", 608, "MWh", "Energy traded, intraday session 4."),
    Indicator("e_pmi5", 609, "MWh", "Energy traded, intraday session 5."),
    Indicator("e_pmi6", 610, "MWh", "Energy traded, intraday session 6."),
    Indicator("e_pmi7", 611, "MWh", "Energy traded, intraday session 7."),
    Indicator("band_afrr_up", 632, "MW", "aFRR up allocated band."),
    Indicator("band_afrr_down", 633, "MW", "aFRR down allocated band."),
    Indicator("e_afrr_act_up", 680, "MWh", "aFRR up activated energy."),
    Indicator("e_afrr_act_down", 681, "MWh", "aFRR down activated energy."),
)}

ARCHIVES: dict[str, Archive] = {a.alias: a for a in (
    Archive("uf", 110, "Physical units (UF)."),
    Archive("up", 111, "Programming units (UP)."),
    Archive("brp", 112, "Balance responsible parties (BRP)."),
    Archive("entitled_participants", 113, "Entitled market participants."),
)}

# Backward compatible alias → id dicts (v1.x).
indicators: dict[str, int] = {alias: i.id for alias, i in INDICATORS.items()}
archives: dict[str, int] = {alias: a.id for alias, a in ARCHIVES.items()}


def _resolve(value: str | int, catalogue: dict[str, int], kind: str) -> int:
    if isinstance(value, bool):
        raise EsiosConfigError(f"Invalid {kind} id: {value!r}.")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        if value.isdigit():
            return int(value)
        if value in catalogue:
            return catalogue[value]
        close = difflib.get_close_matches(value, catalogue, n=3)
        hint = f" Did you mean: {', '.join(close)}?" if close else ""
        raise EsiosUnknownAlias(
            f"Unknown {kind} alias {value!r}.{hint} Use a numeric id or one of the aliases in "
            f"esios_request.indicators (see indicator_catalogue() / archive_catalogue())."
        )
    raise EsiosConfigError(f"The {kind} id must be an alias (str) or a numeric id (int); got {type(value).__name__}.")


def common_indicators(value: str | int) -> int:
    """Indicator alias or numeric id → numeric id. Unknown alias → ``EsiosUnknownAlias``."""
    return _resolve(value, indicators, "indicator")


def common_archives(value: str | int) -> int:
    """Archive alias or numeric id → numeric id. Unknown alias → ``EsiosUnknownAlias``."""
    return _resolve(value, archives, "archive")


def indicator_catalogue() -> pd.DataFrame:
    """Indicator aliases as a DataFrame (alias, id, unit, description), indexed by alias."""
    return pd.DataFrame([asdict(i) for i in INDICATORS.values()]).set_index("alias")


def archive_catalogue() -> pd.DataFrame:
    """Archive aliases as a DataFrame (alias, id, description), indexed by alias."""
    return pd.DataFrame([asdict(a) for a in ARCHIVES.values()]).set_index("alias")
