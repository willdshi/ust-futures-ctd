"""All collected sources, by id."""

from datetime import date

from ctd.data import (cme_delivery, cme_settlements, cme_tcf, fiscaldata, fred, nyfed, par_curve, refdata,
                      td_prices, td_securities)
from ctd.data.sources import SourceSpec

_MODULES = (td_prices, td_securities, fiscaldata, par_curve, fred, nyfed, cme_tcf, cme_settlements, cme_delivery)

SOURCES: dict[str, SourceSpec] = {s.id: s for m in _MODULES for s in m.SPECS}


def daily() -> list[SourceSpec]:
    return [s for s in SOURCES.values() if s.schedule == "daily"]


def backfill() -> list[SourceSpec]:
    return [s for s in SOURCES.values() if s.schedule == "backfill"]


def units_for(source: str, asof: date) -> list[str] | None:
    """A source's units on ``asof``, or None if the source is unknown."""
    spec = SOURCES.get(source)
    return None if spec is None else spec.units(asof, refdata.calendar(spec.calendar))
