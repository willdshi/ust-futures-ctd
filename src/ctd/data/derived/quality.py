"""The derived options quality table: one row per option chain (date, product, option month) with
checks that let a step skip bad chains without diagnosing them (design 4, data.md 5.12).

    derived/options_quality/product=ZN/year=2026/part.parquet
    derived/options_quality/_build.json

Checks, each a column and, when it fails, a flag:

- ``stale``: the at-the-money straddle (the strike where call and put are closest, within a
  point; none in a sparse chain), scaled by the square root of days to expiry, against the same
  chain on the neighbouring trading days. A
  one-day jump away from neighbours that agree with each other is a stale or wrong settlement
  (TN on Friday 2018-08-24: every final only in CME's Sunday republication, straddle 65% rich); a
  real volatility move persists into the next day and isn't flagged. Not checked within a few days
  of expiry or without both neighbours (so not on a chain's first day; TN on 2018-08-24 was
  OCT18's, and the other checks caught it).
- ``parity``: near the money, call minus put against the futures price minus the strike, median
  over strikes; needs the underlying futures settlement (ZB on 2020-03-20: ZBU0 options imply
  175.56 against a settlement of 173.53).
- ``forward``: the futures price each chain implies near the money (median over strikes within
  two points of its at-the-money strike of strike plus call minus put) against the other chains on
  the same futures that day: more than 4/32 from their median. Needs no futures settlement, so it
  covers the deferred months the futures backfill lacks (three of JUL, AUG, SEP on September
  futures); with two chains on a futures that disagree, both are flagged.
- ``order``: calls rising or puts falling with strike by more than a tick, at two or more strikes.
  Mostly Fridays, and many breaks at once (a flagged TN chain has 10, up to 109).

``issues`` lists the failed checks, comma-separated, and ``ok`` is true when none failed; a check that couldn't be made doesn't fail. Built from the
merged options and futures tables, and rebuilt whenever either changes.
"""

import shutil
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pyarrow as pa

from ctd.data.derived.store import DerivedStore

NAME = "options_quality"
VERSION = 2  # 2: forward check
TICK = {"ZT": 1 / 128, "ZF": 1 / 128}  # option premium ticks: halves of 64ths; 64ths otherwise
TICK_DEFAULT = 1 / 64
STALE_LOG = 0.25  # |log| of the scaled straddle against its neighbours' (about 28%)
NEIGHBOURS_LOG = 0.10  # ... when the neighbours agree with each other within this
MIN_DAYS = 5  # days to expiry below which the straddle check isn't made
MIN_PRICED = 6  # priced options below which a chain has no at-the-money straddle
ATM_GAP = 1.0  # points: |call - put| at the at-the-money strike; wider, the chain has no strike near the money
NEIGHBOUR_GAP = 5  # calendar days: further apart, a date has no neighbour
NEAR_MONEY = 2.0  # points from the futures price for the parity check
PARITY_POINTS = 0.125  # 4/32
ORDER_TICKS = 1  # a break is a step the wrong way of more than this many ticks
ORDER_BREAKS = 2  # breaks in a chain that flag it (one can be a rounding wobble)

SCHEMA = pa.schema([
    ("asof", pa.date32()), ("label", pa.string()), ("expiry", pa.date32()), ("underlying_month", pa.date32()),
    ("priced", pa.int64()), ("atm_strike", pa.float64()), ("straddle", pa.float64()),
    ("straddle_log", pa.float64()), ("neighbours_log", pa.float64()), ("futures", pa.float64()),
    ("parity", pa.float64()), ("implied_forward", pa.float64()), ("forward_gap", pa.float64()),
    ("order_breaks", pa.int64()), ("issues", pa.string()), ("ok", pa.bool_()),
    ("source", pa.string()),
])


