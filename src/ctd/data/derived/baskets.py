"""The derived baskets table: every contract month's deliverable notes and bonds and their
conversion factors, rebuilt from the grade rules and security terms (design 2, 4).

    derived/baskets/part.parquet
    derived/baskets/_build.json

One row per contract, contract month (quarterly, March 2016 on) and CUSIP that the month's grade
admits (``reference.grades.eligible``, records in ``contract_grades.toml``), from the fixed-coupon
notes and bonds in the ``securities`` table. The original-term limit applies per tranche, as CME
applies it: a 7-year note later reopened as a 5-year (91282CGQ8 in February 2025) qualifies for ZF
from that auction, measured from that issue date (``security_auctions``). ``cf`` is the 6% formula (``bonds.conversionfactor``)
with the contract's rounding (``cf_round_months``). A basket grows as new issues are auctioned:
``eligible_from`` is the date of the first auction that makes a bond deliverable (usually its
first), and the basket on a date is the rows with ``eligible_from`` before it: CME usually adds a
new issue the morning after the auction, now and then a few days later (late May 2025).

Every build checks the rules against every stored TCF file (CME's own tables, December 2023 on):
on each file's date, each contract month's CUSIPs and CFs against the rows auctioned before that
day. The result is in ``_build.json`` (``tcf_check``); months before December 2023 rest on the
rules alone. Rebuilt whenever the securities, grades, product records or TCF files change.
"""

import csv
import hashlib
import io
from datetime import UTC, date, datetime

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ctd.bonds.conversionfactor import conversion_factor
from ctd.data import refdata
from ctd.data.derived.store import BUILD, PART, DerivedStore, file_ref
from ctd.reference.grades import eligible, grade_for

NAME = "baskets"
VERSION = 1
START = date(2016, 3, 1)  # history starts with the March 2016 contract month (data.md 1)
LATE_DAYS = 7  # CME listing a new issue up to this long after its auction is late, not a disagreement

SCHEMA = pa.schema([
    ("contract", pa.string()), ("month", pa.date32()), ("cusip", pa.string()), ("coupon", pa.float64()),
    ("maturity", pa.date32()), ("original_issue_date", pa.date32()), ("eligible_from", pa.date32()),
    ("remaining_months", pa.int64()), ("cf", pa.float64()),
])


