"""Derived bond tables (design 4): daily prices by CUSIP, and each CUSIP's terms.

    derived/bond_prices/type=NOTE/year=2026/part.parquet   one row per date and CUSIP
    derived/securities/part.parquet                        one row per CUSIP
    derived/securities/_build.json
    derived/security_auctions/part.parquet                 one row per auction

``bond_prices`` is every row of the TreasuryDirect price file (data.md 5.1), every security type,
with all three prices as published: buy, sell and end of day, null where TreasuryDirect gives
0. Which one a step uses is its own choice (the model's is in decisions.md); ``provisional`` marks
a same-evening file without end-of-day prices, replaced once they're in (and then read again).

``securities`` reduces TreasuryDirect's security terms (data.md 5.2), one record per auction, to
one row per CUSIP: the terms of the first auction (original term, dated and issue dates, the
auction date, when a new issue joins a futures basket), the last issue date and the number of
auctions. Built from the latest pull of each type: the file holds
every security ever auctioned, and terms don't change once issued, so a newer pull only adds
CUSIPs. Join prices to terms on ``cusip``. ``security_auctions`` keeps every auction (date, issue
date, term as auctioned): a 7-year note reopened as a 5-year counts as a 5-year issue for ZT and
ZF, so basket eligibility needs each tranche, not just the first.
"""

import csv
import io
import json
import shutil
from datetime import UTC, date, datetime

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ctd.data import td_prices
from ctd.data.derived.store import PART, DerivedStore, Source, Table, file_ref

TYPES = {"MARKET BASED BILL": "BILL", "MARKET BASED NOTE": "NOTE", "MARKET BASED BOND": "BOND",
         "MARKET BASED FRN": "FRN", "TIPS": "TIPS"}

PRICES_SCHEMA = pa.schema([
    ("asof", pa.date32()), ("type", pa.string()), ("cusip", pa.string()), ("coupon", pa.float64()),
    ("maturity", pa.date32()), ("call_date", pa.date32()), ("buy", pa.float64()), ("sell", pa.float64()),
    ("eod", pa.float64()), ("provisional", pa.bool_()), ("source", pa.string()),
])


def _mdy(s: str) -> date | None:
    return datetime.strptime(s, "%m/%d/%Y").date() if s.strip() else None


def price_rows(asof: date, content: bytes) -> tuple[list[dict], list[str]]:
    """Table rows from one TreasuryDirect price file: every row, prices of 0 as null."""
    provisional = td_prices.provisional(content)
    rows, unknown = [], set()
    for r in csv.reader(io.StringIO(content.decode("latin-1"))):
        if len(r) < 8:
            continue
        kind = TYPES.get(r[1])
        if kind is None:
            unknown.add(r[1])
            kind = r[1]
        buy, sell, eod = (float(x or 0) or None for x in r[5:8])
        rows.append({"asof": asof, "type": kind, "cusip": r[0], "coupon": float(r[2] or 0), "maturity": _mdy(r[3]),
                     "call_date": _mdy(r[4]), "buy": buy, "sell": sell, "eod": eod, "provisional": provisional})
    return rows, [f"security types not recognised, kept as printed: {sorted(unknown)}"] if unknown else []


def _price_units(store) -> dict[str, list[dict]]:
    out = {}
    for d in store.asofs():
        name = f"securityprice_{d.isoformat()}.csv"
        if name in store.names(d, "td_prices", "securityprice"):
            out[d.isoformat()] = [file_ref(store, d, "td_prices", "securityprice", name)]
    return out


def _price_read(store, key: str) -> tuple[list[dict], list[str]]:
    asof = date.fromisoformat(key)
    return price_rows(asof, store.read(asof, "td_prices", "securityprice", f"securityprice_{key}.csv"))


PRICES = Table("bond_prices", 1, PRICES_SCHEMA, key=("asof", "type", "cusip"),
               compare=("coupon", "maturity", "buy", "sell", "eod"),
               sources=(Source("td_prices", 1, _price_units, _price_read, lambda key: (None, int(key[:4]))),),
               winner=lambda asof, kind: "td_prices", calendar="sifma", partition="type")


# --- Security terms ----------------------------------------------------------------------------

SECURITIES = "securities"
SECURITIES_VERSION = 3  # 2: first_auction_date; 3: security_auctions alongside
AUCTIONS = "security_auctions"
SECURITY_TYPES = ("Bill", "Note", "Bond", "CMB", "TIPS", "FRN")

SECURITIES_SCHEMA = pa.schema([
    ("cusip", pa.string()), ("type", pa.string()), ("original_term", pa.string()), ("coupon", pa.float64()),
    ("maturity", pa.date32()), ("dated_date", pa.date32()), ("original_issue_date", pa.date32()),
    ("first_auction_date", pa.date32()), ("last_issue_date", pa.date32()), ("auctions", pa.int64()), ("callable", pa.bool_()),
    ("inflation_protected", pa.bool_()), ("floating_rate", pa.bool_()),
])


