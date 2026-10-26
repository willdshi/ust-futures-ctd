"""The derived options table: standard (quarterly and serial) option settlements by strike (design 4).

One row per date, product, option month, right and strike. Sources and precedence:

- ``databento_opt_backfill`` before 2026-10-16 (data.md 5.12; ``ctd.data.databento.read_options``);
- ``cme_bulletin`` (Section 42) from 2026-10-16, the first stored bulletin (data.md 5.9).

A cabinet settlement (``CAB`` in the bulletin; 0.001 in Databento, 0.0005 for ZT, 0.0 before
2017-05-19) is ``settle`` null and ``cabinet`` true. No volume or open interest is 0 from both
sources; null only where not yet published (Databento's last date). ``expiry`` is the last trading day as the source
states it (page 1 of the bulletin, which doesn't list TN: TN's come from the reference records,
``option_expiries.toml``; Databento's definitions), and ``underlying_month`` the futures contract
month it's on, the key of the futures table.
"""

from datetime import date

import pyarrow as pa

from ctd.data import cme_bulletin, databento, refdata
from ctd.data.derived.store import Source, Table, file_ref
from ctd.reference.options import underlying_month

BULLETIN_FROM = date(2026, 10, 16)

SCHEMA = pa.schema([
    ("asof", pa.date32()), ("product", pa.string()), ("label", pa.string()), ("expiry", pa.date32()),
    ("underlying_month", pa.date32()), ("right", pa.string()), ("strike", pa.float64()),
    ("settle", pa.float64()), ("cabinet", pa.bool_()), ("volume", pa.int64()), ("open_interest", pa.int64()),
    ("source", pa.string()),
])


def bulletin_rows(asof: date, settles: list[cme_bulletin.OptionSettle],
                  last_trade: dict[tuple[str, str], date]) -> tuple[list[dict], list[str]]:
    """Table rows from one bulletin's settlements and page-1 last trade dates."""
    missing = sorted({f"{o.product} {o.label}" for o in settles if (o.product, o.label) not in last_trade})
    rows = [{"asof": asof, "product": o.product, "label": o.label, "expiry": last_trade.get((o.product, o.label)),
             "underlying_month": underlying_month(o.label), "right": o.right, "strike": o.strike,
             "settle": o.settle, "cabinet": o.cabinet, "volume": o.volume, "open_interest": o.open_interest}
            for o in settles]
    return rows, [f"no last trade date on page 1 for {', '.join(missing)}"] if missing else []


def _bulletin_units(store) -> dict[str, list[dict]]:
    return {d.isoformat(): [file_ref(store, d, "cme_bulletin", "Section42", "Section42.pdf")]
            for d in store.asofs() if "Section42.pdf" in store.names(d, "cme_bulletin", "Section42")}


def _bulletin_read(store, key: str) -> tuple[list[dict], list[str]]:
    asof = date.fromisoformat(key)
    settles, last_trade = cme_bulletin.read(store, asof)
    # Page 1 doesn't list TN; its expiries follow the same rule and are in the reference records.
    for r in refdata.option_expiries():
        if r.product == "TN":
            last_trade.setdefault((r.product, r.label), r.expiry)
    return bulletin_rows(asof, settles, last_trade)


BULLETIN = Source("cme_bulletin", 2, _bulletin_units, _bulletin_read, lambda key: (None, int(key[:4])))


def _databento_units(store) -> dict[str, list[dict]]:
    out = {}
    for d in store.asofs():
        for product in store.units(d, databento.OPT):
            out.setdefault(product, []).extend(
                file_ref(store, d, databento.OPT, product, n) for n in store.names(d, databento.OPT, product))
    return out


DATABENTO = Source(databento.OPT, 3, _databento_units, lambda store, key: databento.read_options(store, key),
                   lambda key: (key, None))


def winner(asof: date, product: str) -> str:
    return "cme_bulletin" if asof >= BULLETIN_FROM else "databento_opt_backfill"


def chain(dstore, product: str, asof: date) -> tuple[list[cme_bulletin.OptionSettle], list[str]]:
    """``product``'s standard option settlements on ``asof`` from the derived table, as the
    bulletin reader gives them (no delta: the table doesn't keep it), and the sources the rows
    came from. Volume or open interest not yet published (null) is an error, not a 0."""
    t = dstore.read("options", products=[product], start=asof, end=asof)
    if t[["volume", "open_interest"]].isna().any(axis=None):
        raise ValueError(f"{product} options on {asof}: volume or open interest not yet published")
    settles = [cme_bulletin.OptionSettle(product, r.label, r.right, r.strike, None if r.cabinet else r.settle, None,
                                         int(r.volume), int(r.open_interest)) for r in t.itertuples()]
    return settles, sorted(set(t["source"]))


TABLE = Table("options", 1, SCHEMA, key=("asof", "product", "label", "right", "strike"),
              compare=("expiry", "underlying_month", "settle", "cabinet", "volume", "open_interest"),
              sources=(DATABENTO, BULLETIN), winner=winner)
