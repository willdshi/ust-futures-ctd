"""The daily Databento pull: its window, readiness, completeness and new-definitions rules (offline)."""

import json
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from ctd.data import databento_daily as dd
from ctd.data import manifest as mf
from ctd.data import registry
from ctd.data.databento import OPEN_INTEREST, SETTLE, UNDEF_PRICE, UNDEF_TS, stats_frame
from ctd.data.fetch import fetch_date

MON = date(2026, 10, 26)
STATS = np.dtype([("ts_event", "u8"), ("instrument_id", "u4"), ("ts_ref", "u8"), ("stat_type", "u2"),
                  ("stat_flags", "u1"), ("price", "i8"), ("quantity", "i8")])
DEFS = np.dtype([("instrument_id", "u4"), ("raw_symbol", "S22")])


def ns(ts: str) -> int:
    return pd.Timestamp(ts).value


def records(*rows) -> np.ndarray:
    """(ts_event, instrument_id, ts_ref, stat_type, stat_flags, price, quantity) as a statistics record array."""
    return np.array([(ns(t), iid, UNDEF_TS if ref is None else ns(ref), st, fl,
                      UNDEF_PRICE if px is None else round(px * 1e9), q) for t, iid, ref, st, fl, px, q in rows],
                    dtype=STATS)


def full_day(ids, d="2026-10-26"):
    """Each id: a preliminary and a final for ``d`` and its first open interest figure that evening."""
    out = []
    for iid in ids:
        out += [(f"{d}T19:00", iid, d, SETTLE, 2, 112.5, 0), (f"{d}T23:15", iid, d, SETTLE, 3, 112.5, 0),
                (f"{d}T01:30", iid, d, OPEN_INTEREST, 0, None, 1000)]
    return records(*out)


def test_window_is_midnight_to_midnight_chicago_to_the_next_business_day():
    assert dd.window(MON) == (datetime(2026, 10, 26, 5, tzinfo=UTC), datetime(2026, 10, 27, 5, tzinfo=UTC))
    # Friday before the clocks change runs to Monday, catching the Sunday finals
    assert dd.window(date(2026, 10, 30)) == (datetime(2026, 10, 30, 5, tzinfo=UTC), datetime(2026, 11, 2, 6, tzinfo=UTC))
    # The day before Thanksgiving runs to Friday
    assert dd.window(date(2026, 11, 25))[1] == datetime(2026, 11, 27, 6, tzinfo=UTC)


def test_futures_need_a_final_and_open_interest_on_every_contract():
    assert dd.futures_complete(stats_frame(full_day([1, 2])), MON, 2) is None
    assert dd.futures_complete(stats_frame(full_day([1, 2])[:-1]), MON, 2) == \
        "2 of 2 contracts with a final settlement, 1 with open interest"
    # the previous date's records don't count for this one
    assert dd.futures_complete(stats_frame(full_day([1], d="2026-10-23")), MON, 1) is not None


def test_options_need_finals():
    assert dd.options_complete(stats_frame(full_day([5, 6])), MON) is None
    assert dd.options_complete(stats_frame(full_day([5])[:1]), MON) == "no final settlements"


def test_new_options_are_unseen_calls_and_puts():
    lookup = {"result": {"10": [{"d0": "2026-10-26", "d1": "2026-10-27", "s": "OZNZ6 C1120"}],
                         "11": [{"d0": "2026-10-26", "d1": "2026-10-27", "s": "OZNZ6 P1100"}],
                         "12": [{"d0": "2026-10-26", "d1": "2026-10-27", "s": "UD:1V: VT 1026956853"}],
                         "13": [{"d0": "2026-10-26", "d1": "2026-10-27", "s": "OZNF7 C1130"}]}}
    known = {(10, "OZNZ6 C1120"), (11, "OZNZ6 P1095")}  # id 11 reused for another strike
    assert dd.new_options(lookup, MON, known) == [11, 13]  # the spread is never requested


class FakeClient:
    """Databento's historical client, as far as the fetcher uses it: requests recorded, files served by schema."""

    def __init__(self):
        self.available, self.condition, self.listed, self.calls = "2026-10-27T13:10:00Z", "available", None, []
        self.content = {"statistics": b"stats", "definition": b"defs"}
        self.metadata, self.timeseries, self.symbology = self, self, self

    def get_dataset_range(self, dataset):
        return {"start": "2010-06-06T00:00:00Z", "end": self.available}

    def get_dataset_condition(self, dataset, start_date, end_date):
        days = [d for d in pd.date_range(start_date, end_date).date
                if self.listed is None or d.isoformat() in self.listed]
        return [{"date": d.isoformat(), "condition": self.condition, "last_modified_date": None} for d in days]

    def get_cost(self, **kw):
        return 0.01

    def get_range(self, path, **kw):
        self.calls.append(kw)
        path.write_bytes(self.content[kw["schema"]])

    def resolve(self, **kw):
        sym = lambda i: f"OZNZ6 C{1100 + i}" if i > 100 else "ZNZ6"  # noqa: E731
        return {"result": {str(i): [{"d0": kw["start_date"], "d1": kw["end_date"], "s": sym(i)}] for i in kw["symbols"]},
                "start_date": kw["start_date"]}


