"""Collect the previous business day D and derive it, one step after another (roadmap 1e.5; data.md §4).

    python scripts/morning.py [--no-notify]

Run by the scheduled task ``ctd-morning`` at 09:15 on weekdays (``register_morning_tasks.ps1``); log in
``data/morning.log``. The steps, each its own process, in order:

1. ``ctd fetch --catch-up --notify``: every daily source for D, Databento included (queryable from 09:00),
   and the 4 business days before it still missing;
2. ``scripts/morning_sofr.py``: D's SOFR, published about 08:00, under today's as-of date;
3. ``scripts/morning_derive.py``: ``ctd derive --notify`` if D's data is now stored, otherwise a desktop
   alert naming what's missing.

One task rather than one per step (until 2026-10-28 there were four): steps that start together after a
missed start collide, as two ``ctd fetch`` runs did sweeping the Downloads folder on 2026-10-28, and a
derive waiting on other tasks has to guess when they're done. A step that fails doesn't stop the later
ones (the derive check decides for itself whether D is complete). Exit 1 if any step failed.
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-notify", action="store_true", help="no desktop alert for fetch gaps")
    args = ap.parse_args()
    py = [sys.executable, "-u"]  # unbuffered, so the log shows a step while it runs
    steps = [
        ("fetch", py + ["-m", "ctd.cli", "fetch", "--catch-up"] + ([] if args.no_notify else ["--notify"])),
        ("sofr", py + [str(SCRIPTS / "morning_sofr.py")]),
        ("derive", py + [str(SCRIPTS / "morning_derive.py")]),
    ]
    failed = []
    for name, cmd in steps:
        print(f"==== {datetime.now():%Y-%m-%dT%H:%M:%S} {name}", flush=True)
        code = subprocess.call(cmd)
        if code:
            failed.append(f"{name} (exit {code})")
    print(f"==== {datetime.now():%Y-%m-%dT%H:%M:%S} done" + (f"; failed: {', '.join(failed)}" if failed else ""),
          flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
