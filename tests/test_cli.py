from datetime import date, datetime

from ctd.cli import default_asof, main


def test_default_asof():
    assert default_asof(datetime(2026, 10, 16, 19), 18) == date(2026, 10, 16)  # Friday evening
    assert default_asof(datetime(2026, 10, 16, 9), 18) == date(2026, 10, 15)  # Friday morning
    assert default_asof(datetime(2026, 10, 18, 9), 18) == date(2026, 10, 16)  # Sunday
    assert default_asof(datetime(2026, 11, 27, 9), 18) == date(2026, 11, 25)  # after Thanksgiving


def test_check_on_empty_store(tmp_path, capsys):
    assert main(["--data-root", str(tmp_path), "check"]) == 0
    assert "0 gap(s)" in capsys.readouterr().out


def test_ingest_refreshes_manifest(tmp_path):
    from ctd.data import manifest as mf
    from ctd.data.store import RawStore

    p = tmp_path / "inbox" / "2026-10-16" / "cme_stir" / "SR3" / "sr3.json"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"{}")
    assert main(["--data-root", str(tmp_path), "ingest"]) == 0
    man = mf.load(RawStore(tmp_path), date(2026, 10, 16))
    assert man["sources"]["cme_stir"]["units"]["SR3"]["status"] == mf.OK
    assert main(["--data-root", str(tmp_path), "check"]) == 1  # other units and sources still missing


def test_model_commands_not_implemented():
    assert main(["run", "--contract", "ZBZ6", "--asof", "2026-10-16"]) == 2