@pytest.fixture
def client(monkeypatch, store):
    """A fake client; files are keys into ``arrays``, read back as record arrays. Options are ids 101 to 103."""
    full = full_day([*range(1, 8), 101, 102, 103])  # seven contracts: enough for SR1
    not_yet = full[~((full["stat_type"] == OPEN_INTEREST) | ((full["stat_flags"] & 1) == 1))]
    arrays = {b"stats": full, b"partial": not_yet, b"stats27": full_day([*range(1, 8), 101, 102, 103], d="2026-10-27"),
              b"stats30": full_day([*range(1, 8), 101, 102, 103], d="2026-10-30"),
              b"defs": np.array([(101, b"OZNZ6 C1201"), (102, b"OZNZ6 C1202")], dtype=DEFS)}
    c = FakeClient()
    monkeypatch.setattr(dd, "_client", lambda: c)
    monkeypatch.setattr(dd, "_array", lambda content: arrays[content])
    monkeypatch.setenv("CTD_DATA_ROOT", str(store.root))
    return c


def fetch(store, asof=MON, today=date(2026, 10, 27)):
    gaps = fetch_date(asof, store, object(), sources=[registry.SOURCES[dd.SOURCE]], today=today, fill_missing=False,
                      log=lambda _: None)
    return gaps, mf.load(store, asof)["sources"][dd.SOURCE]


def test_a_ready_date_is_stored_with_its_request(store, client):
    gaps, man = fetch(store)
    assert gaps == [] and man["status"] == mf.OK and set(man["units"]) == {*dd.FUT_MONTHS, *dd.OPT_UNITS}
    assert store.names(MON, dd.SOURCE, "SR1") == ["SR1_statistics_2026-10-26.dbn.zst",
                                                  "SR1_symbology_raw_symbol_2026-10-26.json"]
    assert store.names(MON, dd.SOURCE, "OZN") == ["OZN_definition_2026-10-26.dbn.zst",
                                                  "OZN_statistics_2026-10-26.dbn.zst",
                                                  "OZN_symbology_raw_symbol_2026-10-26.json"]
    params = store.meta(MON, dd.SOURCE, "SR1", "SR1_statistics_2026-10-26.dbn.zst")["params"]
    assert params["symbols"] == [f"SR1.c.{k}" for k in range(7)] and params["stype_in"] == "continuous"
    assert (params["start"], params["end"], params["cost_usd"]) == ("2026-10-26T00:00:00-05:00",
                                                                    "2026-10-27T00:00:00-05:00", 0.01)
    lookup = json.loads(store.read(MON, dd.SOURCE, "ZN", "ZN_symbology_raw_symbol_2026-10-26.json"))
    assert len(lookup["result"]) == 10
    # first date: each option unit's whole set of definitions, by parent
    assert {c["symbols"][0] for c in client.calls if c["schema"] == "definition"} == {f"{u}.OPT" for u in dd.OPT_UNITS}
    n = len(client.calls)
    fetch(store)
    assert len(client.calls) == n  # stored: never pulled again


def test_later_dates_request_definitions_for_new_options_only(store, client):
    fetch(store)
    client.calls.clear()
    client.available, client.content["statistics"] = "2026-10-28T13:10:00Z", b"stats27"
    _, man = fetch(store, asof=date(2026, 10, 27), today=date(2026, 10, 28))
    assert man["status"] == mf.OK
    defs = [c for c in client.calls if c["schema"] == "definition"]
    # the stored file defines 101 and 102 under the symbols they still have; only 103 is new
    assert {(c["stype_in"], tuple(c["symbols"])) for c in defs} == {("instrument_id", (103,))}
    assert store.names(date(2026, 10, 27), dd.SOURCE, "OZT") == ["OZT_definition_2026-10-27.dbn.zst",
                                                                 "OZT_statistics_2026-10-27.dbn.zst",
                                                                 "OZT_symbology_raw_symbol_2026-10-27.json"]


def test_nothing_is_requested_before_the_window_is_queryable(store, client):
    client.available = "2026-10-27T04:59:00Z"
    gaps, man = fetch(store)
    assert man["status"] == mf.FAILED and client.calls == []
    assert "the 2026-10-26 window ends" in man["units"]["ZN"]["error"]
    client.available, client.condition = "2026-10-27T13:10:00Z", "pending"
    _, man = fetch(store)
    assert man["status"] == mf.FAILED and client.calls == [] and "pending" in man["units"]["OZB"]["error"]


def test_a_degraded_date_is_stored_with_a_note(store, client):
    client.condition = "degraded"
    _, man = fetch(store)
    assert man["status"] == mf.OK
    assert man["units"]["ZN"]["notes"] == ["GLBX.MDP3 degraded on 2026-10-26"]


def test_a_friday_checks_its_weekend_and_needs_every_date_listed(store, client):
    client.available = "2026-11-02T13:10:00Z"
    client.listed, client.content["statistics"] = ["2026-10-30", "2026-10-31"], b"stats30"  # Sunday not listed yet
    _, man = fetch(store, asof=date(2026, 10, 30), today=date(2026, 11, 2))
    assert man["status"] == mf.FAILED and "2026-11-01 not listed" in man["units"]["ZN"]["error"]
    client.listed = None
    _, man = fetch(store, asof=date(2026, 10, 30), today=date(2026, 11, 2))
    assert man["status"] == mf.OK


def test_an_incomplete_pull_is_not_stored(store, client):
    client.content["statistics"] = b"partial"
    _, man = fetch(store)
    assert man["status"] == mf.FAILED
    assert "0 with open interest" in man["units"]["ZN"]["error"]
    assert "no final settlements" in man["units"]["OZN"]["error"]
    assert store.names(MON, dd.SOURCE, "ZN") == [] and store.names(MON, dd.SOURCE, "OZN") == []


def test_not_collected_before_the_first_date(store, client):
    _, man = fetch(store, asof=date(2026, 10, 23), today=date(2026, 10, 27))
    assert man["status"] == mf.NOT_EXPECTED and client.calls == []
