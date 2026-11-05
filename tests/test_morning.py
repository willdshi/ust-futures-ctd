"""The morning task's one-line summary of each run (data.md §4)."""

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from morning import summary_line  # noqa: E402


def test_a_good_run():
    line = summary_line(datetime(2026, 11, 5, 9, 15, 7), datetime(2026, 11, 5, 9, 21, 53), date(2026, 11, 4), [],
                        False)
    assert line == "2026-11-05T09:15  D=2026-11-04  ok       6m46s"


def test_a_failed_rerun_lists_its_steps():
    line = summary_line(datetime(2026, 11, 6, 10, 30), datetime(2026, 11, 6, 10, 33, 5), date(2026, 11, 5),
                        ["derive (exit 1)", "run (skipped)", "publish (skipped)"], True)
    assert line == ("2026-11-06T10:30  D=2026-11-05  FAILED   3m05s  (rerun)  "
                    "derive (exit 1), run (skipped), publish (skipped)")


def test_no_date_to_run_lines_up_with_the_rest():
    line = summary_line(datetime(2026, 11, 11, 9, 15), datetime(2026, 11, 11, 9, 17), None, [], False)
    assert line == "2026-11-11T09:15  D=-           ok       2m00s"
