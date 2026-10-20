"""TreasuryDirect FedInvest end-of-day prices: the whole file, every CUSIP.

The site needs a three-step form flow (each step hands out a CSRF token). Past dates can
be requested back to 30 May 2008 (files before about September 2008 carry only CUSIP and prices).
A date with no prices returns an empty file: NoData, so a past holiday isn't reported as a gap.
"""

import re
from collections.abc import Iterator
from datetime import date

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


SPECS = [
    SourceSpec("td_prices", "TreasuryDirect FedInvest daily prices, all CUSIPs", Kind.DATED, "sifma",
               units=lambda asof, cal: ["securityprice"], fetch=fetch),
]