def quarterly_months(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        out.append(d)
        d = date(d.year + (d.month + 3 > 12), (d.month + 2) % 12 + 1, 1)
    return out


def basket_rows(securities: pd.DataFrame, auctions: pd.DataFrame, end: date) -> pd.DataFrame:
    """Rows for every contract and quarterly month from March 2016 to ``end``, from the
    ``securities`` and ``security_auctions`` tables (fixed-coupon notes and bonds; TIPS and FRNs are
    never deliverable). A bond becomes deliverable at its first auction that meets the grade's
    original-term limit, measured from that auction's issue date; one auctioned after the delivery
    month is left out."""
    grades = refdata.grades()
    bonds = securities[securities["type"].isin(["Note", "Bond"]) & ~securities["inflation_protected"]
                       & ~securities["floating_rate"] & securities["coupon"].notna()]
    tranches = {c: list(zip(g["auction_date"], g["issue_date"]))
                for c, g in auctions.sort_values(["cusip", "issue_date"]).groupby("cusip")}
    rows = []
    for product in refdata.cme_products()["treasury"]:
        contract, rounding = product["code"], product["cf_round_months"]
        for month in quarterly_months(START, end):
            grade = grade_for(grades, contract, month)
            month_end = (pd.Timestamp(month) + pd.offsets.MonthEnd(0)).date()
            for b in bonds.itertuples():
                own = tranches.get(b.cusip, [(b.first_auction_date, b.original_issue_date)])
                qualifying = [a for a, issued in own if a <= month_end and eligible(grade, month, b.maturity, issued)]
                if not qualifying:
                    continue
                remaining = (b.maturity.year - month.year) * 12 + b.maturity.month - month.month
                rows.append({"contract": contract, "month": month, "cusip": b.cusip, "coupon": b.coupon,
                             "maturity": b.maturity, "original_issue_date": b.original_issue_date,
                             "eligible_from": qualifying[0], "remaining_months": remaining,
                             "cf": conversion_factor(b.coupon, b.maturity, month, rounding)})
    return pd.DataFrame(rows, columns=SCHEMA.names).sort_values(["contract", "month", "maturity", "cusip"],
                                                                 ignore_index=True)


def tcf_frame(store) -> tuple[pd.DataFrame, list[dict]]:
    """Every stored TCF csv's rows for the six contracts (date, contract, month, cusip, cf), and
    the files read."""
    codes = {p["clearing_code"]: p["code"] for p in refdata.cme_products()["treasury"]}
    rows, refs = [], []
    for d in store.asofs():
        for name in store.names(d, "cme_tcf", "csv"):
            refs.append(file_ref(store, d, "cme_tcf", "csv", name))
            for r in csv.DictReader(io.StringIO(store.read(d, "cme_tcf", "csv", name).decode("latin-1"))):
                if r["PFCode"] in codes:
                    rows.append((d, codes[r["PFCode"]], date(int(r["Period"][:4]), int(r["Period"][4:]), 1),
                                 r["CUSIP"], float(r["Invoice_Conversion_Factor"])))
    return pd.DataFrame(rows, columns=["asof", "contract", "month", "cusip", "cf"]), refs


def tcf_check(baskets: pd.DataFrame, tcf: pd.DataFrame) -> dict:
    """Rules against CME: per contract month, over every TCF date listing it, the CUSIPs CME lists
    that the rules don't have by then, the ones the rules have that CME doesn't, and CF differences.
    A bond the rules have within a week of its auction that CME doesn't list yet is CME being late
    (``cme_late``), not a disagreement."""
    out = {}
    rules = {k: g for k, g in baskets.groupby(["contract", "month"])}
    for (contract, month), cme in tcf.groupby(["contract", "month"]):
        ours = rules.get((contract, month), baskets.iloc[0:0])
        missing, extra, late, cf_differ = set(), set(), set(), set()
        for d, day in cme.groupby("asof"):
            listed = dict(zip(day["cusip"], day["cf"]))
            have = ours[ours["eligible_from"] < d]
            mine = dict(zip(have["cusip"], have["cf"]))
            since = dict(zip(have["cusip"], have["eligible_from"]))
            missing |= {(c, d) for c in listed.keys() - mine.keys()}
            for c in mine.keys() - listed.keys():
                (late if (d - since[c]).days <= LATE_DAYS else extra).add((c, d))
            cf_differ |= {c for c in listed.keys() & mine.keys() if abs(listed[c] - mine[c]) > 1e-9}
        out[f"{contract} {month:%Y-%m}"] = {
            "tcf_dates": int(cme["asof"].nunique()), "cusips": int(cme["cusip"].nunique()),
            "missing_from_rules": sorted({c for c, _ in missing}), "missing_days": len(missing),
            "extra_in_rules": sorted({c for c, _ in extra}), "extra_days": len(extra),
            "cme_late": sorted({c for c, _ in late}), "cme_late_days": len(late),
            "cf_differ": sorted(cf_differ)}
    return out


def _hash(name: str) -> str:
    return hashlib.sha256(refdata._ref_file(name).read_bytes()).hexdigest()


def build(dstore: DerivedStore, store, full: bool = False, code: str | None = None, log=print) -> dict | None:
    """Rebuild the baskets table if its inputs changed. Returns the TCF check summary, or None if
    nothing changed."""
    securities_state = dstore.state("securities")
    if not securities_state:
        return None
    tcf, refs = tcf_frame(store)
    inputs = {"securities": securities_state.get("inputs"), "securities_version": securities_state.get("version"),
              "grades": _hash("contract_grades.toml"), "products": _hash("cme_products.toml"), "tcf": refs}
    state = dstore.state(NAME)
    if not full and state.get("version") == VERSION and state.get("inputs") == inputs:
        return None
    log(f"{NAME}: rebuilding from the rules, checked against {len(refs)} TCF files")
    end = max(tcf["month"]) if len(tcf) else START
    baskets = basket_rows(dstore.read("securities"), dstore.read("security_auctions"), end)
    check = tcf_check(baskets, tcf)
    base = dstore.table_dir(NAME)
    base.mkdir(parents=True, exist_ok=True)
    tmp = base / f".{PART}.tmp"
    pq.write_table(pa.Table.from_pandas(baskets, schema=SCHEMA, preserve_index=False), tmp, compression="zstd")
    tmp.replace(base / PART)
    summary = {"rows": len(baskets), "months": int(baskets[["contract", "month"]].drop_duplicates().shape[0]),
               "checked": len(check),
               "membership_mismatches": sum(1 for c in check.values() if c["missing_from_rules"] or c["extra_in_rules"]),
               "cme_late": sorted({x for c in check.values() for x in c["cme_late"]}),
               "cf_mismatches": sum(len(c["cf_differ"]) for c in check.values())}
    dstore.save_state(NAME, {"table": NAME, "version": VERSION, "inputs": inputs, "summary": summary,
                             "tcf_check": check, "code": code,
                             "built_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")})
    assert (base / BUILD).exists()
    return summary
