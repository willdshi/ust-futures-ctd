"""CME Daily Bulletin sections: the daily source of option settlements (design section 3.1).

Section 42 covers options on ZT, ZF, ZN, TN, ZB and UB, every listed expiry and strike, weeklies
included. cmegroup.com blocks scripts, so the bulletin normally arrives through the browser
bookmarklet and the inbox. CME's URL always serves the latest bulletin, so an automated fetch
(CME switch on) is only trusted for the current date.
"""

from collections.abc import Iterator
from datetime import date

from ctd.data import refdata
from ctd.data.http import FetchError, Http
from ctd.data.sources import Kind, RawFile, SourceSpec

HEADERS = {"Referer": "https://www.cmegroup.com/"}


def _sections() -> dict[str, dict]:
    return {b["name"]: b for b in refdata.cme_products().get("bulletin", [])}


def fetch(asof: date, unit: str, http: Http) -> Iterator[RawFile]:
    r = http.get(_sections()[unit]["url"], headers=HEADERS).ensure_ok()
    if not r.content.startswith(b"%PDF-"):
        raise FetchError(f"bulletin {unit} is not a PDF (blocked?)")
    yield RawFile(f"{unit}.pdf", r.content, r.url, r.status, r.content_type)


SPECS = [
    SourceSpec("cme_bulletin", "CME Daily Bulletin sections (Section 42: Treasury options)", Kind.DATED, "cme",
               units=lambda asof, cal: list(_sections()), fetch=fetch, window=0, cme=True),
]