def chain_quality(options: pd.DataFrame, futures: pd.DataFrame, product: str) -> pd.DataFrame:
    """Quality rows for one product's option chains, given its options and futures table rows
    (``asof``, ``month`` etc. as ``DerivedStore.read`` returns them)."""
    o = options.copy()
    o["asof"] = pd.to_datetime(o["asof"])
    tick = TICK.get(product, TICK_DEFAULT)
    keys = ["asof", "label"]
    chains = o.groupby(keys).agg(expiry=("expiry", "first"), underlying_month=("underlying_month", "first"),
                                 source=("source", "first"), priced=("settle", "count")).reset_index()

    priced = o[o["settle"].notna()]
    calls = priced[priced["right"] == "C"].set_index(keys + ["strike"])["settle"]
    puts = priced[priced["right"] == "P"].set_index(keys + ["strike"])["settle"]
    pairs = pd.concat([calls.rename("c"), puts.rename("p")], axis=1, join="inner").reset_index()
    pairs["gap"] = (pairs["c"] - pairs["p"]).abs()
    atm = pairs.loc[pairs.groupby(keys)["gap"].idxmin(), keys + ["strike", "c", "p", "gap"]]
    atm = atm[atm["gap"] <= ATM_GAP]
    atm = atm.assign(atm_strike=atm["strike"], straddle=atm["c"] + atm["p"])[keys + ["atm_strike", "straddle"]]
    q = chains.merge(atm, on=keys, how="left")
    q.loc[q["priced"] < MIN_PRICED, ["atm_strike", "straddle"]] = np.nan

    days = (pd.to_datetime(q["expiry"]) - q["asof"]).dt.days
    scaled = np.log(q["straddle"] / np.sqrt(days.clip(lower=1))).where(days >= MIN_DAYS)
    q = q.assign(scaled=scaled).sort_values(["label", "asof"])
    g = q.groupby("label")
    gap_prev = (q["asof"] - g["asof"].shift(1)).dt.days
    gap_next = (g["asof"].shift(-1) - q["asof"]).dt.days
    prev = g["scaled"].shift(1).where(gap_prev <= NEIGHBOUR_GAP)
    nxt = g["scaled"].shift(-1).where(gap_next <= NEIGHBOUR_GAP)
    q["straddle_log"] = q["scaled"] - (prev + nxt) / 2
    q["neighbours_log"] = (prev - nxt).abs()

    f = futures[["asof", "month", "settle"]].rename(columns={"month": "underlying_month", "settle": "futures"})
    f = f.assign(asof=pd.to_datetime(f["asof"]))
    q = q.merge(f, on=["asof", "underlying_month"], how="left")
    near = pairs.merge(q[keys + ["futures"]], on=keys)
    near = near[(near["strike"] - near["futures"]).abs() <= NEAR_MONEY]
    near = near.assign(res=(near["c"] - near["p"]) - (near["futures"] - near["strike"]))
    q = q.merge(near.groupby(keys)["res"].median().rename("parity").reset_index(), on=keys, how="left")

    implied = pairs.merge(q[keys + ["atm_strike"]], on=keys)
    implied = implied[(implied["strike"] - implied["atm_strike"]).abs() <= NEAR_MONEY]
    implied = implied.assign(f=implied["strike"] + implied["c"] - implied["p"]).groupby(keys)["f"].median()
    q = q.merge(implied.rename("implied_forward").reset_index(), on=keys, how="left")
    group = q.groupby(["asof", "underlying_month"])["implied_forward"]
    q["forward_gap"] = (q["implied_forward"] - group.transform("median")).where(group.transform("count") >= 2)

    s = priced.sort_values(keys + ["right", "strike"])
    step = s.groupby(keys + ["right"])["settle"].diff()
    broken = ((s["right"] == "C") & (step > ORDER_TICKS * tick + 1e-9)) | \
             ((s["right"] == "P") & (step < -ORDER_TICKS * tick - 1e-9))
    q = q.merge(s[broken].groupby(keys).size().rename("order_breaks").reset_index(), on=keys, how="left")
    q["order_breaks"] = q["order_breaks"].fillna(0).astype("int64")

    stale = (q["straddle_log"].abs() > STALE_LOG) & (q["neighbours_log"] < NEIGHBOURS_LOG)
    parity = q["parity"].abs() > PARITY_POINTS
    forward = q["forward_gap"].abs() > PARITY_POINTS
    order = q["order_breaks"] >= ORDER_BREAKS
    q["issues"] = [",".join(n for n, hit in (("stale", a), ("parity", b), ("forward", c), ("order", d)) if hit)
                  for a, b, c, d in zip(stale, parity, forward, order)]
    q["ok"] = q["issues"] == ""
    return q.drop(columns=["scaled"]).sort_values(keys).reset_index(drop=True)


def _fingerprint(dstore: DerivedStore) -> dict:
    """What the inputs looked like: the options and futures builds' partitions and times."""
    out = {}
    for table in ("options", "futures"):
        st = dstore.state(table)
        out[table] = {"built_at": st.get("built_at"), "partitions": st.get("partitions", {})}
    return out


def build(dstore: DerivedStore, full: bool = False, code: str | None = None, log=print) -> dict | None:
    """Rebuild the quality table if the options or futures table changed. Returns the summary
    (chains and flags per product), or None if nothing changed."""
    base = dstore.table_dir(NAME)
    state = dstore.state(NAME)
    inputs = _fingerprint(dstore)
    if not full and state.get("version") == VERSION and state.get("inputs") == inputs:
        return None
    log(f"{NAME}: rebuilding from the options and futures tables")
    shutil.rmtree(base, ignore_errors=True)
    options = dstore.read("options")
    futures = dstore.read("futures")
    summary = {}
    for product, o in options.groupby("product"):
        q = chain_quality(o, futures[futures["product"] == product], product)
        for year, part in q.groupby(q["asof"].dt.year):
            part = part.assign(asof=part["asof"].dt.date)
            dstore.write_part(base, product, int(year), pa.Table.from_pandas(part[SCHEMA.names], schema=SCHEMA,
                                                                            preserve_index=False))
        flags = q.loc[~q["ok"], "issues"].str.split(",").explode().value_counts().to_dict()
        summary[product] = {"chains": len(q), "flagged": int((~q["ok"]).sum()), "by_flag": flags,
                            "flagged_dates": int(q.loc[~q["ok"], "asof"].nunique())}
    dstore.save_state(NAME, {"table": NAME, "version": VERSION, "inputs": inputs, "summary": summary,
                             "code": code, "built_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")})
    return summary
