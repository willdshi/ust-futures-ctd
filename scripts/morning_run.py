"""Run the light model for the previous business day and build its report pages (roadmap 1f.3).

    python scripts/morning_run.py [--asof 2026-10-28] [--no-notify]

Run as a step of ``scripts/morning.py`` (scheduled task ``ctd-morning``), after ``morning_derive.py``. The
as-of date D is the previous ``cme`` business day, as for the derive. Nothing happens, with exit 0, when
today isn't a ``cme`` business day or D isn't a ``sifma`` one (no TreasuryDirect prices). Otherwise:

1. ``ctd run --asof D``: every contract of the run window (design 7), so the 2026-11-13 roll needs no
   change here, saving each result in the checkout's ``results/``;
2. ``ctd report --asof D --out <output dir>``: the pages in ``$CTD_OUTPUT_DIR``, the ``gh-pages`` worktree
   (``prod_env.ps1``), so ``archive.html`` lists every published date. ``ctd report`` fails if any of D's
   contracts has no saved result, so a partly failed run never builds a page;
3. ``D.html`` copied to ``index.html``.

A failing step stops the rest, raises a desktop alert and exits 1. ``scripts/morning_publish.py`` pushes
the pages.
"""

import argparse
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from ctd import cli
from ctd.data import alert, refdata


def choose_asof(today: date, asof: date | None = None) -> tuple[date | None, str]:
    """(D, "") for the date to run, or (None, why not) when there is nothing to run today."""
    cme, sifma = refdata.calendar("cme"), refdata.calendar("sifma")
    if asof is None:
        if not cme.is_business_day(today):
            return None, f"{today} isn't a cme business day"
        asof = cme.prev_business_day(today)
    if not sifma.is_business_day(asof):
        return None, f"{asof} isn't a bond-market business day (no TreasuryDirect prices)"
    return asof, ""


def run_steps(asof: date, out: Path, py: list[str]) -> str | None:
    """The model run, the report and the ``index.html`` copy; None on success, else what failed."""
    for name, args in (("run", ["run", "--asof", asof.isoformat()]),
                       ("report", ["report", "--asof", asof.isoformat(), "--out", str(out)])):
        print(f"{datetime.now():%Y-%m-%dT%H:%M:%S} ctd {name} {asof}", flush=True)
        code = subprocess.call(py + ["-m", "ctd.cli"] + args)
        if code:
            return f"ctd {name} {asof} exited {code}"
    shutil.copyfile(out / f"{asof.isoformat()}.html", out / "index.html")
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--asof", type=date.fromisoformat)
    ap.add_argument("--no-notify", action="store_true", help="no desktop alert on failure")
    args = ap.parse_args()
    asof, why = choose_asof(date.today(), args.asof)
    if asof is None:
        print(f"{datetime.now():%Y-%m-%dT%H:%M:%S} {why}: nothing to run")
        return 0
    out = cli.output_dir()
    print(f"{datetime.now():%Y-%m-%dT%H:%M:%S} morning run for {asof}: results {cli.results_dir()},"
          f" pages {out}", flush=True)
    problem = run_steps(asof, out, [sys.executable, "-u"])
    if problem:
        print(f"{datetime.now():%Y-%m-%dT%H:%M:%S} {problem}")
        if not args.no_notify:
            alert.notify(f"ctd run failed for {asof}", f"{problem}\nSee data\\morning.log")
        return 1
    print(f"{datetime.now():%Y-%m-%dT%H:%M:%S} {asof}: pages and index.html written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
