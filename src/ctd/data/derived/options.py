"""The derived options table: standard (quarterly and serial) option settlements by strike (design 4).

One row per date, product, option month, right and strike. Sources and precedence:

- ``databento_opt_backfill`` before 2026-10-16 (data.md 5.12; ``ctd.data.databento.read_options``);
- ``cme_bulletin`` (Section 42) from 2026-10-16, the first stored bulletin (data.md 5.9);
- ``databento_daily`` from 2026-10-26, the daily pull (data.md 5.14;
  ``ctd.data.databento.read_daily_options``). The bulletin becomes a cross-check (``overlap``), stored
  on the days the bookmarklet is clicked. Like the backfill, it also settles strikes the bulletin
  leaves out. Open interest is the evening's first figure until the next date's file brings the revision.

A cabinet settlement (``CAB`` in the bulletin; 0.001 in Databento, 0.0005 for ZT, 0.0 before
2017-05-19) is ``settle`` null and ``cabinet`` true. No volume or open interest is 0 from both
sources; null only where not yet published (Databento's last date). ``expiry`` is the last trading day as the source
states it (page 1 of the bulletin, which doesn't list TN: TN's come from the CBOT rule,
``refdata.option_expiry``; Databento's definitions), and ``underlying_month`` the futures contract
month it's on, the key of the futures table. ``expiry_disagreements`` checks every option month's
expiry against the rule (design section 2).
"""

from datetime import date, timedelta

import pyarrow as pa
import pyarrow.dataset as ds

from ctd.data import cme_bulletin, databento, databento_daily, refdata
from ctd.data.derived.store import Source, Table, file_ref, partitioning
from ctd.reference.options import option_month, underlying_month

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
    # Page 1 doesn't list TN; its expiries follow the same rule.
    for label in {o.label for o in settles if o.product == "TN"}:
        last_trade.setdefault(("TN", label), refdata.option_expiry("TN", label).expiry)
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


def _daily_units(store) -> dict[str, list[dict]]:
    """Per date and option unit: the date's statistics and lookup, every definitions file of the unit up
    to the date (a day's holds only new strikes), and the next business day's statistics once stored."""
    cal, out, defs = refdata.calendar("cme"), {}, {}
    for d in sorted(store.asofs()):
        for unit in store.units(d, databento.DAILY):
            if unit not in databento_daily.OPT_UNITS:
                continue
            names = store.names(d, databento.DAILY, unit)
            defs.setdefault(unit, []).extend(file_ref(store, d, databento.DAILY, unit, n)
                                             for n in names if "_definition_" in n)
            nxt = cal.add_business_days(d, 1)
            out[f"{d.isoformat()}/{unit}"] = (
                [file_ref(store, d, databento.DAILY, unit, n) for n in names if "_definition_" not in n]
                + list(defs[unit])
                + [file_ref(store, nxt, databento.DAILY, unit, n) for n in store.names(nxt, databento.DAILY, unit)
                   if "_statistics_" in n])
    return out


def _daily_read(store, key: str) -> tuple[pa.Table, list[str]]:
    iso, unit = key.split("/")
    asof = date.fromisoformat(iso)
    dates = sorted(d for d in store.asofs() if d <= asof and store.names(d, databento.DAILY, unit))
    return databento.read_daily_options(store, asof, unit, dates)


DAILY = Source(databento.DAILY, 1, _daily_units, _daily_read, lambda key: (key.split("/")[1][1:], int(key[:4])))


def winner(asof: date, product: str) -> str:
    if asof >= databento_daily.FIRST_DATE:
        return databento.DAILY
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


def expiries(dstore) -> list[tuple[str, str, date]]:
    """Every (product, option month, expiry) in the options table, as its sources state the expiry."""
    t = ds.dataset(dstore.table_dir("options"), format="parquet", partitioning=partitioning()).to_table(
        columns=["product", "label", "expiry"]).group_by(["product", "label", "expiry"]).aggregate([])
    return sorted(zip(*(t[c].to_pylist() for c in ("product", "label", "expiry"))))


def expiry_disagreements(rows: list[tuple[str, str, date]]) -> tuple[list[str], list[str]]:
    """Option months whose stated expiry isn't ``refdata.option_expiry`` (the rule, or an exception
    record), and those not checked because the holiday list doesn't reach them yet."""
    wrong, beyond = [], []
    for product, label, expiry in rows:
        if expiry is None:
            continue
        if option_month(label) - timedelta(days=1) > refdata.holidays_through():
            beyond.append(f"{product} {label}")
        elif (rule := refdata.option_expiry(product, label).expiry) != expiry:
            wrong.append(f"{product} {label}: CME {expiry}, rule {rule}")
    return wrong, beyond


TABLE = Table("options", 1, SCHEMA, key=("asof", "product", "label", "right", "strike"),
              compare=("expiry", "underlying_month", "settle", "cabinet", "volume", "open_interest"),
              sources=(DATABENTO, BULLETIN, DAILY), winner=winner)
