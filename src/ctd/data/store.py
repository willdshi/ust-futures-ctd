"""Raw snapshot store: every file exactly as downloaded, keyed by as-of date.

Layout under the data root::

    raw/<asof>/<source>/<unit>/<name>.gz         gzip of the downloaded bytes (lossless, mtime=0)
    raw/<asof>/<source>/<unit>/<name>.meta.json  url, timestamps, sha256 of the original bytes, origin
    raw/<asof>/manifest.json                     see ctd.data.manifest

A stored file is never overwritten.
"""

import gzip
import hashlib
import json
import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

GZ = ".gz"
META = ".meta.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _create_exclusive(target: Path, payload: bytes) -> bool:
    """Write ``payload`` to ``target`` only if ``target`` doesn't exist. True if written."""
    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_bytes(payload)
    try:
        os.link(tmp, target)  # fails if target exists, on Windows and POSIX alike
        return True
    except FileExistsError:
        return False
    finally:
        tmp.unlink()


class RawStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    def asof_dir(self, asof: date) -> Path:
        return self.root / "raw" / asof.isoformat()

    def unit_dir(self, asof: date, source: str, unit: str) -> Path:
        return self.asof_dir(asof) / source / unit

    def manifest_path(self, asof: date) -> Path:
        return self.asof_dir(asof) / "manifest.json"

    def exists(self, asof: date, source: str, unit: str, name: str) -> bool:
        return (self.unit_dir(asof, source, unit) / (name + GZ)).exists()

    def write(self, asof: date, source: str, unit: str, name: str, content: bytes, meta: dict) -> bool:
        """Store ``content`` and its meta sidecar. Returns False (and changes nothing) if already stored."""
        d = self.unit_dir(asof, source, unit)
        d.mkdir(parents=True, exist_ok=True)
        if not _create_exclusive(d / (name + GZ), gzip.compress(content, mtime=0)):
            return False
        full = {"asof": asof.isoformat(), "source": source, "unit": unit, "name": name,
                "bytes": len(content), "sha256": sha256(content), "stored_at": utc_now(), **meta}
        _create_exclusive(d / (name + META), json.dumps(full, indent=2).encode())
        return True

    def read(self, asof: date, source: str, unit: str, name: str) -> bytes:
        return gzip.decompress((self.unit_dir(asof, source, unit) / (name + GZ)).read_bytes())

    def meta(self, asof: date, source: str, unit: str, name: str) -> dict:
        return json.loads((self.unit_dir(asof, source, unit) / (name + META)).read_text())

    def names(self, asof: date, source: str, unit: str) -> list[str]:
        d = self.unit_dir(asof, source, unit)
        if not d.is_dir():
            return []
        return sorted(p.name[: -len(GZ)] for p in d.iterdir() if p.name.endswith(GZ))

    def units(self, asof: date, source: str) -> list[str]:
        d = self.asof_dir(asof) / source
        return sorted(p.name for p in d.iterdir() if p.is_dir()) if d.is_dir() else []

    def asofs(self) -> list[date]:
        d = self.root / "raw"
        if not d.is_dir():
            return []
        out = []
        for p in d.iterdir():
            try:
                out.append(date.fromisoformat(p.name))
            except ValueError:
                continue
        return sorted(out)
