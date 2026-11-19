"""Check that today's morning run happened; start it if it didn't (data.md §4, When the PC is asleep or off).

    python scripts/morning_check.py

Run by the scheduled task ``ctd-morning-check`` (``register_morning_tasks.ps1``) 15 minutes after logon or
unlock, and every 30 minutes from 10:30 to 15:00 on weekdays. It reads the record ``scripts/morning.py``
keeps of its last run (``data/morning_status.json``). On a ``cme`` business day from 09:45:

- no run started today: it starts ``ctd-morning`` and raises a desktop alert saying so (once a day);
- today's run failed a step: from 10:30 to 15:00, it starts ``ctd-morning`` again, without an alert (the
  run's own steps alert for what's still missing), at most once every 25 minutes, so each half-hourly
  check can retry but an unlock between them doesn't add one;
- today's run started more than 2 hours ago (the task's time limit) and hasn't finished: an alert.

It raises each alert at most once a day and keeps track of what it has done today in
``data/morning_check.json``. Otherwise it does nothing and prints nothing, so it can run on every unlock.
Starting the task, not ``morning.py`` itself, keeps one run at a time (the task ignores a second start).
"""

import subprocess
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from morning import read_status, status_path, write_status  # noqa: E402

TASK = "ctd-morning"
CHECK_FROM = time(9, 45)  # the run starts at 09:15
RETRY_FROM = time(10, 30)  # late enough for a late Databento or TreasuryDirect file
RETRY_UNTIL = time(15, 1)  # exclusive: the 15:00 check is the last to retry
RETRY_GAP = timedelta(minutes=25)  # under the triggers' 30 minutes, which fire a few seconds late
RUN_LIMIT = timedelta(hours=2)  # the task's ExecutionTimeLimit


def decide(now: datetime, status: dict | None, done: dict, business_day: bool) -> tuple[str | None, str | None]:
    """(``"start"`` or None, alert text or None) for the run record ``status`` and today's ``done``
    (``{"started": bool, "last_start": iso time or None, "alerted": [...]}``: what this check has already
    done today; ``last_start`` may be absent)."""
    if not business_day or now.time() < CHECK_FROM:
        return None, None
    started = datetime.fromisoformat(status["started"]) if status else None
    if started is None or started.date() != now.date():
        last = f"the last run started {started:%Y-%m-%d %H:%M}" if started else "no run is recorded"
        if not done["started"]:
            return "start", f"ctd-morning hadn't run today ({last}); started it now"
        return None, f"ctd-morning still hasn't run today, after this check started it ({last})"
    if status["finished"] is None:
        if now - started > RUN_LIMIT:
            return None, f"ctd-morning started at {started:%H:%M} and hasn't finished; see data\\morning.log"
        return None, None
    if status["failed"] and RETRY_FROM <= now.time() < RETRY_UNTIL:
        last = done.get("last_start")
        if last is None or now - datetime.fromisoformat(last) >= RETRY_GAP:
            return "start", None
    return None, None


def main() -> int:
    from ctd.data import alert, refdata

    now = datetime.now()
    state_path = status_path().with_name("morning_check.json")
    state = read_status(state_path)
    done = state if state and state.get("date") == now.date().isoformat() else \
        {"date": now.date().isoformat(), "started": False, "last_start": None, "alerted": []}
    action, message = decide(now, read_status(status_path()), done, refdata.calendar("cme").is_business_day(now.date()))
    if action == "start":
        r = subprocess.run(["schtasks", "/run", "/tn", TASK], capture_output=True, text=True)
        done["started"] = True
        done["last_start"] = now.isoformat(timespec="seconds")
        print(f"{now:%Y-%m-%dT%H:%M:%S} started {TASK}: exit code {r.returncode} {r.stdout.strip()}", flush=True)
        if r.returncode:
            message = f"ctd-morning-check couldn't start {TASK}: {(r.stderr or r.stdout).strip()}"
    if message and message.split(" (")[0] not in done["alerted"]:
        print(f"{now:%Y-%m-%dT%H:%M:%S} alert: {message}", flush=True)
        alert.notify("ctd-morning", message)
        done["alerted"].append(message.split(" (")[0])
    if action or message:
        write_status(state_path, done)
    return 0


if __name__ == "__main__":
    sys.exit(main())
