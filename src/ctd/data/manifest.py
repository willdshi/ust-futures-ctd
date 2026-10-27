"""Per-date manifest: every expected source and unit, with its collection status.

``raw/<asof>/manifest.json``::

    {"asof": "2026-10-16", "updated_at": "...",
     "sources": {"cme_fut": {"status": "ok", "kind": "dated", "calendar": "cme", "reason": null,
                             "units": {"ZN": {"status": "ok", "origin": "auto", "files": [...],
                                              "attempted_at": "...", "error": null}}}}}

The manifest is the collector's own bookkeeping (not raw data) and is rewritten on every run.

Several processes use one date's manifest (the morning tasks, ``ctd ingest``, the derive gate), so every
access holds ``raw/<asof>/manifest.json.lock``, an operating-system lock released when the process exits
(so never stale): ``load`` for the read only, ``update`` from the read until after the write, so no entry
another process records in between is lost. A lock not free within ``LOCK_TIMEOUT`` raises
``ManifestLocked``. The write goes to a temporary file swapped in whole, so a crash never leaves a
truncated manifest.
"""

import contextlib
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ctd.data.store import RawStore, utc_now

OK = "ok"
MANUAL = "manual"                    # files dropped at source level; unit coverage not verified
NOT_EXPECTED = "not_expected"        # holiday, or the source doesn't publish on this date
MISSING = "missing"                  # not attempted yet
MANUAL_NEEDED = "manual_needed"      # manual-only source (CME) and no manual file yet
FAILED = "failed"                    # fetch attempted and failed; retried on the next run

GAPS = (MISSING, MANUAL_NEEDED, FAILED)
_RANK = {NOT_EXPECTED: 0, OK: 1, MANUAL: 2, MISSING: 3, MANUAL_NEEDED: 4, FAILED: 5}


@dataclass(frozen=True)
class Gap:
    asof: date
    source: str
    unit: str
    status: str
    error: str | None = None

    def __str__(self) -> str:
        msg = f"asof={self.asof} source={self.source} unit={self.unit} status={self.status}"
        return msg + (f" error={self.error}" if self.error else "")


def worst(statuses) -> str:
    return max(statuses, key=_RANK.__getitem__, default=NOT_EXPECTED)


LOCK_TIMEOUT = 60.0  # seconds to wait for another process's lock
LOCK_RETRY = 1.0  # seconds between attempts


class ManifestLocked(TimeoutError):
    """Another process held a date's manifest lock for longer than ``LOCK_TIMEOUT``."""


def _try_lock(f) -> bool:
    f.seek(0)
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(f) -> None:
    f.seek(0)
    if sys.platform == "win32":
        import msvcrt
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def locked(store: RawStore, asof: date):
    """Hold ``asof``'s manifest lock: try every ``LOCK_RETRY`` seconds, up to ``LOCK_TIMEOUT``."""
    p = store.manifest_path(asof).with_name("manifest.json.lock")
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a+b") as f:
        deadline = time.monotonic() + LOCK_TIMEOUT
        while not _try_lock(f):
            if time.monotonic() >= deadline:
                raise ManifestLocked(f"{asof}: manifest locked by another process for over {LOCK_TIMEOUT:.0f}s")
            time.sleep(LOCK_RETRY)
        try:
            yield
        finally:
            _unlock(f)


def _read(store: RawStore, asof: date) -> dict:
    p = store.manifest_path(asof)
    if p.exists():
        return json.loads(p.read_text())
    return {"asof": asof.isoformat(), "updated_at": None, "sources": {}}


def _write(store: RawStore, asof: date, manifest: dict) -> Path:
    p = store.manifest_path(asof)
    manifest["updated_at"] = utc_now()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2))
    os.replace(tmp, p)
    return p


def load(store: RawStore, asof: date) -> dict:
    """``asof``'s manifest (empty if none), read under its lock, released straight after."""
    if not store.asof_dir(asof).is_dir():  # nothing stored for the date: nothing to lock
        return _read(store, asof)
    with locked(store, asof):
        return _read(store, asof)


def update(store: RawStore, asof: date, change: Callable[[dict], None]) -> dict:
    """Read ``asof``'s manifest, apply ``change`` to it and write it, all under its lock; return it."""
    with locked(store, asof):
        manifest = _read(store, asof)
        change(manifest)
        _write(store, asof, manifest)
        return manifest


def save(store: RawStore, asof: date, manifest: dict) -> Path:
    """Write ``manifest`` whole, under the lock (``update`` merges into the stored one instead)."""
    with locked(store, asof):
        return _write(store, asof, manifest)


def gaps(manifest: dict, occasional: frozenset[str] = frozenset()) -> list[Gap]:
    """The manifest's gaps. A source recorded as occasional, or named in ``occasional`` (its schedule now,
    for manifests written while it was still daily), is never a gap."""
    asof = date.fromisoformat(manifest["asof"])
    out = []
    for sid, src in manifest["sources"].items():
        if src.get("schedule") == "occasional" or sid in occasional:  # nice to have: never a gap
            continue
        units = src.get("units") or {}
        if not units and src["status"] in GAPS:
            out.append(Gap(asof, sid, "*", src["status"], src.get("reason")))
        for unit, u in units.items():
            if u["status"] in GAPS:
                out.append(Gap(asof, sid, unit, u["status"], u.get("error")))
    return out
