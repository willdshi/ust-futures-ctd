"""Run ``ctd derive --notify`` once the previous business day's data is stored (roadmap 1e.5;
data.md §4, When the morning derive runs).

    python scripts/morning_derive.py [--asof 2026-10-26] [--timeout-minutes 0]

Run as the last step of ``scripts/morning.py`` (scheduled task ``ctd-morning``), after the collection steps.
The as-of date D is the previous day that was a business day on both the ``cme`` and ``sifma`` calendars
(``morning_run.choose_asof``). It checks the raw store for what the morning brings
for D:

- ``databento_daily`` ``ok`` in D's manifest (the fetch step);
- ``td_prices`` ``ok`` and not provisional, and ``par_curve`` ``ok`` in D's manifest (the fetch step);
- D's SOFR fixing stored (the SOFR step; only when D and today are both ``sifma`` business days, since it
  is published the next bond-market morning; D is always one now, unless given by ``--asof``).

It derives if all are there. It checks the data, not the steps' exit codes, which can't be trusted
(2026-10-27: a task reported 0 without running its command). Otherwise it doesn't derive: it prints what's
missing, raises a desktop alert and exits 1. Run it, or ``ctd derive``, by hand once the data is in;
``--timeout-minutes`` makes it look again every minute until then. Nothing happens on a day that isn't a
business day on both calendars.
"""

import argparse
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from morning_run import choose_asof  # noqa: E402

from ctd import cli  # noqa: E402
from ctd.data import alert, nyfed, refdata  # noqa: E402
from ctd.data import manifest as mf  # noqa: E402
from ctd.data.store import RawStore  # noqa: E402


def missing(store: RawStore, asof: date, today: date) -> list[str]:
    """What the morning tasks haven't stored for ``asof`` yet (empty when it's all there)."""
    try:
        sources = mf.load(store, asof)["sources"]
    except mf.ManifestLocked:  # being written: look again next minute
        return [f"{asof} manifest locked"]
    out = []
    for source in ("databento_daily", "td_prices", "par_curve"):
        entry = sources.get(source) or {}
        if entry.get("status") != mf.OK:
            out.append(f"{source} {entry.get('status', 'not run')}")
        elif source == "td_prices" and any(u.get("provisional") for u in entry["units"].values()):
            out.append("td_prices provisional (no end-of-day prices yet)")
    sifma = refdata.calendar("sifma")
    if sifma.is_business_day(asof) and sifma.is_business_day(today):
        try:
            got = nyfed.read_latest(store, asof)[0]
        except ValueError:
            got = None
        if got != asof:
            out.append(f"SOFR for {asof} (latest stored: {got})")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--asof", type=date.fromisoformat)
    ap.add_argument("--timeout-minutes", type=int, default=0)
    args = ap.parse_args()
    today = date.today()
    asof, why = choose_asof(today, args.asof)
    if asof is None:
        print(f"{datetime.now():%Y-%m-%dT%H:%M:%S} {why}: nothing new to derive")
        return 0
    store = RawStore(cli.data_root())
    deadline = datetime.now() + timedelta(minutes=args.timeout_minutes)
    print(f"{datetime.now():%Y-%m-%dT%H:%M:%S} morning derive for {asof}: checking its data", flush=True)
    while gaps := missing(store, asof, today):
        if datetime.now() >= deadline:
            print(f"{datetime.now():%Y-%m-%dT%H:%M:%S} still missing after {args.timeout_minutes} minute(s), "
                  f"not deriving: {'; '.join(gaps)}")
            alert.notify(f"ctd derive skipped for {asof}", "; ".join(gaps)[:250] + "\nSee data\\morning.log")
            return 1
        time.sleep(60)
    print(f"{datetime.now():%Y-%m-%dT%H:%M:%S} {asof} is stored; deriving", flush=True)
    code = subprocess.call([sys.executable, "-m", "ctd.cli", "derive", "--notify"])
    print(f"{datetime.now():%Y-%m-%dT%H:%M:%S} morning derive: exit code {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
