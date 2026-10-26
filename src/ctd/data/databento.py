"""Readers for the paid Databento backfills (data.md 5.11, 5.12, 5.13). No fetcher: the files are
pulled once by the scripts in ``scratch/`` and stored under ``raw/2026-10-22/`` (``raw/2026-10-26/``
for the extra SR1 and ZQ months).

Statistics records (``stat_type`` 3 settlement, 6 cleared volume, 9 open interest) carry
``ts_ref``, the trading day they refer to, stamped at midnight UTC: its UTC date is the trading
date (converting to Chicago time first would put every record a day early). Settlement
``stat_flags`` is CME's SettlPriceType bit field; bit 0 set means final. Instrument ids are reused
over the years (one id is a futures contract, later an option or a spread), so an id is mapped to
its contract on each trading date, never once for the whole file.

The files are read as numpy record arrays, in chunks for the option backfill (ZN's statistics are
2.1 GB compressed): ``DBNStore.from_bytes`` keeps the compressed bytes and decompresses as it goes.
"""

import json
import re
from datetime import date

import numpy as np
import pandas as pd
import pyarrow as pa

from ctd.reference.contracts import MONTH_CODES, parse_contract
from ctd.reference.options import LABELS, underlying_month

FUT = "databento_fut_backfill"
STIR_FUT = "databento_stir_backfill"  # SR1 and ZQ months 3 to 8, read with FUT as one source (data.md 5.13)
OPT = "databento_opt_backfill"
SETTLE, VOLUME, OPEN_INTEREST = 3, 6, 9
UNDEF_TS = np.iinfo(np.uint64).max
UNDEF_PRICE = np.iinfo(np.int64).max
START = np.datetime64("2016-01-01")  # history starts in 2016 (data.md 1)
# A cabinet settlement ("CAB" in the bulletin) is $1 a contract: 0.001 points on $100,000 face, 0.0005 on ZT's $200,000.
CABINET = {"ZT": 0.0005}
CABINET_DEFAULT = 0.001
# Before this date every product's cabinets are published as 0.0 (none is in the money against its own chain);
# from it on they are 0.001 (0.0005), and a 0.0 is a placeholder: never any open interest, some deep in the money.
CABINETS_FROM = np.datetime64("2017-05-19")
CHUNK = 2_000_000
DAY_NS = 86_400 * 10**9


