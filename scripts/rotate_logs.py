"""Archive the previous months of ``data/morning.log`` (roadmap 1f.11; data.md §4).

    python scripts/rotate_logs.py [--data-root DIR]

Run by the scheduled task ``ctd-morning`` just before ``morning.py``, outside the ``>>`` redirect: PowerShell
holds the log open for the whole run, so the file can only be rewritten while no run is going. The log is a
series of runs, each starting with ``==== YYYY-MM-DDTHH:MM:SS fetch`` (``morning.py``'s step header). Entries
of an earlier month than the current one move to ``data/log_archive/morning-YYYY-MM.log``; the current month
stays in ``morning.log``. A line belongs to the month of the last header above it, so a run that crosses a
month end stays whole in the earlier month's file. Lines before the first header go with the first one.
"""

import argparse
import os
import re
import sys
from datetime import date
from pathlib import Path

HEADER = re.compile(r"^==== (\d{4})-(\d\d)-\d\dT\d\d:\d\d:\d\d ")


def split_months(lines: list[str]) -> dict[str, list[str]]:
    """The lines grouped by the ``YYYY-MM`` of the header they sit under, in file order."""
    months: dict[str, list[str]] = {}
    current: str | None = None
    pending: list[str] = []  # lines before the first header
    for line in lines:
        if m := HEADER.match(line):
            current = f"{m[1]}-{m[2]}"
            months.setdefault(current, []).extend(pending)
            pending = []
        if current is None:
            pending.append(line)
        else:
            months[current].append(line)
    return months


def rotate(log: Path, archive: Path, today: date) -> list[Path]:
    """Move every month before ``today``'s out of ``log`` into ``archive/<stem>-YYYY-MM.log``, appending to a
    month file that already exists. Returns the archive files written. The archive is written before the log
    is trimmed, so an interruption repeats a month rather than losing it."""
    if not log.exists():
        return []
    # errors="surrogateescape": a stray non-UTF-8 byte is carried through unchanged instead of failing.
    lines = log.read_bytes().decode("utf-8", errors="surrogateescape").splitlines(keepends=True)
    months = split_months(lines)
    this_month = f"{today:%Y-%m}"
    old = {m: ls for m, ls in months.items() if m < this_month}
    if not old:
        return []
    archive.mkdir(parents=True, exist_ok=True)
    written = []
    for month, month_lines in sorted(old.items()):
        path = archive / f"{log.stem}-{month}.log"
        existing = path.read_bytes() if path.exists() else b""
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_bytes(existing + "".join(month_lines).encode("utf-8", errors="surrogateescape"))
        os.replace(tmp, path)
        written.append(path)
    kept = "".join(l for m, ls in months.items() if m >= this_month for l in ls)
    tmp = log.with_name(f".{log.name}.tmp")
    tmp.write_bytes(kept.encode("utf-8", errors="surrogateescape"))
    os.replace(tmp, log)
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-root", type=Path, help="the data store (default: ctd's)")
    args = ap.parse_args()
    root = args.data_root
    if root is None:
        from ctd import cli

        root = cli.data_root()
    for path in rotate(root / "morning.log", root / "log_archive", date.today()):
        print(f"archived {path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
