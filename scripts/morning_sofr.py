"""Store the NY Fed rates under today's as-of date once yesterday's SOFR is published (design §10, phase 1b B7).

    python scripts/morning_sofr.py [--asof 2026-10-27]

Run as a step of ``scripts/morning.py`` (scheduled task ``ctd-morning``, 09:15 on weekdays). A date's SOFR is
published about 8am the next business day and stored under that day's as-of date (docs/decisions.md, Which
data a run uses), but the morning fetch collects only the previous business day. This stores
today's file once the fixing is out, so the previous day's run has its SOFR the same morning; the next
morning's fetch then finds it stored and skips it.

Nothing is stored until the latest fixing is the previous ``sifma`` business day's: a file without it would
still be skipped by the next fetch, holding the date's run back a day. Only ``nyfed_rates`` is fetched, and
the other sources are left out of the manifest rather than recorded as missing (the next morning's fetch adds them).
Exit 1 if the fixing isn't published yet or the fetch fails.
"""

import argparse
import sys
from datetime import date

from ctd import cli
from ctd.data import nyfed, refdata, registry
from ctd.data.fetch import fetch_date
from ctd.data.http import RequestsHttp
from ctd.data.store import RawStore


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--asof", type=date.fromisoformat, default=date.today())
    asof = ap.parse_args().asof
    if not (refdata.calendar("cme").is_business_day(asof) and refdata.calendar("sifma").is_business_day(asof)):
        print(f"{asof}: not a cme and sifma business day; the next morning's fetch handles it")
        return 0
    want = refdata.calendar("sifma").prev_business_day(asof)
    http = RequestsHttp()
    latest = max(nyfed.parse(next(nyfed.fetch(asof, "sofr", http)).content))
    if latest < want:
        print(f"{asof}: latest SOFR published is {latest}, not {want} yet; nothing stored")
        return 1
    store = RawStore(cli.data_root())
    gaps = [g for g in fetch_date(asof, store, http, sources=[registry.SOURCES["nyfed_rates"]], fill_missing=False)
            if g.source == "nyfed_rates"]
    got, rate = nyfed.read_latest(store, want)
    print(f"{asof}: SOFR for {got} = {rate:.4%}" + (f"; {len(gaps)} gap(s)" if gaps else ""))
    return 1 if gaps or got != want else 0


if __name__ == "__main__":
    sys.exit(main())
