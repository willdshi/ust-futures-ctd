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


def test_run_on_an_empty_store_reports_what_is_missing(tmp_path, capsys):
    assert main(["--data-root", str(tmp_path), "run", "--contract", "ZBZ6", "--asof", "2026-10-21"]) == 1
    assert "no ZB futures settlements stored for 2026-10-21" in capsys.readouterr().err


def test_history_carries_on_past_failed_dates(tmp_path, capsys):
    # 2026-09-07 is Labor Day; the dates before 10-16 read the derived tables, which don't exist here
    assert main(["--data-root", str(tmp_path), "history", "--contract", "ZBZ6", "--from", "2026-09-04",
                 "--to", "2026-09-08"]) == 1
    out = capsys.readouterr().out
    assert out.count("FAILED: no derived futures table") == 2 and "2026-09-07" not in out
    assert "ZBZ6: 0 of 2 business day(s) from 2026-09-04 to 2026-09-08 run and saved, 2 failed" in out


def test_warning_kinds_group_by_wording():
    from ctd.cli import warning_kind

    a = warning_kind("no TreasuryDirect price for 912810UL0: left out of the basket")
    b = warning_kind("no TreasuryDirect price for 91282CRJ2: left out of the basket")
    assert a == b == "no TreasuryDirect price for <cusip>: left out of the basket"
    assert warning_kind("par curve of 2026-10-22 predates 2026-10-23 by 1 day(s)") == \
        "par curve of # predates # by # day(s)"


def test_output_is_utf8_on_a_cp1252_stream(monkeypatch):
    import io
    import sys

    from ctd.cli import utf8_output

    buf = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(buf, encoding="cp1252"))
    utf8_output()
    print("→ ≤ √ σ")
    sys.stdout.flush()
    assert buf.getvalue().decode("utf-8").rstrip() == "→ ≤ √ σ"  # \r\n on Windows


def test_piped_output_is_utf8_without_environment_help():
    # a pipe on Windows defaults to cp1252, which can't encode the report's symbols
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    code = "from ctd.cli import utf8_output; utf8_output(); print('→ ≤ √ σ')"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, env=env, check=True).stdout
    assert out.decode("utf-8").strip() == "→ ≤ √ σ"
