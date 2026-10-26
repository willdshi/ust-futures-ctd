"""Per-date manifest: every expected source and unit, with its collection status.

``raw/<asof>/manifest.json``::

    {"asof": "2026-10-16", "updated_at": "...",
     "sources": {"cme_fut": {"status": "ok", "kind": "dated", "calendar": "cme", "reason": null,
                             "units": {"ZN": {"status": "ok", "origin": "auto", "files": [...],
                                              "attempted_at": "...", "error": null}}}}}

The manifest is the collector's own bookkeeping (not raw data) and is rewritten on every run.
"""

import json
import os
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


def load(store: RawStore, asof: date) -> dict:
    p = store.manifest_path(asof)
    if p.exists():
        return json.loads(p.read_text())
    return {"asof": asof.isoformat(), "updated_at": None, "sources": {}}


def save(store: RawStore, asof: date, manifest: dict) -> Path:
    p = store.manifest_path(asof)
    p.parent.mkdir(parents=True, exist_ok=True)
    manifest["updated_at"] = utc_now()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2))
    os.replace(tmp, p)
    return p


def gaps(manifest: dict) -> list[Gap]:
    asof = date.fromisoformat(manifest["asof"])
    out = []
    for sid, src in manifest["sources"].items():
        if src.get("schedule") == "occasional":  # nice to have: never a gap
            continue
        units = src.get("units") or {}
        if not units and src["status"] in GAPS:
            out.append(Gap(asof, sid, "*", src["status"], src.get("reason")))
        for unit, u in units.items():
            if u["status"] in GAPS:
                out.append(Gap(asof, sid, unit, u["status"], u.get("error")))
    return out
