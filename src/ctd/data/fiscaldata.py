"""FiscalData Treasury securities auctions (all auctions since 1979, including matured issues)."""

import json
from collections.abc import Iterator
from datetime import date

from ctd.data.http import FetchError, Http
from ctd.data.sources import Kind, RawFile, SourceSpec

URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query"
PAGE_SIZE = 10000


def fetch(asof: date, unit: str, http: Http) -> Iterator[RawFile]:
    page, pages = 1, 1
    while page <= pages:
        params = {"format": "json", "page[size]": str(PAGE_SIZE), "page[number]": str(page)}
        r = http.get(URL, params=params).ensure_ok()
        try:
            pages = int(json.loads(r.content)["meta"]["total-pages"])
        except (ValueError, KeyError, TypeError) as e:
            raise FetchError(f"unexpected FiscalData response on page {page}: {e!r}") from e
        yield RawFile(f"auctions_query_p{page:03d}.json", r.content, r.url, r.status, r.content_type,
                      params=params)
        page += 1


SPECS = [
    SourceSpec("fiscaldata_auctions", "FiscalData auctions_query, full table", Kind.HISTORY, "cme",
               units=lambda asof, cal: ["auctions_query"], fetch=fetch),
]
