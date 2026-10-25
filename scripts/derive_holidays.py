"""Derive the 2016-2025 rows of reference/data/holidays.csv from the stored data (data.md 2.5).

CME publishes no structured archive of past holidays, so each calendar is read off what was
actually published:

- ``cme_closed``: a weekday with no CME settlements in any of the 15 Databento backfills (nine
  futures, six option products; under 5% of a usual day's rows counts as none, e.g. 2025-07-04).
  A weekday with no settlements that isn't a scheduled holiday is a gap in the feed, not a
  closure, when Yahoo shows the contracts trading or TreasuryDirect published (Yahoo is missing
  some of the same days); with neither it's listed for review instead of being written.
- ``sifma_closed``: a weekday with no TreasuryDirect prices (FedInvest returned an empty file), or
  with no Treasury par curve (the derived ``par_curve`` table). FedInvest follows the Federal
  Reserve and publishes on every Good Friday; Treasury's par curve is missing exactly on the Good
  Fridays SIFMA recommended a full close (2024, 2025) and present when it recommended an early one
  (2021, 2023). The evidence column says which.

Names come from the US holiday rules; they label the rows, the data decides them. Rows outside
2016-2025 are kept as they are.

    python scripts/derive_holidays.py           # print the report
    python scripts/derive_holidays.py --write   # also rewrite holidays.csv
"""

