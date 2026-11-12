import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from rotate_logs import rotate  # noqa: E402

LOG = (
    "stray line\n"
    "==== 2026-09-30T09:15:00 fetch\nsept fetch\n"
    "==== 2026-09-30T09:20:00 derive\nsept derive\n"
    "==== 2026-10-01T09:15:00 fetch\noct fetch\n"
    "==== 2026-11-02T09:15:00 fetch\nnov fetch\n"
    "==== 2026-11-02T09:30:00 done\n"
)


def test_rotate_moves_earlier_months_and_keeps_current(tmp_path):
    log, archive = tmp_path / "morning.log", tmp_path / "log_archive"
    log.write_text(LOG, encoding="utf-8", newline="")
    written = rotate(log, archive, date(2026, 11, 10))
    assert [p.name for p in written] == ["morning-2026-09.log", "morning-2026-10.log"]
    assert (archive / "morning-2026-09.log").read_text(encoding="utf-8") == (
        "stray line\n==== 2026-09-30T09:15:00 fetch\nsept fetch\n==== 2026-09-30T09:20:00 derive\nsept derive\n")
    assert (archive / "morning-2026-10.log").read_text(encoding="utf-8") == "==== 2026-10-01T09:15:00 fetch\noct fetch\n"
    assert log.read_text(encoding="utf-8") == "==== 2026-11-02T09:15:00 fetch\nnov fetch\n==== 2026-11-02T09:30:00 done\n"


def test_rotate_twice_changes_nothing(tmp_path):
    log, archive = tmp_path / "morning.log", tmp_path / "log_archive"
    log.write_text(LOG, encoding="utf-8", newline="")
    rotate(log, archive, date(2026, 11, 10))
    before = {p.name: p.read_bytes() for p in [log, *archive.iterdir()]}
    assert rotate(log, archive, date(2026, 11, 20)) == []
    assert {p.name: p.read_bytes() for p in [log, *archive.iterdir()]} == before


def test_rotate_appends_to_existing_month_file(tmp_path):
    log, archive = tmp_path / "morning.log", tmp_path / "log_archive"
    archive.mkdir()
    (archive / "morning-2026-10.log").write_text("==== 2026-10-01T09:15:00 fetch\nfirst\n", encoding="utf-8")
    log.write_text("==== 2026-10-02T09:15:00 fetch\nsecond\n", encoding="utf-8")
    rotate(log, archive, date(2026, 11, 1))
    assert (archive / "morning-2026-10.log").read_text(encoding="utf-8").endswith("first\n==== 2026-10-02T09:15:00 fetch\nsecond\n")
    assert log.read_text(encoding="utf-8") == ""


def test_rotate_without_log_does_nothing(tmp_path):
    assert rotate(tmp_path / "morning.log", tmp_path / "log_archive", date(2026, 11, 1)) == []
