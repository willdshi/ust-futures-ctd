from datetime import date

from ctd.data.inbox import INGESTED, MANUAL_UNIT, ingest

ASOF = date(2026, 10, 16)
UNITS = {"cme_fut": ["ZN", "ZB", "TN", "UB"], "cme_opt": ["ZN", "ZB"], "cme_bulletin": ["Section42"]}


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
    drop(inbox, "cme_bulletin/bulletin.pdf", b"%PDF")
    [r] = ingest(store, inbox, SOURCES)
    assert r.unit == "Section42" and store.names(ASOF, "cme_bulletin", "Section42") == ["bulletin.pdf"]


def test_collect_downloads(tmp_path):
    from ctd.data.inbox import collect_downloads

    dl, inbox = tmp_path / "Downloads", tmp_path / "inbox"
    dl.mkdir()
    (dl / "ctd_2026-10-16_cme_fut_ZN.json").write_bytes(b"zn")
    (dl / "ctd_2026-10-16_cme_fut_ZB (1).json").write_bytes(b"zb")  # browser's repeat-download name
    (dl / "ctd_2026-10-16_cme_bulletin_Section42.pdf").write_bytes(b"%PDF")
    (dl / "ctd_2026-10-16_nonsense_X.json").write_bytes(b"?")
    (dl / "holiday.jpg").write_bytes(b"not ours")
    collect_downloads(dl, inbox, {"cme_fut", "cme_bulletin"})
    day = inbox / "2026-10-16"
    assert (day / "cme_fut" / "ZN.json").read_bytes() == b"zn"
    assert (day / "cme_fut" / "ZB.json").read_bytes() == b"zb"
    assert (day / "cme_bulletin" / "Section42.pdf").exists()
    assert sorted(p.name for p in dl.iterdir()) == ["ctd_2026-10-16_nonsense_X.json", "holiday.jpg"]


def test_collect_downloads_never_overwrites_inbox(tmp_path):
    from ctd.data.inbox import collect_downloads

    dl, inbox = tmp_path / "Downloads", tmp_path / "inbox"
    (inbox / "2026-10-16" / "cme_fut").mkdir(parents=True)
    (inbox / "2026-10-16" / "cme_fut" / "ZN.json").write_bytes(b"first")
    dl.mkdir()
    (dl / "ctd_2026-10-16_cme_fut_ZN.json").write_bytes(b"first")
    (dl / "ctd_2026-10-16_cme_fut_ZN (1).json").write_bytes(b"different")
    collect_downloads(dl, inbox, {"cme_fut"})
    assert [p.name for p in dl.iterdir()] == ["ctd_2026-10-16_cme_fut_ZN (1).json"]  # identical one deleted
    assert (inbox / "2026-10-16" / "cme_fut" / "ZN.json").read_bytes() == b"first"
