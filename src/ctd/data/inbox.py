"""Manual-drop folder for files that can't be (or weren't) fetched automatically.

Drop files as::

    inbox/<asof>/<source>/<unit>.<ext>    e.g. cme_fut/ZN.json (also ZN_anything.json, any case): unit ZN
    inbox/<asof>/<source>/<unit>/<file>   any file name
    inbox/<asof>/<source>/<file>          a source with one unit (e.g. cme_delivery): that unit

A file matched to a unit counts as that unit collected (status "ok", origin "manual"). Any other
file directly under a source (e.g. a Daily Bulletin PDF covering several products) is stored
under the ``_manual`` unit: kept, but coverage of the source's units is not verified (status "manual").

Ingest copies each file byte-for-byte into the raw store and moves the original to
``inbox/_ingested/``. A file whose name is already stored with different content stays in the
inbox and is reported as a conflict; nothing is overwritten. A file that fails its source's content
check (e.g. a Daily Bulletin printed for another date) also stays in the inbox, reported as rejected.

Files saved by the CME bookmarklet land in the browser's Downloads folder as
``ctd_<asof>_<source>_<name>`` (e.g. ``ctd_2026-10-16_cme_fut_ZN.json``); ``collect_downloads``
moves them into the inbox first.
"""

import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from ctd.data.store import RawStore, sha256

MANUAL_UNIT = "_manual"
INGESTED = "_ingested"
_DOWNLOAD = re.compile(r"^ctd_(\d{4}-\d{2}-\d{2})_(.+)$")
_BROWSER_COPY = re.compile(r" \(\d+\)(?=\.[^.]+$)")  # "ZN (1).json" from a repeated download


@dataclass(frozen=True)
class Ingested:
    asof: date
    source: str
    unit: str
    name: str
    status: str  # "stored", "duplicate" (same bytes already stored), "conflict: ..." or "rejected: ..."

    @property
    def problem(self) -> bool:
        return self.status.startswith(("conflict", "rejected"))


def _move(path: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest = dest.with_name(f"{dest.stem}.{datetime.now():%Y%m%dT%H%M%S}{dest.suffix}")
    shutil.move(path, dest)


def collect_downloads(downloads: Path, inbox: Path, sources: set[str]) -> list[str]:
    """Move ``ctd_<asof>_<source>_<name>`` files from ``downloads`` into ``inbox/<asof>/<source>/<name>``.

    A repeated download of the same bytes is deleted; a different file whose target name is already
    in the inbox stays in ``downloads``. Returns one message per file handled.
    """
    out = []
    if not downloads.is_dir():
        return out
    for path in sorted(p for p in downloads.iterdir() if p.is_file()):
        m = _DOWNLOAD.match(path.name)
        if not m or path.suffix in (".crdownload", ".tmp"):
            continue
        source = max((s for s in sources if m[2].startswith(s + "_")), key=len, default=None)
        if source is None:
            out.append(f"{path.name}: left in downloads (unknown source)")
            continue
        name = _BROWSER_COPY.sub("", m[2][len(source) + 1:])
        dest = inbox / m[1] / source / name
        if dest.exists():
            if dest.read_bytes() == path.read_bytes():
                path.unlink()
                out.append(f"{path.name}: duplicate of {dest.relative_to(inbox)}, deleted")
            else:
                out.append(f"{path.name}: left in downloads ({dest.relative_to(inbox)} already in inbox)")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(path, dest)
        out.append(f"{path.name} -> inbox/{dest.relative_to(inbox).as_posix()}")
    return out


def match_unit(name: str, units: list[str]) -> str:
    """The unit a file dropped directly under its source folder belongs to, else ``MANUAL_UNIT``."""
    if len(units) == 1:
        return units[0]
    stem = name.split(".")[0].upper()
    for unit in units:
        if stem == unit.upper() or stem.startswith(unit.upper() + "_"):
            return unit
    return MANUAL_UNIT


def ingest(store: RawStore, inbox: Path, units_for: Callable[[str, date], list[str] | None],
           validate: Callable[[str, date, str, bytes], str | None] | None = None) -> list[Ingested]:
    """``units_for(source, asof)`` lists a source's units on a date, or None for an unknown source.
    ``validate(source, asof, name, content)`` returns a reason to reject a file, or None."""
    out = []
    if not inbox.is_dir():
        return out
    for asof_dir in sorted(p for p in inbox.iterdir() if p.is_dir() and p.name != INGESTED):
        try:
            asof = date.fromisoformat(asof_dir.name)
        except ValueError:
            continue
        for source_dir in sorted(p for p in asof_dir.iterdir() if p.is_dir()):
            for path in sorted(p for p in source_dir.rglob("*") if p.is_file()):
                rel = path.relative_to(source_dir)
                units = units_for(source_dir.name, asof)
                if len(rel.parts) == 1:
                    unit, name = match_unit(rel.name, units or []), rel.name
                else:
                    unit, name = rel.parts[0], rel.parts[-1]
                if units is None:
                    out.append(Ingested(asof, source_dir.name, unit, name, "conflict: unknown source"))
                    continue
                if len(rel.parts) > 2:
                    out.append(Ingested(asof, source_dir.name, unit, name, "conflict: nested too deep"))
                    continue
                content = path.read_bytes()
                reason = validate(source_dir.name, asof, name, content) if validate else None
                if reason:
                    out.append(Ingested(asof, source_dir.name, unit, name, f"rejected: {reason}"))
                    continue
                mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                meta = {"origin": "manual", "url": None, "original_path": str(path),
                        "original_mtime": mtime.strftime("%Y-%m-%dT%H:%M:%SZ")}
                if store.write(asof, source_dir.name, unit, name, content, meta):
                    status = "stored"
                elif store.meta(asof, source_dir.name, unit, name)["sha256"] == sha256(content):
                    status = "duplicate"
                else:
                    out.append(Ingested(asof, source_dir.name, unit, name,
                                        "conflict: a different file with this name is already stored"))
                    continue
                _move(path, inbox / INGESTED / asof_dir.name / source_dir.name / rel)
                out.append(Ingested(asof, source_dir.name, unit, name, status))
    return out
