"""TreasuryDirect securities search: terms of every auctioned security (CUSIP, coupon, dated date, ...)."""

from collections.abc import Iterator
from datetime import date

from ctd.data.http import FetchError, Http
from ctd.data.sources import Kind, RawFile, SourceSpec

URL = "https://www.treasurydirect.gov/TA_WS/securities/search"
TYPES = ["Bill", "Note", "Bond", "CMB", "TIPS", "FRN"]


def fetch(asof: date, unit: str, http: Http) -> Iterator[RawFile]:
    params = {"format": "json", "type": unit}
    r = http.get(URL, params=params).ensure_ok()
    if not r.content.lstrip().startswith(b"[") or len(r.content) < 3:
        raise FetchError(f"TreasuryDirect securities search for {unit} returned no list")
    yield RawFile(f"securities_{unit}.json", r.content, r.url, r.status, r.content_type, params=params)


SPECS = [
    SourceSpec("td_securities", "TreasuryDirect securities search, by security type", Kind.HISTORY, "cme",
               units=lambda asof, cal: list(TYPES), fetch=fetch),
]