import argparse
import csv
import gzip
import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"
CSV = REPO / "src" / "ctd" / "reference" / "data" / "holidays.csv"
FIRST, LAST = date(2016, 1, 1), date(2025, 12, 31)
YAHOO = ("ZT", "ZF", "ZN", "TN", "ZB", "UB")
YAHOO_MIN_VOLUME = 100_000  # summed over the six front-month series


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year, month + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _easter(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _observed(d: date) -> date | None:
    """Saturday holidays are observed the Friday before, Sunday ones the Monday after; New Year's
    Day on a Saturday isn't observed (markets don't close on 31 December)."""
    if d.weekday() == 5:
        return None if (d.month, d.day) == (1, 1) else d - timedelta(days=1)
    return d + timedelta(days=1) if d.weekday() == 6 else d


def scheduled(year: int) -> dict[date, tuple[str, bool]]:
    """Weekday holidays by the usual rules: date -> (name, CME closes too). Columbus and Veterans
    Day close the bond market only."""
    out = {}
    for d, name, cme in [
        (date(year, 1, 1), "New Year's Day", True),
        (_nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day", True),
        (_nth_weekday(year, 2, 0, 3), "Presidents' Day", True),
        (_easter(year) - timedelta(days=2), "Good Friday", True),
        (_last_weekday(year, 5, 0), "Memorial Day", True),
        (date(year, 6, 19) if year >= 2022 else None, "Juneteenth", True),
        (date(year, 7, 4), "Independence Day", True),
        (_nth_weekday(year, 9, 0, 1), "Labor Day", True),
        (_nth_weekday(year, 10, 0, 2), "Columbus Day", False),
        (date(year, 11, 11), "Veterans Day", False),
        (_nth_weekday(year, 11, 3, 4), "Thanksgiving Day", True),
        (date(year, 12, 25), "Christmas Day", True),
    ]:
        if d is None:
            continue
        o = _observed(d) if name not in ("Columbus Day", "Veterans Day") or d.weekday() == 6 else d
        if name == "Veterans Day" and d.weekday() == 5:
            o = None  # the bond market stays open on the Friday
        if o is not None and o.weekday() < 5:
            out[o] = (name + (" (observed)" if o != d else ""), cme)
    return out


SPECIAL = {date(2018, 12, 5): "National Day of Mourning (George H. W. Bush)",
           date(2025, 1, 9): "National Day of Mourning (Jimmy Carter)"}


def databento_rows() -> pd.Series:
    """Rows per date across every Databento backfill in the derived staging tables."""
    counts = []
    for table, source in (("futures", "databento_fut_backfill"), ("options", "databento_opt_backfill")):
        for path in (DATA / "derived" / "staging" / table / source).glob("product=*/year=*/part.parquet"):
            counts.append(pq.read_table(path, columns=["asof"]).to_pandas()["asof"].value_counts())
    if not counts:
        raise SystemExit("no Databento staging tables: run `ctd derive` first")
    s = pd.concat(counts).groupby(level=0).sum()
    s.index = pd.to_datetime(s.index).date
    return s


def yahoo_volume() -> pd.Series:
    total = None
    for p in YAHOO:
        path = next((DATA / "raw").glob(f"*/yahoo_fut_backfill/{p}/{p}=F_history_*.json.gz"))
        r = json.loads(gzip.decompress(path.read_bytes()))["chart"]["result"][0]
        days = pd.to_datetime(r["timestamp"], unit="s", utc=True).tz_convert("America/New_York").date
        v = pd.Series(r["indicators"]["quote"][0]["volume"], index=days).fillna(0).groupby(level=0).sum()
        total = v if total is None else total.add(v, fill_value=0)
    return total


def treasurydirect_empty() -> set[date]:
    """Dates whose TreasuryDirect price file was empty (manifest status not_expected)."""
    out = set()
    for m in (DATA / "raw").glob("*/manifest.json"):
        d = date.fromisoformat(m.parent.name)
        if FIRST <= d <= LAST and d.weekday() < 5:
            src = json.loads(m.read_text())["sources"].get("td_prices")
            if src and src["status"] == "not_expected":
                out.add(d)
    return out


def par_curve_dates() -> set[date]:
    """Dates with a Treasury par curve (the derived table; run `ctd derive --table par_curve` first)."""
    out = set()
    for path in (DATA / "derived" / "par_curve").glob("curve=*/year=*/part.parquet"):
        out |= set(pq.read_table(path, columns=["asof"]).to_pandas()["asof"])
    if not out:
        raise SystemExit("no derived par_curve table: run `ctd derive --table par_curve` first")
    return out


def derive() -> tuple[list[dict], list[str], list[str]]:
    rows_db, vol, td_closed = databento_rows(), yahoo_volume(), treasurydirect_empty()
    par = par_curve_dates()
    usual = rows_db.sort_index().rolling(21, center=True, min_periods=5).median()
    sched = {d: v for y in range(FIRST.year, LAST.year + 1) for d, v in scheduled(y).items()}
    out, gaps, review = [], [], []
    d = FIRST
    while d <= LAST:
        if d.weekday() < 5:
            n = int(rows_db.get(d, 0))
            cme_open = n >= 0.05 * float(usual.asof(d) if d in usual.index else usual.median())
            name, cme_rule = sched.get(d, (SPECIAL.get(d), False))
            cme_closed = not cme_open and (cme_rule or d in SPECIAL)
            if not cme_open and not cme_closed:
                (gaps if vol.get(d, 0) >= YAHOO_MIN_VOLUME or d not in td_closed else review).append(
                    f"{d} {d:%a}: no Databento settlements, Yahoo volume {int(vol.get(d, 0)):,}, "
                    f"TreasuryDirect {'empty' if d in td_closed else 'published'}")
            no_par = d not in par
            sifma_closed = d in td_closed or no_par
            if cme_closed or sifma_closed:
                evidence = []
                evidence.append("CME: no settlements in any Databento backfill" if cme_closed else
                                f"CME: settlements ({n:,} Databento rows)")
                if d in td_closed:
                    evidence.append("bond market: no TreasuryDirect prices" + ("" if no_par else ", but a par curve"))
                elif no_par:
                    evidence.append("bond market: no Treasury par curve (TreasuryDirect published)")
                else:
                    evidence.append("bond market: TreasuryDirect prices and a par curve")
                out.append({"date": d.isoformat(), "name": name or "unscheduled closure",
                            "cme_closed": "y" if cme_closed else "n", "sifma_closed": "y" if sifma_closed else "n",
                            "verified": "data", "evidence": "; ".join(evidence)})
            elif name:
                review.append(f"{d} {d:%a}: {name} by the rules, but CME settled ({n:,} rows) and TreasuryDirect published")
        d += timedelta(days=1)
    return out, gaps, review


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="rewrite holidays.csv's 2016-2025 rows")
    args = ap.parse_args()
    rows, gaps, review = derive()
    print(f"{len(rows)} closures 2016-2025: {sum(r['cme_closed'] == 'y' for r in rows)} CME, "
          f"{sum(r['sifma_closed'] == 'y' for r in rows)} bond market")
    for r in rows:
        print(f"  {r['date']} {r['cme_closed']}{r['sifma_closed']} {r['name']:<45} {r['evidence']}")
    print(f"\nGaps (trading days missing from every Databento backfill): {len(gaps)}")
    print("\n".join("  " + g for g in gaps))
    print(f"\nFor review: {len(review)}")
    print("\n".join("  " + g for g in review))
    if args.write:
        with CSV.open(newline="", encoding="utf-8") as f:
            keep = [r for r in csv.DictReader(f) if not FIRST.isoformat() <= r["date"] <= LAST.isoformat()]
        fields = ["date", "name", "cme_closed", "sifma_closed", "verified", "evidence"]
        with CSV.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
            w.writeheader()
            for r in sorted(rows + keep, key=lambda r: r["date"]):
                w.writerow({k: r.get(k, "") for k in fields})
        print(f"\nwrote {CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
