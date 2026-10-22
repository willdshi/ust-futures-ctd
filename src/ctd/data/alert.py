"""Desktop alert from the scheduled fetch (``ctd fetch --catch-up --notify``).

Gaps on the newest as-of date of a run aren't alerted. At 19:00 that date's CME files are waiting
for the next morning's bookmarklet click, and late files (the TCF xlsx, posted around 19:00) are
retried by the next run. A gap still open on an earlier date has survived a retry, so it needs
attention, and so does a manual file that ingest refused.
"""

import os
import subprocess
import sys
from collections import defaultdict
from datetime import date

from ctd.data import manifest as mf

# PowerShell's own AppUserModelID, so the toast needs no app registration.
_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
_TOAST = r"""
$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime]
$x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$t = $x.GetElementsByTagName('text')
$null = $t.Item(0).AppendChild($x.CreateTextNode($env:CTD_ALERT_TITLE))
$null = $t.Item(1).AppendChild($x.CreateTextNode($env:CTD_ALERT_BODY))
$n = [Windows.UI.Notifications.ToastNotification]::new($x)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:CTD_ALERT_APP).Show($n)
"""


def actionable(gaps: list[mf.Gap], newest: date) -> list[mf.Gap]:
    """Gaps worth an alert: those on dates before the newest one in the run."""
    return [g for g in gaps if g.asof < newest]


def message(gaps: list[mf.Gap], problems) -> list[str]:
    """One line per kind of problem; empty if there's nothing to report."""
    def dates(ds):
        return ", ".join(d.isoformat() for d in sorted(ds))

    lines = []
    cme = {g.asof for g in gaps if g.status == mf.MANUAL_NEEDED}
    if cme:
        lines.append(f"CME files missing for {dates(cme)}: run the bookmarklet")
    other = defaultdict(set)
    for g in gaps:
        if g.status != mf.MANUAL_NEEDED:
            other[(g.source, g.status)].add(g.asof)
    lines += [f"{source} {status}: {dates(ds)}" for (source, status), ds in sorted(other.items())]
    lines += [f"ingest {r.asof} {r.source}/{r.name}: {r.status}" for r in problems]
    return lines


def notify(title: str, body: str) -> bool:
    """Show a Windows toast. False (and a note on stderr) if it couldn't be shown."""
    if sys.platform != "win32":
        print("alert: desktop notifications are only supported on Windows", file=sys.stderr)
        return False
    env = dict(os.environ, CTD_ALERT_TITLE=title, CTD_ALERT_BODY=body, CTD_ALERT_APP=_APP_ID)
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _TOAST],
                           env=env, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"alert: notification failed: {e}", file=sys.stderr)
        return False
    if r.returncode != 0:
        print(f"alert: notification failed: {r.stderr.strip()}", file=sys.stderr)
        return False
    return True
