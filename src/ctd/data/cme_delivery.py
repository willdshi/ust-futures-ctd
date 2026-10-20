"""CME Treasury futures delivery reports, around delivery months.

Nice to have, not required (design section 3.2): the backtest computes the actual CTD from prices and
uses a report only to settle ambiguous cycles. Pulled when asked for, or dropped in the inbox.
Stores each configured page and every spreadsheet, CSV or PDF it links to.
"""

import re
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlparse

from ctd.data import refdata
from ctd.data.http import FetchError, Http
from ctd.data.sources import Kind, RawFile, SourceSpec
from ctd.reference.calendar import BusinessCalendar

DELIVERY_MONTHS = (3, 6, 9, 12)
ONE_DAY = timedelta(days=1)
HEADERS = {"Referer": "https://www.cmegroup.com/"}
_LINK = re.compile(rb"""href=["']([^"']+\.(?:xlsx?|csv|pdf))(?:\?[^"']*)?["']""", re.I)


def _basename(url: str) -> str:
    return PurePosixPath(urlparse(url).path).name or "index.html"


def fetch_pages(pages: list[str], http: Http) -> Iterator[RawFile]:
    if not pages:
        raise FetchError("no CME pages configured")
    seen = set()
    for page in pages:
        r = http.get(page, headers=HEADERS).ensure_ok()
        yield RawFile(_basename(r.url), r.content, r.url, r.status, r.content_type)
        for href in _LINK.findall(r.content):
            url = urljoin(r.url, href.decode("latin-1"))
            if url in seen:
                continue
            seen.add(url)
            f = http.get(url, headers=HEADERS).ensure_ok()
            yield RawFile(_basename(url), f.content, f.url, f.status, f.content_type)


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
               fetch=fetch, window=0, cme=True, schedule="occasional"),
]
