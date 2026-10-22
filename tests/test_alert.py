from datetime import date

from ctd.cli import _alert
from ctd.data import alert
from ctd.data import manifest as mf
from ctd.data.inbox import Ingested

D20, D21 = date(2026, 10, 20), date(2026, 10, 21)


def test_newest_date_is_not_actionable():
    gaps = [mf.Gap(D21, "cme_fut", "ZN", mf.MANUAL_NEEDED), mf.Gap(D21, "cme_tcf", "xlsx", mf.FAILED),
            mf.Gap(D20, "cme_fut", "ZN", mf.MANUAL_NEEDED)]
    assert alert.actionable(gaps, D21) == [gaps[2]]


def test_message_groups_by_source():
    gaps = [mf.Gap(D20, "cme_fut", "ZN", mf.MANUAL_NEEDED), mf.Gap(D20, "cme_bulletin", "Section42", mf.MANUAL_NEEDED),
            mf.Gap(D20, "fred", "DGS10", mf.FAILED), mf.Gap(D20, "fred", "DGS30", mf.FAILED)]
    refused = [Ingested(D21, "cme_bulletin", "Section42", "Section42.pdf", "rejected: trade date 2026-10-20")]
    assert alert.message(gaps, refused) == [
        "CME files missing for 2026-10-20: run the bookmarklet",
        "fred failed: 2026-10-20",
        "ingest 2026-10-21 cme_bulletin/Section42.pdf: rejected: trade date 2026-10-20",
    ]
    assert alert.message([], []) == []


def test_alert_notifies_only_when_needed(monkeypatch):
    sent = []
    monkeypatch.setattr(alert, "notify", lambda title, body: sent.append((title, body)) or True)
    _alert([mf.Gap(D21, "cme_fut", "ZN", mf.MANUAL_NEEDED)], [], D21)
    assert sent == []
    _alert([mf.Gap(D20, "fred", "DFF", mf.FAILED)], [], D21)
    assert sent == [("ctd fetch: 1 problem(s)", "fred failed: 2026-10-20\nSee data\\fetch.log")]
