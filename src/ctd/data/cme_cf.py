"""CME conversion factor / deliverable basket tables for every listed Treasury contract month.

Validation data only (design section 3.2): CFs come from the formula and baskets from the rules,
so this is pulled occasionally, not daily. CME keeps no past versions, so it can only be pulled
for the current date. Stores each configured page and every spreadsheet, CSV or PDF it links to.
"""

import re
from collections.abc import Iterator
from datetime import date
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlparse

from ctd.data import refdata
from ctd.data.http import FetchError, Http
from ctd.data.sources import Kind, RawFile, SourceSpec

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


def fetch(asof: date, unit: str, http: Http) -> Iterator[RawFile]:
    yield from fetch_pages(refdata.cme_products()["cme_cf"]["pages"], http)


SPECS = [
    SourceSpec("cme_cf", "CME conversion factor and deliverable basket tables", Kind.SNAPSHOT, "cme",
               units=lambda asof, cal: ["tables"], fetch=fetch, window=0, cme=True, schedule="occasional"),
]
