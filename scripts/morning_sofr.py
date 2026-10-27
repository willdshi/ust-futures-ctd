"""Store the NY Fed rates under today's as-of date once yesterday's SOFR is published (design §10, phase 1b B7).

    python scripts/morning_sofr.py [--asof 2026-10-27]

Run by the scheduled task ``ctd-morning-sofr`` (``register_morning_sofr.ps1``) at 10:00 on weekdays. A date's
SOFR is published about 8am the next business day; the evening fetch stores it under that day's as-of date,
so a run for the previous day made before the evening would take the day before's rate and warn
(docs/decisions.md, Which data a run uses). This stores the same file in the morning instead: the evening
fetch then finds it stored and skips it.

Nothing is stored until the latest fixing is the previous ``sifma`` business day's: a file without it would
still be skipped by the evening fetch, holding the date's run back a day. Only ``nyfed_rates`` is fetched, and
the other sources are left out of the manifest rather than recorded as missing (the evening fetch adds them).
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
        print(f"{asof}: not a cme and sifma business day; the evening fetch handles it")
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
