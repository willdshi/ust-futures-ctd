"""The derived futures table: daily settlement and open interest by contract (design 4).

One row per date, product and contract month, for the six Treasury futures and SR1, SR3 and ZQ.
Sources and precedence:

- ``databento_fut_backfill`` before 2026-10-14: front two contracts only (data.md 5.11), and for SR1
  and ZQ months 3 to 8 too, from ``databento_stir_backfill`` (data.md 5.13). The two pulls are one
  source, since precedence picks one source per date and product; their rows are all labelled
  ``databento_fut_backfill``, and the month tells which pull a row came from;
- ``cme_fut`` (Treasuries) and ``cme_stir`` (SR1, SR3, ZQ) from 2026-10-14: every listed month (data.md 5.8).

``open_interest`` is at the close of ``asof``. CME's page for day D shows the previous business
day's, so a CME row for D takes it from D+1's page and stays null until that page is stored.
Volume isn't kept: CME's page has a same-day estimate, Databento the final cleared volume.
"""

from datetime import date

import pyarrow as pa

from ctd.data import cme_settlements, databento, refdata
from ctd.data.derived.store import Source, Table, file_ref
from ctd.reference.contracts import MONTH_CODES

CME_FROM = date(2026, 10, 14)

SCHEMA = pa.schema([
    ("asof", pa.date32()), ("product", pa.string()), ("month", pa.date32()), ("contract", pa.string()),
    ("settle", pa.float64()), ("open_interest", pa.int64()), ("source", pa.string()),
])


def contract_code(product: str, month: date) -> str:
    return f"{product}{MONTH_CODES[month.month - 1]}{month.year % 10}"


def cme_rows(asof: date, product: str, today: dict[date, cme_settlements.FuturesSettle],
             next_day: dict[date, cme_settlements.FuturesSettle] | None) -> list[dict]:
    """Table rows for ``asof`` from that day's page and, for open interest, the next business day's."""
    return [{"asof": asof, "product": product, "month": m, "contract": contract_code(product, m), "settle": s.settle,
             "open_interest": next_day[m].prior_open_interest if next_day and m in next_day else None}
            for m, s in today.items()]


def _cme_source(source: str) -> Source:
    def files(store, d: date, product: str) -> list[dict]:
        return [file_ref(store, d, source, product, n) for n in store.names(d, source, product)[:1]]

    def units(store) -> dict[str, list[dict]]:
        cal, out = refdata.calendar("cme"), {}
        for d in store.asofs():
            for product in store.units(d, source):
                if today := files(store, d, product):
                    out[f"{d.isoformat()}/{product}"] = today + files(store, cal.add_business_days(d, 1), product)
        return out

    def page(store, d: date, product: str) -> dict[date, cme_settlements.FuturesSettle] | None:
        names = store.names(d, source, product)
        return cme_settlements.parse_futures(store.read(d, source, product, names[0]), d) if names else None

    def read(store, key: str) -> tuple[list[dict], list[str]]:
        iso, product = key.split("/")
        asof = date.fromisoformat(iso)
        nxt = refdata.calendar("cme").add_business_days(asof, 1)
        return cme_rows(asof, product, page(store, asof, product), page(store, nxt, product)), []

    return Source(source, 1, units, read, lambda key: (key.split("/")[1], int(key[:4])))


def _databento_units(store) -> dict[str, list[dict]]:
    out = {}
    for d in store.asofs():
        for source in (databento.FUT, databento.STIR_FUT):
            for product in store.units(d, source):
                out.setdefault(product, []).extend(
                    file_ref(store, d, source, product, n) for n in store.names(d, source, product)
                    if "_statistics_" in n or "_symbology_raw_symbol_" in n)
    return out


DATABENTO = Source(databento.FUT, 2, _databento_units, lambda store, key: databento.read_futures(store, key),
                   lambda key: (key, None))
STIR = ("SR1", "SR3", "ZQ")


def winner(asof: date, product: str) -> str:
    if asof < CME_FROM:
        return databento.FUT
    return "cme_stir" if product in STIR else "cme_fut"


def settlements(dstore, product: str, asof: date) -> tuple[dict[date, float], list[str]]:
    """Contract month -> ``product``'s settlement on ``asof`` from the derived table, and the
    sources the rows came from. Empty when the date has no rows."""
    t = dstore.read("futures", products=[product], start=asof, end=asof)
    return dict(zip(t["month"], t["settle"])), sorted(set(t["source"]))


TABLE = Table("futures", 1, SCHEMA, key=("asof", "product", "month"), compare=("contract", "settle", "open_interest"),
              sources=(DATABENTO, _cme_source("cme_fut"), _cme_source("cme_stir")), winner=winner)
