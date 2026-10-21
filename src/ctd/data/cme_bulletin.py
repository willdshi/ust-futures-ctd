"""CME Daily Bulletin sections: the daily source of option settlements (design section 3.1).

Section 42 covers options on ZT, ZF, ZN, TN, ZB and UB, every listed expiry and strike, weeklies
included. cmegroup.com blocks scripts, so the bulletin normally arrives through the browser
bookmarklet and the inbox. CME's URL always serves the latest bulletin, so a file downloaded late
for an earlier date is the wrong edition: ingest (and the automated fetch, if the CME switch is on)
reads the trade date and FINAL flag printed on page 1 and rejects a bulletin that doesn't match.
"""

import io
import re
from collections.abc import Iterator
from datetime import date, datetime

from ctd.data import refdata
from ctd.data.http import FetchError, Http
from ctd.data.sources import Kind, RawFile, SourceSpec

HEADERS = {"Referer": "https://www.cmegroup.com/"}
# Page-1 header, e.g. "PG42 BULLETIN # 201@ 10YR NOTE, ... OPTIONS Mon, Oct 19, 2026 PG42"
_HEADER = re.compile(r"BULLETIN\s*#\s*(\d+).*?((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), [A-Z][a-z]{2} \d{1,2}, \d{4})", re.S)


def _sections() -> dict[str, dict]:
    return {b["name"]: b for b in refdata.cme_products().get("bulletin", [])}


def bulletin_header(content: bytes) -> tuple[int, date, bool]:
    """(bulletin number, trade date, FINAL?) as printed on page 1."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        text = pdf.pages[0].extract_text() or ""
    m = _HEADER.search(text)
    if not m:
        raise ValueError("no bulletin number and trade date on page 1")
    return int(m[1]), datetime.strptime(m[2], "%a, %b %d, %Y").date(), "FINAL" in text


def check(asof: date, name: str, content: bytes) -> str | None:
    """Why ``content`` isn't the final bulletin for ``asof``, or None."""
    if not content.startswith(b"%PDF-"):
        return f"{name} is not a PDF"
    try:
        number, printed, final = bulletin_header(content)
    except Exception as e:
        return f"can't read the trade date in {name}: {e}"
    if printed != asof:
        return (f"{name} is bulletin #{number} for {printed}, not {asof}; CME's link serves only the latest "
                f"bulletin, so this date's bulletin can't be downloaded now. Delete the file from the inbox")
    if not final:
        return f"{name} is bulletin #{number} for {printed} but not FINAL yet; download it again later"
    return None


def fetch(asof: date, unit: str, http: Http) -> Iterator[RawFile]:
    r = http.get(_sections()[unit]["url"], headers=HEADERS).ensure_ok()
    reason = check(asof, f"{unit}.pdf", r.content)
    if reason:
        raise FetchError(reason)
    yield RawFile(f"{unit}.pdf", r.content, r.url, r.status, r.content_type)


SPECS = [
    SourceSpec("cme_bulletin", "CME Daily Bulletin sections (Section 42: Treasury options)", Kind.DATED, "cme",
               units=lambda asof, cal: list(_sections()), fetch=fetch, window=0, cme=True, validate=check),
]
