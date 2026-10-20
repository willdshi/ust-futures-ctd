"""FRED series as full-history CSVs (no API key needed)."""

from collections.abc import Iterator
from datetime import date

from ctd.data.http import FetchError, Http
from ctd.data.sources import Kind, RawFile, SourceSpec

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SERIES = ["DGS1MO", "DGS3MO", "DGS6MO", "DGS1", "DGS2", "DGS3", "DGS5", "DGS7", "DGS10", "DGS20", "DGS30",
          "SOFR", "DFF"]


def fetch(asof: date, unit: str, http: Http) -> Iterator[RawFile]:
    params = {"id": unit}
    r = http.get(URL, params=params).ensure_ok()
    if not r.content.lstrip(b"\xef\xbb\xbf").startswith((b"observation_date", b"DATE")):
        raise FetchError(f"FRED {unit}: response is not the expected CSV")
    yield RawFile(f"{unit}.csv", r.content, r.url, r.status, r.content_type, params=params)


SPECS = [
    SourceSpec("fred", "FRED CMT yields, SOFR, effective fed funds", Kind.HISTORY, "cme",
               units=lambda asof, cal: list(SERIES), fetch=fetch),
]
