"""The morning check (data.md §4): it starts a run that didn't happen, retries a failed one once, and
alerts on a run that never finished."""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from morning import read_status, write_status  # noqa: E402
from morning_check import decide  # noqa: E402

FRESH = {"started": False, "alerted": []}


def run(started: str, finished: str | None = None, failed: list | None = None) -> dict:
    return {"started": started, "finished": finished, "failed": failed or []}


def test_nothing_before_09_45_or_on_a_holiday():
    assert decide(datetime(2026, 10, 29, 9, 40), None, FRESH, True) == (None, None)
    assert decide(datetime(2026, 11, 26, 11, 0), None, FRESH, False) == (None, None)


def test_a_missed_run_is_started_once_with_an_alert():
    yesterday = run("2026-10-28T09:15:02", "2026-10-28T09:33:00")
    action, message = decide(datetime(2026, 10, 29, 10, 5), yesterday, FRESH, True)
    assert action == "start" and "started it now" in message and "2026-10-28 09:15" in message
    action, message = decide(datetime(2026, 10, 29, 10, 30), yesterday, {"started": True, "alerted": []}, True)
    assert action is None and "still hasn't run" in message


def test_a_run_in_progress_is_left_alone_until_past_the_time_limit():
    running = run("2026-10-29T10:06:10")
    assert decide(datetime(2026, 10, 29, 10, 30), running, FRESH, True) == (None, None)
    action, message = decide(datetime(2026, 10, 29, 12, 10), running, FRESH, True)
    assert action is None and "10:06 and hasn't finished" in message


def test_a_failed_run_is_retried_once_from_10_30_without_an_alert():
    failed = run("2026-10-29T09:15:02", "2026-10-29T09:30:00", ["derive (exit 1)"])
    assert decide(datetime(2026, 10, 29, 10, 0), failed, FRESH, True) == (None, None)
    assert decide(datetime(2026, 10, 29, 10, 30), failed, FRESH, True) == ("start", None)
    assert decide(datetime(2026, 10, 29, 11, 0), failed, {"started": True, "alerted": []}, True) == (None, None)
    ok = run("2026-10-29T09:15:02", "2026-10-29T09:33:00")
    assert decide(datetime(2026, 10, 29, 10, 30), ok, FRESH, True) == (None, None)


def test_the_run_record_round_trips(tmp_path):
    path = tmp_path / "data" / "morning_status.json"
    assert read_status(path) is None
    write_status(path, run("2026-10-29T09:15:02"))
    assert read_status(path) == run("2026-10-29T09:15:02")
