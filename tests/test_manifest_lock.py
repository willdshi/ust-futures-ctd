"""The per-date manifest lock: concurrent updates lose nothing, reads wait for writes, timeouts raise."""

import subprocess
import sys
import threading
import time
from datetime import date

import pytest

from ctd.data import manifest as mf
from ctd.data.store import RawStore

ASOF = date(2026, 10, 26)
WRITER = """
import sys
from datetime import date
from ctd.data import manifest as mf
from ctd.data.store import RawStore
mf.LOCK_RETRY = 0.01
store, who = RawStore(sys.argv[1]), sys.argv[2]
for k in range(25):
    mf.update(store, date(2026, 10, 26), lambda m: m["sources"].update({f"{who}_{k}": {"status": "ok"}}))
"""


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(mf, "LOCK_RETRY", 0.01)


def test_concurrent_updates_from_several_processes_lose_nothing(store):
    store.asof_dir(ASOF).mkdir(parents=True)
    procs = [subprocess.Popen([sys.executable, "-c", WRITER, str(store.root), f"p{i}"]) for i in range(4)]
    assert [p.wait(timeout=120) for p in procs] == [0, 0, 0, 0]
    assert set(mf.load(store, ASOF)["sources"]) == {f"p{i}_{k}" for i in range(4) for k in range(25)}


def test_a_read_waits_until_the_write_has_finished(store, fast):
    mf.save(store, ASOF, {"asof": ASOF.isoformat(), "sources": {"a": {"status": "ok"}}})
    seen = []

    def slow_change(m):
        reader.start()
        time.sleep(0.3)  # the reader is waiting meanwhile
        m["sources"]["b"] = {"status": "ok"}

    reader = threading.Thread(target=lambda: seen.append(set(mf.load(store, ASOF)["sources"])))
    mf.update(store, ASOF, slow_change)
    reader.join()
    assert seen == [{"a", "b"}]  # not the state before the write


def test_a_lock_held_too_long_raises(store, monkeypatch):
    monkeypatch.setattr(mf, "LOCK_TIMEOUT", 0.2)
    monkeypatch.setattr(mf, "LOCK_RETRY", 0.05)
    mf.save(store, ASOF, {"asof": ASOF.isoformat(), "sources": {}})
    with mf.locked(store, ASOF):
        with pytest.raises(mf.ManifestLocked, match="2026-10-26: manifest locked"):
            mf.load(store, ASOF)
    assert mf.load(store, ASOF)["sources"] == {}  # free again


def test_reading_a_date_with_nothing_stored_creates_nothing(tmp_path):
    store = RawStore(tmp_path / "data")
    assert mf.load(store, ASOF)["sources"] == {} and store.asofs() == []
