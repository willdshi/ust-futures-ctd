from datetime import date

from ctd.data.inbox import INGESTED, MANUAL_UNIT, ingest

ASOF = date(2026, 10, 16)
UNITS = {"cme_fut": ["ZN", "ZB", "TN", "UB"], "cme_opt": ["ZN", "ZB"], "cme_cf": ["tables"]}


def SOURCES(source, asof):
    return UNITS.get(source)


def drop(inbox, rel, content):
    p = inbox / ASOF.isoformat() / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


def test_unit_drop_copied_byte_for_byte_and_moved(store, tmp_path):
    inbox = tmp_path / "inbox"
    p = drop(inbox, "cme_fut/ZN/zn.json", b"\x00raw bytes\xff")
    [r] = ingest(store, inbox, SOURCES)
    assert (r.source, r.unit, r.name, r.status) == ("cme_fut", "ZN", "zn.json", "stored")
    assert store.read(ASOF, "cme_fut", "ZN", "zn.json") == b"\x00raw bytes\xff"
    meta = store.meta(ASOF, "cme_fut", "ZN", "zn.json")
    assert meta["origin"] == "manual" and meta["url"] is None
    assert not p.exists()
    assert (inbox / INGESTED / ASOF.isoformat() / "cme_fut" / "ZN" / "zn.json").exists()


def test_source_level_drop_goes_to_manual_unit(store, tmp_path):
    inbox = tmp_path / "inbox"
    drop(inbox, "cme_opt/bulletin.pdf", b"%PDF")
    [r] = ingest(store, inbox, SOURCES)
    assert r.unit == MANUAL_UNIT
    assert store.names(ASOF, "cme_opt", MANUAL_UNIT) == ["bulletin.pdf"]


def test_conflict_left_in_inbox(store, tmp_path):
    inbox = tmp_path / "inbox"
    store.write(ASOF, "cme_fut", "ZN", "zn.json", b"original", {"origin": "auto"})
    p = drop(inbox, "cme_fut/ZN/zn.json", b"different")
    [r] = ingest(store, inbox, SOURCES)
    assert r.status.startswith("conflict")
    assert p.exists()
    assert store.read(ASOF, "cme_fut", "ZN", "zn.json") == b"original"


def test_identical_duplicate_is_moved(store, tmp_path):
    inbox = tmp_path / "inbox"
    store.write(ASOF, "cme_fut", "ZN", "zn.json", b"same", {"origin": "auto"})
    p = drop(inbox, "cme_fut/ZN/zn.json", b"same")
    [r] = ingest(store, inbox, SOURCES)
    assert r.status == "duplicate" and not p.exists()


def test_unknown_source_is_a_conflict(store, tmp_path):
    inbox = tmp_path / "inbox"
    p = drop(inbox, "nonsense/file.csv", b"x")
    [r] = ingest(store, inbox, SOURCES)
    assert r.status == "conflict: unknown source" and p.exists()


def test_file_named_after_its_unit(store, tmp_path):
    inbox = tmp_path / "inbox"
    for name in ("ZN.json", "zb_settle.json", "UB.json", "Other.json"):
        drop(inbox, f"cme_fut/{name}", b"{}")
    got = {r.name: r.unit for r in ingest(store, inbox, SOURCES)}
    assert got == {"ZN.json": "ZN", "zb_settle.json": "ZB", "UB.json": "UB", "Other.json": MANUAL_UNIT}


def test_single_unit_source_takes_any_file(store, tmp_path):
    inbox = tmp_path / "inbox"
    drop(inbox, "cme_cf/TCF.xlsx", b"PK")
    [r] = ingest(store, inbox, SOURCES)
    assert r.unit == "tables" and store.names(ASOF, "cme_cf", "tables") == ["TCF.xlsx"]