def stats_frame(a: np.ndarray) -> pd.DataFrame:
    """Settlement, volume and open interest records from a statistics record array: ``d`` (trading
    date as datetime64[D], NaT without ``ts_ref``), ``instrument_id``, ``ts_event`` (ns), ``stat_type``,
    ``stat_flags``, ``price`` (decimal, NaN if unset), ``quantity``."""
    a = a[np.isin(a["stat_type"], [SETTLE, VOLUME, OPEN_INTEREST])]
    ref = a["ts_ref"]
    d = np.where(ref == UNDEF_TS, np.datetime64("NaT", "D"), (ref // DAY_NS).astype("datetime64[D]"))
    price = np.where(a["price"] == UNDEF_PRICE, np.nan, a["price"] / 1e9)
    return pd.DataFrame({"d": d, "instrument_id": a["instrument_id"], "ts_event": a["ts_event"],
                         "stat_type": a["stat_type"], "stat_flags": a["stat_flags"], "price": price,
                         "quantity": a["quantity"]})


def _last(records: pd.DataFrame, column: str) -> pd.Series:
    """The last published ``column`` per (d, instrument_id)."""
    return records.dropna(subset=["d"]).sort_values("ts_event", kind="stable").groupby(["d", "instrument_id"])[column].last()


def in_window(d: pd.Series, ts_event: pd.Series) -> pd.Series:
    """Whether a settlement for trading date ``d`` was published in its window: from 11:00 CT on
    ``d`` (settlement is about 14:00, 12:00 on early closes) to 11:00 CT on the next weekday."""
    t = pd.to_datetime(ts_event.astype("int64"), utc=True).dt.tz_convert("America/Chicago")
    day = pd.to_datetime(d).dt.tz_localize("America/Chicago")
    nxt = day + pd.to_timedelta(np.where(day.dt.weekday == 4, 3, 1), unit="D")
    return (t >= day + pd.Timedelta(hours=11)) & (t < nxt + pd.Timedelta(hours=11))


def final_settlements(stats: pd.DataFrame) -> tuple[pd.Series, list[str]]:
    """The final settlement per (d, instrument_id).

    The final re-sent on Sunday with no ``ts_ref`` repeats the previous one and is skipped. A date's
    finals normally repeat one price. Where they don't, the one equal to the date's last preliminary
    settlement is kept; failing that, the last one published in the date's window (``in_window``);
    failing that, the last one. The strays are another day's final tagged with this date (the
    previous evening's, e.g. ZT options on 2016-01-06; the next afternoon's, UB futures on
    2020-03-16) or a wrong batch corrected later the same evening (ZT options on 2016-08-22, every
    one at 0.0005 at 18:19 CT, corrected at 22:35). The window alone misses a holiday: ZN options on
    Friday 2017-05-26 have a stray 0.0 on Sunday and the real final on Memorial Day evening, which
    the preliminary picks out. Checked on the full backfills: where there is no preliminary, the
    window's pick is also the last one published (ZN, ZB).
    """
    notes = []
    settles = stats[stats["stat_type"] == SETTLE]
    final = settles[(settles["stat_flags"] & 1) == 1]
    if n := int(final["d"].isna().sum()):
        notes.append(f"{n} final settlement(s) with no ts_ref skipped (Sunday repeats of the previous final)")
    final = final.dropna(subset=["d"]).sort_values("ts_event", kind="stable")
    settle = final.groupby(["d", "instrument_id"])["price"].last()
    count = final.groupby(["d", "instrument_id"])["price"].nunique()
    bad = count[count > 1].index
    if len(bad):
        odd = final.set_index(["d", "instrument_id"]).loc[bad].reset_index()
        seen = odd.groupby(["d", "instrument_id"])["price"].agg(set).reindex(bad)
        prelim = _last(settles[(settles["stat_flags"] & 1) == 0], "price").reindex(bad)
        by_prelim = prelim[[p in prices for p, prices in zip(prelim, seen)]]
        windowed = odd[in_window(odd["d"], odd["ts_event"]).values].groupby(["d", "instrument_id"])["price"].last()
        rest = bad.difference(by_prelim.index)
        windowed = windowed.reindex(rest.intersection(windowed.index))
        settle.loc[windowed.index] = windowed
        settle.loc[by_prelim.index] = by_prelim
        notes.append(f"{len(bad)} date/instrument pair(s) with disagreeing finals: kept the one equal to the "
                     f"preliminary for {len(by_prelim)}, the last in the settlement window for {len(windowed)}, "
                     f"the last published for {len(rest) - len(windowed)} ({int(prelim.reindex(rest).notna().sum())} "
                     f"of these have a preliminary equal to none of their finals)")
    return settle, notes


# --- Futures (data.md 5.11) --------------------------------------------------------------------


def symbol_on(intervals: list[dict], d: date) -> str | None:
    """The symbol an instrument id had on ``d``, from a raw-symbol lookup's ``[{d0, d1, s}, ...]`` (``d1`` exclusive)."""
    iso = d.isoformat()
    for i in intervals:
        if i["d0"] <= iso < i["d1"]:
            return i["s"]
    return None


def futures_rows(stats: pd.DataFrame, symbology: dict, product: str) -> tuple[list[dict], list[str]]:
    """Futures table rows (asof, product, month, contract, settle, open_interest) from one product's
    statistics (``stats_frame``) and its instrument id -> raw symbol lookup.

    Final settlements (``final_settlements``) on and after the lookup's start. A final of 0.0 on an
    id that wasn't a futures contract that day is a placeholder sent before the contract was listed
    (SR1M9 on 2018-11-16, its id still a CAD option) and is skipped; any other final that doesn't map
    to a futures contract is an error. Open interest is the last published for the date (a
    late-evening figure is revised the next morning, and the revision is what CME's page shows),
    and null where none was (the last date: it's published the next morning).
    """
    settle, notes = final_settlements(stats)
    oi = _last(stats[stats["stat_type"] == OPEN_INTEREST], "quantity")
    start = date.fromisoformat(symbology["start_date"])
    pattern = re.compile(rf"{re.escape(product)}[{''.join(MONTH_CODES)}]\d")
    rows, early, placeholders = [], 0, 0
    for (d64, iid), price in settle.items():
        d = pd.Timestamp(d64).date()
        if d < start:
            early += 1
            continue
        sym = symbol_on(symbology["result"].get(str(iid), []), d)
        if sym is None or not pattern.fullmatch(sym):
            if price == 0.0:
                placeholders += 1
                continue
            raise ValueError(f"{product}: instrument {iid} on {d} is {sym!r}, not a {product} futures contract")
        q = oi.get((d64, iid))
        rows.append({"asof": d, "product": product, "month": parse_contract(sym, d)[1], "contract": sym,
                     "settle": float(price), "open_interest": None if q is None else int(q)})
    if early:
        notes.append(f"{early} settlement(s) dated before {start} skipped")
    if placeholders:
        notes.append(f"{placeholders} settlement(s) of 0.0 on instruments not yet a {product} futures contract "
                     f"skipped (placeholders before listing)")
    return rows, notes


def fut_files(store, product: str, source: str = FUT) -> list[tuple[date, str, str]]:
    """(as-of, statistics file, raw-symbol lookup file) of each stored pull for ``product``."""
    out = []
    for asof in store.asofs():
        names = store.names(asof, source, product)
        for stats in (n for n in names if "_statistics_" in n):
            sym = stats.replace("_statistics_", "_symbology_raw_symbol_").replace(".dbn.zst", ".json")
            if sym not in names:
                raise FileNotFoundError(f"{source}/{product}: {stats} has no {sym}")
            out.append((asof, stats, sym))
    return out


def merge_symbology(lookups: list[dict]) -> dict:
    """One raw-symbol lookup from several pulls': each id's date ranges from all of them, starting at
    the earliest start. An id given two symbols over the same dates is an error."""
    result = {}
    for lookup in lookups:
        for iid, intervals in lookup["result"].items():
            result.setdefault(iid, []).extend(intervals)
    for iid, intervals in result.items():
        for i in intervals:
            for j in intervals:
                if i["s"] != j["s"] and i["d0"] < j["d1"] and j["d0"] < i["d1"]:
                    raise ValueError(f"instrument {iid} is both {i['s']!r} and {j['s']!r} from {max(i['d0'], j['d0'])}")
    return {"start_date": min(lookup["start_date"] for lookup in lookups), "result": result}


def read_futures(store, product: str) -> tuple[list[dict], list[str]]:
    """Every stored final settlement and open interest for ``product``, 2016 on: the front two
    contracts (``FUT``), and for SR1 and ZQ months 3 to 8 as well (``STIR_FUT``).

    The pulls' records are joined before finals are picked. A pull holds a record if its id was one
    of the requested symbols when the record was published, not on the trading date it refers to,
    so near a roll one date's records are split between the pulls: SR1Q8's final for Friday
    2018-06-29 was sent on Sunday, after the id moved from ``c.2`` to ``c.1``, and is in ``FUT``
    with its preliminaries in ``STIR_FUT``.
    """
    import databento as db

    frames, lookups = [], []
    for source in (FUT, STIR_FUT):
        files = fut_files(store, product, source)
        if len(files) > 1 or (source == FUT and not files):
            raise ValueError(f"{source}/{product}: expected one stored pull, found {len(files)}")
        for asof, stats, sym in files:
            frames.append(stats_frame(db.DBNStore.from_bytes(store.read(asof, source, product, stats)).to_ndarray()))
            lookups.append(json.loads(store.read(asof, source, product, sym)))
    return futures_rows(pd.concat(frames, ignore_index=True), merge_symbology(lookups), product)


# --- Options (data.md 5.12) --------------------------------------------------------------------

IDENTITY = ["instrument_id", "raw_symbol", "right", "strike", "expiration", "underlying"]
_OPTION_SYMBOL = re.compile(rf"O[A-Z]{{2}}([{''.join(MONTH_CODES)}])(\d) [CP]")
GRACE_NS = 7 * DAY_NS  # a stats record must fall within a week of its definition's last re-send


def definitions_frame(a: np.ndarray) -> pd.DataFrame:
    """Calls and puts from a definition record array, one row per distinct contract an instrument
    id stood for, with the first and last time (ns) its definition was sent. Spreads (instrument
    classes M, T) are dropped: they have no underlying and never settle."""
    a = a[np.isin(a["instrument_class"], [b"C", b"P"])]
    df = pd.DataFrame({"instrument_id": a["instrument_id"], "raw_symbol": a["raw_symbol"],
                       "right": a["instrument_class"], "strike": a["strike_price"],
                       "expiration": a["expiration"], "underlying": a["underlying"],
                       "ts": a["ts_recv"].astype("int64")})
    return df.groupby(IDENTITY, sort=False)["ts"].agg(first="min", last="max").reset_index()


def option_label(raw_symbol: str, expiry: date) -> str:
    """``"DEC26"`` from ``"OZNZ6 C1005"`` and its expiry: the symbol's option month (``Z6``, not the
    futures month), with the decade the one that puts the month just after the expiry."""
    m = _OPTION_SYMBOL.match(raw_symbol)
    if not m:
        raise ValueError(f"not a standard option symbol: {raw_symbol!r}")
    month = MONTH_CODES.index(m[1]) + 1
    year = next(y for y in (expiry.year, expiry.year + 1) if y % 10 == int(m[2]))
    if not 0 < (date(year, month, 1) - expiry).days < 75:
        raise ValueError(f"{raw_symbol}: option month {month}/{year} doesn't follow its expiry {expiry}")
    return f"{LABELS[month - 1]}{year % 100:02d}"


def option_rows(stats: pd.DataFrame, defs: pd.DataFrame, product: str) -> tuple[pa.Table, list[str]]:
    """Options table rows (asof, product, label, expiry, underlying_month, right, strike, settle,
    cabinet, volume, open_interest) from one product's statistics (``stats_frame``) and definitions
    (``definitions_frame``).

    Each settlement is matched to the contract its instrument id stood for on that date: the latest
    definition sent by the end of the trading date (UTC; strikes listed during the day are defined
    after midnight, the next day's re-sends at midnight after), and no more than a week after that contract's
    last re-send (else the id is something else that day, e.g. a spread, and is skipped; so are
    settlements dated the day before a new strike's first definition, and the few dated on a Sunday). Dates with under half the
    usual number of settlements are noted: Databento's feed has gaps (ZT on 2020-02-27: 10 of ~830).

    A cabinet (``CABINET``; 0.0 before ``CABINETS_FROM``) is ``settle`` null and ``cabinet`` true; a
    0.0 from then on is a placeholder and skipped. Volume is cleared volume and open interest the last
    published. Databento publishes neither for an option with no trades and no open interest, the
    ones the bulletin leaves out, so a missing value is 0, except after the last date each was
    published (the next morning's figures for the pull's last date): null. Finals are chosen by
    ``final_settlements``.
    """
    settle, notes = final_settlements(stats)
    s = settle.rename("settle").to_frame()
    s = s.join(_last(stats[stats["stat_type"] == VOLUME], "quantity").rename("volume"))
    s = s.join(_last(stats[stats["stat_type"] == OPEN_INTEREST], "quantity").rename("open_interest")).reset_index()
    if n := int((s["d"] < START).sum()):
        notes.append(f"{n} settlement(s) dated before {START} skipped")
        s = s[s["d"] >= START]
    if n := int((weekend := pd.to_datetime(s["d"]).dt.weekday >= 5).sum()):
        notes.append(f"{n} settlement(s) dated on a weekend skipped")
        s = s[~weekend]
    s["ts"] = s["d"].values.astype("datetime64[ns]").astype("int64") + DAY_NS - 1
    s["instrument_id"] = s["instrument_id"].astype("int64")
    defs = defs.astype({"instrument_id": "int64", "first": "int64", "last": "int64"})
    m = pd.merge_asof(s.sort_values("ts"), defs.sort_values("first"), left_on="ts", right_on="first",
                      by="instrument_id", direction="backward")
    known = m["first"].notna() & (m["ts"] <= m["last"] + GRACE_NS)
    if n := int((~known).sum()):
        notes.append(f"{n} settlement(s) on instruments not defined as calls or puts by that date skipped (mostly "
                     f"0.0 or reference settlements for strikes listed for the next session)")
    m = m[known]
    late = (m["settle"] == 0.0) & (m["d"] >= CABINETS_FROM)
    if n := int(late.sum()):
        notes.append(f"{n} settlement(s) of 0.0 from {CABINETS_FROM} on skipped (placeholders, never with open interest)")
        m = m[~late]
    for col, stat in (("volume", VOLUME), ("open_interest", OPEN_INTEREST)):
        published = stats.loc[stats["stat_type"] == stat, "d"].max()  # published the next morning
        m[col] = m[col].where(m[col].notna() | (m["d"] > published), 0)
    per_day = m.groupby("d").size()
    usual = per_day.rolling(21, center=True, min_periods=5).median()
    thin = per_day[per_day < usual / 2]
    if len(thin):
        notes.append(f"{len(thin)} date(s) with under half the usual number of settlements (gaps in the feed): "
                     + ", ".join(f"{pd.Timestamp(d).date()} ({n} of ~{int(usual[d])})" for d, n in thin.items()))

    contracts = m[["raw_symbol", "expiration", "underlying"]].drop_duplicates()
    expiry = pd.to_datetime(contracts["expiration"].astype("int64"), utc=True).dt.tz_convert("America/Chicago").dt.date
    contracts = contracts.assign(
        expiry=expiry.values,
        label=[option_label(r.decode(), e) for r, e in zip(contracts["raw_symbol"], expiry)],
        underlying_month=[parse_contract(u.decode(), e)[1] for u, e in zip(contracts["underlying"], expiry)])
    off = contracts[[underlying_month(lab) != um for lab, um in zip(contracts["label"], contracts["underlying_month"])]]
    if len(off):
        notes.append(f"{len(off)} contract(s) on another futures month than the rule gives, e.g. "
                     f"{off['raw_symbol'].iloc[0].decode()} on {off['underlying'].iloc[0].decode()}")
    m = m.merge(contracts, on=["raw_symbol", "expiration", "underlying"], how="left")

    m["cabinet"] = ((m["settle"] - CABINET.get(product, CABINET_DEFAULT)).abs() < 1e-9) | (m["settle"] == 0.0)
    m["settle"] = m["settle"].mask(m["cabinet"])
    m = m.sort_values(["d", "label", "right", "strike"], kind="stable")
    table = pa.table({
        "asof": pa.array(m["d"].values.astype("datetime64[D]"), pa.date32()),
        "product": pa.repeat(pa.scalar(product), len(m)),
        "label": pa.array(m["label"].values, pa.string()),
        "expiry": pa.array(m["expiry"].values, pa.date32()),
        "underlying_month": pa.array(m["underlying_month"].values, pa.date32()),
        "right": pa.array([r.decode() for r in m["right"].values], pa.string()),
        "strike": pa.array(m["strike"].values / 1e9, pa.float64()),
        "settle": pa.array(m["settle"].values, pa.float64(), from_pandas=True),
        "cabinet": pa.array(m["cabinet"].values, pa.bool_()),
        "volume": pa.array(m["volume"].values, pa.int64(), from_pandas=True),
        "open_interest": pa.array(m["open_interest"].values, pa.int64(), from_pandas=True),
    })
    return table, notes


_PULL = re.compile(r"(?P<p>[A-Z0-9]+)_(?P<schema>definition|statistics)_(?P<start>[\d-]{10})_(?P<end>[\d-]{10})\.dbn\.zst")


def opt_files(store, product: str) -> tuple[date, str, str]:
    """(as-of, definition file, statistics file) of the pull to read for ``product``: the one whose
    date range contains every other's (ZN also has a small test pull, 2026-10-16 to 10-20)."""
    pulls = {}
    for asof in store.asofs():
        for name in store.names(asof, OPT, product):
            if m := _PULL.fullmatch(name):
                pulls.setdefault((m["start"], m["end"]), {"asof": asof})[m["schema"]] = name
    widest = [k for k in pulls if all(k[0] <= o[0] and o[1] <= k[1] for o in pulls)]
    if len(widest) != 1 or set(pulls[widest[0]]) != {"asof", "definition", "statistics"}:
        raise ValueError(f"{OPT}/{product}: no single complete pull covering the others: {sorted(pulls)}")
    p = pulls[widest[0]]
    return p["asof"], p["definition"], p["statistics"]


def read_options(store, product: str, log=None) -> tuple[pa.Table, list[str]]:
    """Every stored standard option settlement for ``product`` (2016 to 2026-10-19), read in chunks."""
    import databento as db

    asof, definition, statistics = opt_files(store, product)
    parts = [definitions_frame(a) for a in
             db.DBNStore.from_bytes(store.read(asof, OPT, product, definition)).to_ndarray(count=CHUNK)]
    defs = pd.concat(parts).groupby(IDENTITY, sort=False).agg(first=("first", "min"), last=("last", "max")).reset_index()
    if log:
        log(f"{OPT}/{product}: {len(defs)} option contracts defined")
    stats = pd.concat([stats_frame(a) for a in
                       db.DBNStore.from_bytes(store.read(asof, OPT, product, statistics)).to_ndarray(count=CHUNK)])
    if log:
        log(f"{OPT}/{product}: {len(stats)} statistics records")
    return option_rows(stats, defs, product)
