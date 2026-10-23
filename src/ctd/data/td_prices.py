"""TreasuryDirect FedInvest daily prices: the whole file, every CUSIP. Fetcher and reader.

The site needs a three-step form flow (each step hands out a CSRF token). Past dates can
be requested back to 30 May 2008 (files before about September 2008 carry only CUSIP and prices).
A date with no prices returns an empty file: NoData, so a past holiday isn't reported as a gap.

The end-of-day column is filled in later than buy and sell: a file pulled the same evening has
it empty for every note and bond. Such a file is provisional, and the one exception to never
overwriting a stored file (``SourceSpec.provisional``): later runs pull the date again and replace
it once end-of-day prices are in. Any past date can be pulled again, so nothing is lost.
"""

import csv
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime

from ctd.data.http import FetchError, Http, NoData
from ctd.data.sources import Kind, RawFile, SourceSpec

BASE = "https://www.treasurydirect.gov/GA-FI/FedInvest/"
_CSRF = re.compile(r'name="_csrf" value="([^"]+)"')
_CSV_FORM_CSRF = re.compile(r'id="CSVFormat".*?name="_csrf" value="([^"]+)"', re.S)


def fetch(asof: date, unit: str, http: Http) -> Iterator[RawFile]:
    form = http.get(BASE + "selectSecurityPriceDate").ensure_ok()
    m = _CSRF.search(form.content.decode("latin-1"))
    if not m:
        raise FetchError("FedInvest date form has no CSRF token")
    page = http.post(BASE + "selectSecurityPriceDate",
                     data={"priceDate": asof.isoformat(), "submit": "Show Prices", "_csrf": m.group(1)}).ensure_ok()
    m = _CSV_FORM_CSRF.search(page.content.decode("latin-1"))
    if not m:
        raise FetchError(f"FedInvest shows no CSV download for {asof}")
    params = {"priceDateDay": str(asof.day), "priceDateMonth": str(asof.month),
              "priceDateYear": str(asof.year), "fileType": "csv", "csv": "CSV FORMAT"}
    r = http.post(BASE + "securityPriceDetail", data={**params, "_csrf": m.group(1)}).ensure_ok()
    if not r.content.strip():
        raise NoData(f"FedInvest returned an empty price file for {asof}")
    yield RawFile(f"securityprice_{asof.isoformat()}.csv", r.content, r.url, r.status, r.content_type,
                  "POST", params)


def provisional(content: bytes) -> bool:
    """True unless some note or bond has an end-of-day price (column 7). Unreadable counts as provisional."""
    try:
        rows = list(csv.reader(io.StringIO(content.decode("latin-1"))))
        return not any(("NOTE" in r[1] or "BOND" in r[1]) and float(r[7] or 0) > 0 for r in rows if len(r) > 7)
    except (UnicodeDecodeError, ValueError, csv.Error):
        return True


@dataclass(frozen=True)
class BondPrice:
    """A fixed-coupon note or bond's clean price for one date. ``price_from``: "eod", "mid" or "sell"."""

    cusip: str
    coupon: float  # decimal
    maturity: date
    price: float
    price_from: str


def parse(content: bytes) -> dict[str, BondPrice]:
    """Notes and bonds by CUSIP (bills, FRNs and TIPS are skipped; so is a row with no price).

    Price: end of day where filled; otherwise the buy/sell midpoint, or sell where there is no
    buy (docs/decisions.md). Only a provisional file lacks end of day.
    """
    out = {}
    for r in csv.reader(io.StringIO(content.decode("latin-1"))):
        if len(r) < 8 or r[1] not in ("MARKET BASED NOTE", "MARKET BASED BOND"):
            continue
        buy, sell, eod = (float(x or 0) for x in r[5:8])
        if eod > 0:
            price, src = eod, "eod"
        elif buy > 0 and sell > 0:
            price, src = (buy + sell) / 2, "mid"
        elif sell > 0:
            price, src = sell, "sell"
        else:
            continue
        out[r[0]] = BondPrice(r[0], float(r[2]), datetime.strptime(r[3], "%m/%d/%Y").date(), price, src)
    return out


def read(store, asof: date) -> tuple[dict[str, BondPrice], bool]:
    """``asof``'s note and bond prices from the raw store, and whether the file is still provisional."""
    content = store.read(asof, "td_prices", "securityprice", f"securityprice_{asof.isoformat()}.csv")
    return parse(content), provisional(content)


SPECS = [
    SourceSpec("td_prices", "TreasuryDirect FedInvest daily prices, all CUSIPs", Kind.DATED, "sifma",
               units=lambda asof, cal: ["securityprice"], fetch=fetch, provisional=provisional),
]
