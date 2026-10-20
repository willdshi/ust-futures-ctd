"""CME Treasury conversion factor tables (TCF) from CME's public FTP server.

``ftp://ftp.cmegroup.com/settle/TCF/`` holds a CSV (posted early on the date in its name) and an
xlsx (posted that evening) for every business day, back to December 2023. Files are keyed by the
date in CME's file name. The CF formula is the working source (design section 2); these files
validate it and show the day CME changed a basket.
"""

import re
from collections.abc import Iterator
from datetime import date, datetime

from ctd.data.http import FetchError, Http
from ctd.data.sources import Kind, RawFile, SourceSpec

BASE = "ftp://ftp.cmegroup.com/settle/TCF/"
FORMATS = ["csv", "xlsx"]
_NAME = re.compile(r"\bTCF_(\d{8})\.(csv|xlsx)\s*$")


def file_name(asof: date, fmt: str) -> str:
    return f"TCF_{asof:%Y%m%d}.{fmt}"


def fetch(asof: date, unit: str, http: Http) -> Iterator[RawFile]:
    name = file_name(asof, unit)
    r = http.get(BASE + name).ensure_ok()
    if not r.content:
        raise FetchError(f"{name} is empty")
    yield RawFile(name, r.content, r.url, r.status, r.content_type)


def listing(http: Http) -> dict[date, list[str]]:
    """Dated TCF files on the server: as-of date -> formats present."""
    text = http.get(BASE).ensure_ok().content.decode("latin-1")
    out: dict[date, list[str]] = {}
    for line in text.splitlines():
        if m := _NAME.search(line):
            out.setdefault(datetime.strptime(m[1], "%Y%m%d").date(), []).append(m[2])
    return {d: sorted(out[d]) for d in sorted(out)}


SPECS = [
    SourceSpec("cme_tcf", "CME Treasury conversion factor tables (public FTP)", Kind.DATED, "cme",
               units=lambda asof, cal: list(FORMATS), fetch=fetch),
]