AUCTIONS_SCHEMA = pa.schema([
    ("cusip", pa.string()), ("type", pa.string()), ("term", pa.string()), ("auction_date", pa.date32()),
    ("issue_date", pa.date32()), ("maturity", pa.date32()), ("reopening", pa.bool_()),
])


def _iso(s: str | None) -> date | None:
    return date.fromisoformat(s[:10]) if s else None


def securities_rows(auctions: list[dict]) -> tuple[list[dict], list[str]]:
    """One row per CUSIP from TreasuryDirect's auction records (all types together). The first
    auction (earliest issue date) gives the original term and dates; coupon and maturity must agree
    across auctions (a CUSIP where they don't is noted and takes the first auction's)."""
    by_cusip: dict[str, list[dict]] = {}
    for a in auctions:
        by_cusip.setdefault(a["cusip"], []).append(a)
    rows, clashes = [], []
    for cusip, recs in sorted(by_cusip.items()):
        recs.sort(key=lambda a: a.get("issueDate") or "")
        first = recs[0]
        if len({(a.get("interestRate") or "", a.get("maturityDate")) for a in recs}) > 1:
            clashes.append(cusip)
        rate = first.get("interestRate") or ""
        rows.append({
            "cusip": cusip, "type": first.get("type") or first.get("securityType"),
            "original_term": first.get("originalSecurityTerm") or first.get("securityTerm"),
            "coupon": float(rate) / 100 if rate else None, "maturity": _iso(first.get("maturityDate")),
            "dated_date": _iso(first.get("datedDate")) or _iso(first.get("issueDate")),
            "original_issue_date": _iso(first.get("issueDate")),
            "first_auction_date": _iso(first.get("competitiveAuctionCloseDate")),
            "last_issue_date": _iso(recs[-1].get("issueDate")),
            "auctions": len(recs), "callable": first.get("callable") == "Yes",
            "inflation_protected": first.get("inflationProtected") == "Yes",
            "floating_rate": first.get("floatingRate") == "Yes"})
    notes = [f"{len(clashes)} CUSIP(s) whose coupon or maturity differs between auctions: {clashes[:5]}"] if clashes else []
    return rows, notes


def auction_rows(auctions: list[dict]) -> list[dict]:
    """One row per auction record, with the term as auctioned (``9-Year 10-Month`` for a reopening)."""
    rows = [{"cusip": a["cusip"], "type": a.get("type") or a.get("securityType"), "term": a.get("securityTerm"),
             "auction_date": _iso(a.get("competitiveAuctionCloseDate")), "issue_date": _iso(a.get("issueDate")),
             "maturity": _iso(a.get("maturityDate")), "reopening": a.get("reopening") == "Yes"} for a in auctions]
    return sorted(rows, key=lambda r: (r["cusip"], r["issue_date"] or date.min))


def _write_flat(base, table: pa.Table) -> None:
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    tmp = base / f".{PART}.tmp"
    pq.write_table(table, tmp, compression="zstd")
    tmp.replace(base / PART)


def _latest_securities(store) -> list[dict]:
    """The latest stored file of each security type."""
    refs = []
    for kind in SECURITY_TYPES:
        name = f"securities_{kind}.json"
        for d in reversed(store.asofs()):
            if name in store.names(d, "td_securities", kind):
                refs.append(file_ref(store, d, "td_securities", kind, name))
                break
    return refs


def build_securities(dstore: DerivedStore, store, full: bool = False, code: str | None = None,
                     log=print) -> dict | None:
    """Rebuild the securities table if a newer security-terms pull is stored. Returns a summary,
    or None if nothing changed."""
    base = dstore.table_dir(SECURITIES)
    state = dstore.state(SECURITIES)
    refs = _latest_securities(store)
    if not refs:
        return None
    if not full and state.get("version") == SECURITIES_VERSION and state.get("inputs") == refs:
        return None
    log(f"{SECURITIES}: rebuilding from {refs[0]['asof']} security terms")
    auctions = [a for r in refs for a in json.loads(store.read(date.fromisoformat(r["asof"]), r["source"],
                                                                  r["unit"], r["name"]))]
    rows, notes = securities_rows(auctions)
    _write_flat(base, pa.Table.from_pylist(rows, schema=SECURITIES_SCHEMA))
    _write_flat(dstore.table_dir(AUCTIONS), pa.Table.from_pylist(auction_rows(auctions), schema=AUCTIONS_SCHEMA))
    summary = {"cusips": len(rows), "auctions": len(auctions),
               "by_type": pd.Series([r["type"] for r in rows]).value_counts().to_dict(), "notes": notes}
    dstore.save_state(SECURITIES, {"table": SECURITIES, "version": SECURITIES_VERSION, "inputs": refs,
                                   "summary": summary, "code": code,
                                   "built_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")})
    return summary
