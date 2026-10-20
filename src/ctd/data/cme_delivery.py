"""CME Treasury futures delivery reports (backtest ground truth), expected around delivery months only."""

from collections.abc import Iterator
from datetime import date, timedelta

from ctd.data import refdata
from ctd.data.cme_cf import fetch_pages
from ctd.data.http import Http
from ctd.data.sources import Kind, RawFile, SourceSpec
from ctd.reference.calendar import BusinessCalendar

DELIVERY_MONTHS = (3, 6, 9, 12)
ONE_DAY = timedelta(days=1)


def in_delivery_period(asof: date, cal: BusinessCalendar) -> bool:
    """True from the first intention day (2 business days before the first business day of a
    delivery month) to the 3rd business day of the following month (last delivery day of the
    short contracts). A collection window only; the per-contract delivery calendars live in reference data.
    """
    for year in (asof.year - 1, asof.year):
        for month in DELIVERY_MONTHS:
            first = cal.add_business_days(date(year, month, 1) - ONE_DAY, 1)
            next_month = date(year + month // 12, month % 12 + 1, 1)
            start = cal.add_business_days(first, -2)
            end = cal.add_business_days(next_month - ONE_DAY, 3)
            if start <= asof <= end:
                return True
    return False


def fetch(asof: date, unit: str, http: Http) -> Iterator[RawFile]:
    yield from fetch_pages(refdata.cme_products()["cme_delivery"]["pages"], http)


SPECS = [
    SourceSpec("cme_delivery", "CME Treasury futures delivery reports", Kind.DATED, "cme",
               units=lambda asof, cal: ["reports"] if in_delivery_period(asof, cal) else [],
               fetch=fetch, window=0, cme=True),
]
