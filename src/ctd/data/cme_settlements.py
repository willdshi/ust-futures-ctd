"""CME settlements: Treasury futures, options on them, and SOFR / fed funds futures.

CME has no free download feed for settlements, so these are manual-only sources: the futures
settlement JSONs are saved from cmegroup.com in a browser (``ctd bookmarklet``) and moved into
the store by ``ctd ingest``. Option settlements arrive daily as the Daily Bulletin (cme_bulletin).
"""

import json
from dataclasses import dataclass
from datetime import date, datetime

from ctd.data import refdata
from ctd.data.sources import Kind, SourceSpec


def _products(group: str) -> dict[str, dict]:
    return {p["code"]: p for p in refdata.cme_products()[group]}


@dataclass(frozen=True)
class FuturesSettle:
    settle: float  # decimal price, per 100 face
    prior_open_interest: int  # CME's page shows the previous business day's open interest (data.md 5.8)
    est_volume: int  # same-day estimate, not the final cleared volume


_EIGHTHS_OF_32 = {"0": 0, "1": 0.125, "2": 0.25, "3": 0.375, "5": 0.5, "6": 0.625, "7": 0.75, "8": 0.875}


def parse_price(s: str) -> float:
    """CME's points-and-32nds: ``"105'17"`` = 105 + 17/32; with a third digit for eighths of a 32nd
    (1, 2, 3, 5, 6, 7, 8 = ⅛, ¼, ⅜, ½, ⅝, ¾, ⅞; ZN uses 0 and 5, ZF also 2 and 7, ZT all),
    ``"105'035"`` = 105 + 3.5/32. A trailing ``A``/``B`` (ask/bid) is dropped."""
    whole, _, frac = s.rstrip("AB").partition("'")
    if not frac:
        return float(whole)
    thirty_seconds = int(frac[:2]) + (_EIGHTHS_OF_32[frac[2]] if len(frac) == 3 else 0)
    return int(whole or 0) + thirty_seconds / 32


def parse_futures(content: bytes, asof: date) -> dict[date, FuturesSettle]:
    """Contract month (first day) -> settlement, from one product's settlement JSON for ``asof``."""
    doc = json.loads(content)
    traded = datetime.strptime(doc["tradeDate"], "%m/%d/%Y").date()
    if traded != asof:
        raise ValueError(f"settlement file is for trade date {traded}, not {asof}")
    out = {}
    for row in doc["settlements"]:
        if row["month"] == "Total" or row["settle"] in ("", "-"):
            continue
        month = datetime.strptime(row["month"], "%b %y").date()
        out[month] = FuturesSettle(parse_price(row["settle"]), int(row["openInterest"].replace(",", "") or 0),
                                   int(row["volume"].replace(",", "") or 0))
    return out


def read_futures(store, asof: date, product: str, source: str = "cme_fut") -> dict[date, FuturesSettle]:
    """``product``'s (``"ZB"``) settlements for ``asof``, as saved by the bookmarklet;
    ``source="cme_stir"`` for SR1, SR3 and ZQ."""
    names = store.names(asof, source, product)
    if not names:
        raise FileNotFoundError(f"no {product} futures settlements stored for {asof}")
    return parse_futures(store.read(asof, source, product, names[0]), asof)


SPECS = [
    SourceSpec("cme_fut", "CME Treasury futures settlements, all six contracts, all months", Kind.DATED,
               "cme", units=lambda asof, cal: list(_products("treasury")), fetch=None),
    # Occasional: per-product option files dropped by hand; options arrive daily as the Daily Bulletin.
    SourceSpec("cme_opt", "CME options on Treasury futures, every expiry and strike", Kind.DATED, "cme",
               units=lambda asof, cal: list(_products("treasury")), fetch=None, schedule="occasional"),
    SourceSpec("cme_stir", "CME 1M SOFR, 3M SOFR and 30-day fed funds futures settlements", Kind.DATED,
               "cme", units=lambda asof, cal: list(_products("stir")), fetch=None),
]
