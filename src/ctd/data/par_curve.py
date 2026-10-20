"""Treasury daily interest rate CSVs (nominal par yield curve and bill rates), one file per year.

The file for a year holds every date published so far, so a file stored for an as-of date
can contain later dates when fetched after the fact; readers filter by date.

Treasury's real yield curve and long-term rate tables aren't collected: TIPS aren't deliverable,
the long-term composites are averages the model doesn't use, and all of them can be backfilled.
"""

from collections.abc import Iterator
from datetime import date

from ctd.data.http import FetchError, Http
from ctd.data.sources import Kind, RawFile, SourceSpec

URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{year}/all"

# Table type -> first year published.
TYPES = {
    "daily_treasury_yield_curve": 1990,
    "daily_treasury_bill_rates": 2002,
}


def _year_file(table: str, year: int, http: Http) -> RawFile:
    params = {"type": table, "field_tdr_date_value": str(year), "page": "", "_format": "csv"}
    r = http.get(URL.format(year=year), params=params).ensure_ok()
    if not r.content.lstrip(b"\xef\xbb\xbf").startswith(b"Date"):
        raise FetchError(f"{table} {year}: response is not the expected CSV")
    return RawFile(f"{table}_{year}.csv", r.content, r.url, r.status, r.content_type, params=params)


def fetch(asof: date, unit: str, http: Http) -> Iterator[RawFile]:
    yield _year_file(unit, asof.year, http)


def fetch_history(asof: date, unit: str, http: Http) -> Iterator[RawFile]:
    for year in range(TYPES[unit], asof.year):
        yield _year_file(unit, year, http)


SPECS = [
    SourceSpec("par_curve", "Treasury par yield curve and bill rates, current year", Kind.HISTORY, "cme",
               units=lambda asof, cal: list(TYPES), fetch=fetch),
    SourceSpec("par_curve_backfill", "Treasury par yield curve and bill rates, all past years (one-off)", Kind.HISTORY,
               "cme", units=lambda asof, cal: list(TYPES), fetch=fetch_history, schedule="backfill"),
]
