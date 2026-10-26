"""Derived tables (design 4): incremental builds equal full ones, precedence, overlap, failures."""

import json
from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from ctd.data.cme_bulletin import OptionSettle
from ctd.data.databento import (IDENTITY, UNDEF_PRICE, UNDEF_TS, final_settlements, futures_rows,
                                 merge_symbology, option_label, option_rows, stats_frame)
from ctd.data.derived import bonds, futures, rates
from ctd.data.derived.bonds import price_rows, securities_rows
from ctd.data.derived.options import bulletin_rows
from ctd.data.derived.quality import chain_quality
from ctd.data.derived.store import DerivedStore, Source, Table, build, file_ref

SCHEMA = pa.schema([("asof", pa.date32()), ("product", pa.string()), ("k", pa.int64()), ("v", pa.float64()),
                    ("source", pa.string())])
B_FROM = date(2026, 10, 16)


def toy_source(name: str, version: int = 1) -> Source:
    """Rows [{product, k, v}] in one JSON file per date."""
    def units(store):
        return {d.isoformat(): [file_ref(store, d, name, "all", "rows.json")]
                for d in store.asofs() if store.names(d, name, "all")}

    def read(store, key):
        d = date.fromisoformat(key)
        return [{"asof": d, **r} for r in json.loads(store.read(d, name, "all", "rows.json"))], []

    return Source(name, version, units, read, lambda key: (None, int(key[:4])))


TOY = Table("toy", 1, SCHEMA, key=("asof", "product", "k"), compare=("v",),
            sources=(toy_source("a"), toy_source("b")), winner=lambda d, p: "b" if d >= B_FROM else "a")


def put(store, d: date, source: str, rows: list[dict]) -> None:
    store.write(d, source, "all", "rows.json", json.dumps(rows).encode(), {})


def rows(*vs: float, product: str = "ZN") -> list[dict]:
    return [{"product": product, "k": k, "v": v} for k, v in enumerate(vs)]


def quiet(_):
    pass


def test_precedence_overlap_and_no_gap_filling(store):
    dstore = DerivedStore(store.root)
    put(store, date(2026, 10, 15), "a", rows(1.0, 2.0))
    put(store, date(2026, 10, 16), "a", rows(1.0, 2.0, 3.0))
    put(store, date(2026, 10, 16), "b", rows(1.0, 2.5))
    put(store, date(2026, 10, 19), "a", rows(4.0))  # b has no file: the date stays empty
    report = build(dstore, store, TOY, log=quiet)
    t = dstore.read("toy")
    assert list(zip(t["asof"], t["source"], t["v"])) == [
        (date(2026, 10, 15), "a", 1.0), (date(2026, 10, 15), "a", 2.0),
        (date(2026, 10, 16), "b", 1.0), (date(2026, 10, 16), "b", 2.5)]
    [o] = report.disagreements
    assert (o["asof"], o["winner"], o["other"], o["both"], o["differ"], o["only_b"], o["only_a"]) == \
        ("2026-10-16", "b", "a", 2, 1, 0, 1)
    assert o["examples"] == [{"k": 1, "v": 2.5, "v_o": 2.0}]
    assert dstore.state("toy")["partitions"]["ZN/2026"]["by_source"] == {"a": 2, "b": 2}


def test_incremental_equals_full(store, tmp_path):
    dstore = DerivedStore(store.root)
    put(store, date(2025, 12, 31), "a", rows(0.5))
    put(store, date(2026, 10, 15), "a", rows(1.0) + rows(9.0, product="ZB"))
    put(store, date(2026, 10, 16), "b", rows(1.0))
    build(dstore, store, TOY, log=quiet)

    put(store, date(2026, 10, 19), "b", rows(2.0))
    store.replace(date(2026, 10, 16), "b", "all", "rows.json", json.dumps(rows(1.5)).encode(), {})
    report = build(dstore, store, TOY, log=quiet)
    assert report.read == {"a": 0, "b": 2}  # only the new and the changed file
    assert build(dstore, store, TOY, log=quiet).read == {"a": 0, "b": 0}

    incremental = dstore.read("toy")
    assert incremental.loc[incremental["asof"] == date(2026, 10, 16), "v"].tolist() == [1.5]
    build(dstore, store, TOY, full=True, log=quiet)
    pd.testing.assert_frame_equal(dstore.read("toy"), incremental)
    other = DerivedStore(tmp_path / "elsewhere")
    build(other, store, TOY, log=quiet)
    pd.testing.assert_frame_equal(other.read("toy"), incremental)

    assert dstore.read("toy", products=["ZB"])["v"].tolist() == [9.0]
    assert dstore.read("toy", end=date(2025, 12, 31))["v"].tolist() == [0.5]
    assert dstore.read("toy", start=date(2026, 10, 16), end=date(2026, 10, 16))["v"].tolist() == [1.5]


def test_a_unit_that_fails_is_reported_dropped_and_retried(store):
    dstore = DerivedStore(store.root)
    put(store, date(2026, 10, 14), "a", rows(1.0))
    store.write(date(2026, 10, 15), "a", "all", "rows.json", b"not json", {})
    report = build(dstore, store, TOY, log=quiet)
    assert list(report.errors["a"]) == ["2026-10-15"]
    assert dstore.read("toy")["asof"].tolist() == [date(2026, 10, 14)]
    assert list(build(dstore, store, TOY, log=quiet).errors["a"]) == ["2026-10-15"]  # retried every build

    store.replace(date(2026, 10, 15), "a", "all", "rows.json", json.dumps(rows(2.0)).encode(), {})
    report = build(dstore, store, TOY, log=quiet)
    assert report.errors["a"] == {} and report.read["a"] == 1
    assert dstore.read("toy")["v"].tolist() == [1.0, 2.0]


def test_version_bumps_rebuild(store):
    dstore = DerivedStore(store.root)
    for d in (date(2026, 10, 14), date(2026, 10, 15)):
        put(store, d, "a", rows(1.0))
    build(dstore, store, TOY, log=quiet)
    bumped = replace(TOY, sources=(toy_source("a", version=2), toy_source("b")))
    assert build(dstore, store, bumped, log=quiet).read == {"a": 2, "b": 0}
    assert build(dstore, store, replace(bumped, version=2), log=quiet).read == {"a": 2, "b": 0}
    with pytest.raises(FileNotFoundError, match="ctd derive"):
        dstore.read("options")


def page(trade_date: str, months: list[tuple[str, str, str]]) -> bytes:
    """A CME settlement page: (month, settle, open interest) rows."""
    return json.dumps({"tradeDate": trade_date, "settlements": [
        {"month": m, "settle": s, "volume": "1", "openInterest": oi} for m, s, oi in months]}).encode()


def test_cme_open_interest_comes_from_the_next_page(store):
    dstore = DerivedStore(store.root)
    store.write(date(2026, 10, 21), "cme_fut", "ZN", "ZN.json",
                page("10/21/2026", [("DEC 26", "105'035", "5,857,268"), ("MAR 27", "104'285", "11,027")]), {})
    build(dstore, store, futures.TABLE, log=quiet)
    t = dstore.read("futures")
    assert t["open_interest"].isna().all() and t["contract"].tolist() == ["ZNZ6", "ZNH7"]

    store.write(date(2026, 10, 22), "cme_fut", "ZN", "ZN.json",
                page("10/22/2026", [("DEC 26", "106'130", "5,851,680"), ("MAR 27", "106'065", "11,128")]), {})
    assert build(dstore, store, futures.TABLE, log=quiet).read["cme_fut"] == 2  # the 21st is read again
    t = dstore.read("futures")
    assert list(zip(t["asof"], t["contract"], t["settle"], t["open_interest"].astype(object).where(
        t["open_interest"].notna(), None))) == [
        (date(2026, 10, 21), "ZNZ6", 105 + 3.5 / 32, 5_851_680), (date(2026, 10, 21), "ZNH7", 104 + 28.5 / 32, 11_128),
        (date(2026, 10, 22), "ZNZ6", 106 + 13 / 32, None), (date(2026, 10, 22), "ZNH7", 106 + 6.5 / 32, None)]


SYMBOLOGY = {"start_date": "2016-01-01", "result": {
    "1": [{"d0": "2016-01-01", "d1": "2016-03-20", "s": "ZNH6"}, {"d0": "2016-03-20", "d1": "2026-10-22", "s": "OZNM6 C1300"}],
    "2": [{"d0": "2016-01-01", "d1": "2026-10-22", "s": "ZNM6"}]}}


STATS = np.dtype([("ts_event", "u8"), ("instrument_id", "u4"), ("ts_ref", "u8"), ("stat_type", "u2"),
                  ("stat_flags", "u1"), ("price", "i8"), ("quantity", "i8")])


def ns(ts: str) -> int:
    return pd.Timestamp(ts).value


def stats(*records) -> pd.DataFrame:
    """(ts_event, instrument_id, ts_ref or None, stat_type, stat_flags, price, quantity) records, as
    the statistics record array ``stats_frame`` reads (prices fixed-point, unset fields at their sentinels)."""
    a = np.array([(ns(t), iid, UNDEF_TS if ref is None else ns(ref), st, fl,
                   UNDEF_PRICE if px is None else round(px * 1e9), UNDEF_PRICE if q is None else q)
                  for t, iid, ref, st, fl, px, q in records], dtype=STATS)
    return stats_frame(a)


def test_databento_futures_rows():
    df = stats(
        ("2016-01-01T00:20Z", 1, "2015-12-31", 3, 3, 129.0, None),  # before the history starts
        ("2016-03-01T22:00Z", 1, "2016-03-01", 3, 2, 130.0, None),  # preliminary
        ("2016-03-02T00:20Z", 1, "2016-03-01", 3, 3, 130.0, None),
        ("2016-03-02T22:56Z", 1, "2016-03-01", 3, 3, 131.0, None),  # stray: next afternoon, the next day's price
        ("2016-03-06T17:08Z", 1, None, 3, 3, 130.5, None),  # Sunday repeat
        ("2016-03-01T23:00Z", 1, "2016-03-01", 7, 0, 999.0, None),  # another statistic
        ("2016-03-02T01:00Z", 1, "2016-03-01", 9, 0, None, 100),
        ("2016-03-02T13:00Z", 1, "2016-03-01", 9, 0, None, 105),  # morning revision
        ("2016-03-02T00:20Z", 2, "2016-03-01", 3, 3, 129.5, None),
        ("2016-03-02T00:20Z", 2, "2016-03-01", 3, 3, 129.5, None))
    out, notes = futures_rows(df, SYMBOLOGY, "ZN")
    assert out == [
        {"asof": date(2016, 3, 1), "product": "ZN", "month": date(2016, 3, 1), "contract": "ZNH6", "settle": 130.0,
         "open_interest": 105},
        {"asof": date(2016, 3, 1), "product": "ZN", "month": date(2016, 6, 1), "contract": "ZNM6", "settle": 129.5,
         "open_interest": None}]
    assert len(notes) == 3 and "kept the one equal to the preliminary for 1," in notes[1]

    reused = stats(("2016-03-22T00:20Z", 1, "2016-03-21", 3, 3, 1.5, None))  # id 1 is an option by then
    with pytest.raises(ValueError, match="'OZNM6 C1300', not a ZN futures contract"):
        futures_rows(reused, SYMBOLOGY, "ZN")
    placeholder = stats(("2016-03-22T00:20Z", 1, "2016-03-21", 3, 3, 0.0, None))
    assert futures_rows(placeholder, SYMBOLOGY, "ZN") == (
        [], ["1 settlement(s) of 0.0 on instruments not yet a ZN futures contract skipped (placeholders before listing)"])


# SR1 around the 2018-06-29 roll: the front-two pull (c.0, c.1) and months 3 to 8 (c.2 on), both
# from 2018-06-01. Id 3 is c.2 until 07-01, then c.1.
FRONT = {"start_date": "2018-06-01", "result": {
    "1": [{"d0": "2018-06-01", "d1": "2018-07-01", "s": "SR1M8"}],
    "2": [{"d0": "2018-06-01", "d1": "2018-08-01", "s": "SR1N8"}],
    "3": [{"d0": "2018-07-01", "d1": "2018-09-01", "s": "SR1Q8"}]}}
MONTHS_3_TO_8 = {"start_date": "2018-06-01", "result": {
    "3": [{"d0": "2018-06-01", "d1": "2018-07-01", "s": "SR1Q8"}],
    "4": [{"d0": "2017-01-01", "d1": "2018-06-01", "s": "6R4V8 P0082"},  # an option before it was listed
          {"d0": "2018-06-01", "d1": "2018-10-01", "s": "SR1U8"}]}}


def test_databento_pulls_are_joined_before_finals_are_picked():
    """A record is in the pull whose symbol its id was when it was published: SR1Q8's final for
    Friday 2018-06-29 was sent on Sunday, after the roll, so it's in the front-two pull with its
    preliminary in the other."""
    front = stats(("2018-06-29T23:00Z", 2, "2018-06-29", 3, 3, 98.075, None),
                  ("2018-07-01T16:06Z", 3, "2018-06-29", 3, 3, 98.075, None),
                  ("2018-07-02T13:35Z", 3, "2018-06-29", 9, 0, None, 1581))
    later = stats(("2018-06-29T19:13Z", 3, "2018-06-29", 3, 2, 98.075, None),
                  ("2018-06-29T23:10Z", 4, "2018-06-29", 3, 3, 98.045, None),
                  ("2018-05-30T23:00Z", 4, "2018-05-30", 3, 3, 0.0, None))  # placeholder before listing
    rows, notes = futures_rows(pd.concat([front, later], ignore_index=True), merge_symbology([FRONT, MONTHS_3_TO_8]),
                               "SR1")
    assert [(r["asof"], r["contract"], r["settle"], r["open_interest"]) for r in rows] == [
        (date(2018, 6, 29), "SR1N8", 98.075, None), (date(2018, 6, 29), "SR1Q8", 98.075, 1581),
        (date(2018, 6, 29), "SR1U8", 98.045, None)]
    assert notes == ["1 settlement(s) dated before 2018-06-01 skipped"]


def test_merge_symbology():
    merged = merge_symbology([FRONT, MONTHS_3_TO_8])
    assert merged["start_date"] == "2018-06-01" and len(merged["result"]["3"]) == 2
    clash = {"start_date": "2018-01-01", "result": {"3": [{"d0": "2018-06-15", "d1": "2018-06-20", "s": "SR1U8"}]}}
    with pytest.raises(ValueError, match="instrument 3 is both 'SR1Q8' and 'SR1U8' from 2018-06-15"):
        merge_symbology([MONTHS_3_TO_8, clash])


def test_databento_futures_unit_holds_both_pulls(store):
    for d, source, name in ((date(2026, 10, 22), "databento_fut_backfill", "SR1"),
                            (date(2026, 10, 26), "databento_stir_backfill", "SR1_c2-c7")):
        for kind in ("statistics_2016-01-01_2026-10-24.dbn.zst", "symbology_raw_symbol_2016-01-01_2026-10-24.json",
                     "symbology_continuous_2016-01-01_2026-10-24.json"):
            store.write(d, source, "SR1", f"{name}_{kind}", b"x", {})
    store.write(date(2026, 10, 22), "databento_fut_backfill", "ZN", "ZN_statistics_x.dbn.zst", b"x", {})
    units = futures.DATABENTO.units(store)
    assert sorted(units) == ["SR1", "ZN"]
    assert [(f["source"], f["name"].split("_symbology")[0].split("_statistics")[0]) for f in units["SR1"]] == [
        ("databento_fut_backfill", "SR1"), ("databento_fut_backfill", "SR1"),
        ("databento_stir_backfill", "SR1_c2-c7"), ("databento_stir_backfill", "SR1_c2-c7")]


def test_final_settlements_keeps_the_last_in_the_window():
    settle, notes = final_settlements(stats(
        ("2016-01-06T00:18Z", 7, "2016-01-06", 3, 1, 0.0234375, None),  # the previous evening's final
        ("2016-01-07T00:07Z", 7, "2016-01-06", 3, 1, 0.03125, None),
        ("2016-08-23T00:19Z", 8, "2016-08-22", 3, 3, 0.0005, None),  # a wrong batch ...
        ("2016-08-23T04:35Z", 8, "2016-08-22", 3, 3, 3.0, None),  # ... corrected later that evening
        ("2016-08-22T21:41Z", 8, "2016-08-22", 3, 2, 3.0, None),
        ("2016-09-16T23:00Z", 9, "2016-09-16", 3, 3, 1.0, None),  # Friday: Monday morning is still in its window
        ("2016-09-19T15:00Z", 9, "2016-09-16", 3, 3, 1.5, None),
        ("2017-05-26T21:40Z", 10, "2017-05-26", 3, 2, 0.265625, None),  # Friday before Memorial Day
        ("2017-05-28T16:03Z", 10, "2017-05-26", 3, 1, 0.0, None),  # stray, inside the weekday window
        ("2017-05-30T00:47Z", 10, "2017-05-26", 3, 3, 0.265625, None)))  # the real final, on the holiday
    assert settle.to_dict() == {(np.datetime64("2016-01-06"), 7): 0.03125, (np.datetime64("2016-08-22"), 8): 3.0,
                                (np.datetime64("2016-09-16"), 9): 1.5, (np.datetime64("2017-05-26"), 10): 0.265625}
    assert notes == ["4 date/instrument pair(s) with disagreeing finals: kept the one equal to the preliminary for 2, "
                     "the last in the settlement window for 2, the last published for 0 (0 of these have a "
                     "preliminary equal to none of their finals)"]


def definitions(*records) -> pd.DataFrame:
    """(instrument_id, raw_symbol, right, strike, expiration, underlying, first, last) definition rows."""
    return pd.DataFrame([(iid, sym.encode(), right.encode(), round(k * 1e9), ns(exp), und.encode(), ns(a), ns(b))
                         for iid, sym, right, k, exp, und, a, b in records], columns=IDENTITY + ["first", "last"])


def test_option_rows():
    defs = definitions(
        (1, "OZNZ6 C1050", "C", 105.0, "2026-11-20T22:00Z", "ZNZ6", "2026-10-15", "2026-10-19"),
        (2, "OZNF7 P1000", "P", 100.0, "2026-12-24T22:00Z", "ZNH7", "2026-10-16T14:00Z", "2026-10-19"),  # listed on the 16th
        (3, "OZNX6 C1100", "C", 110.0, "2026-10-23T21:00Z", "ZNZ6", "2026-10-15", "2026-10-19"),
        (4, "OZTZ6 C1050", "C", 105.0, "2026-11-20T22:00Z", "ZNZ6", "2016-01-04", "2016-11-18"))  # id 4 reused since
    df = stats(
        ("2026-10-16T23:00Z", 1, "2026-10-16", 3, 3, 1.25, None),
        ("2026-10-17T13:00Z", 1, "2026-10-16", 6, 0, None, 500),
        ("2026-10-17T13:00Z", 1, "2026-10-16", 9, 0, None, 12000),
        ("2026-10-16T23:00Z", 2, "2026-10-16", 3, 3, 0.001, None),  # cabinet, on its first day
        ("2026-10-16T23:00Z", 3, "2026-10-16", 3, 3, 0.5, None),
        ("2026-10-15T23:00Z", 2, "2026-10-15", 3, 3, 0.0, None),  # dated before its first definition
        ("2026-10-16T23:00Z", 4, "2026-10-16", 3, 3, 0.0, None),  # id 4 isn't a call or put any more
        ("2026-10-19T23:00Z", 1, "2026-10-19", 3, 3, 1.5, None),  # last date: no volume or OI published yet
        ("2026-10-19T23:00Z", 3, "2026-10-19", 3, 3, 0.0, None))  # a placeholder
    table, notes = option_rows(df, defs, "ZN")
    rows = table.to_pylist()
    assert [(r["asof"].day, r["label"], r["right"], r["strike"]) for r in rows] == [
        (16, "DEC26", "C", 105.0), (16, "JAN27", "P", 100.0), (16, "NOV26", "C", 110.0), (19, "DEC26", "C", 105.0)]
    assert rows[0] == {"asof": date(2026, 10, 16), "product": "ZN", "label": "DEC26", "expiry": date(2026, 11, 20),
                       "underlying_month": date(2026, 12, 1), "right": "C", "strike": 105.0, "settle": 1.25,
                       "cabinet": False, "volume": 500, "open_interest": 12000}
    assert (rows[1]["settle"], rows[1]["cabinet"], rows[1]["volume"], rows[1]["open_interest"],
            rows[1]["underlying_month"]) == (None, True, 0, 0, date(2027, 3, 1))  # nothing published: none traded
    assert rows[2]["expiry"] == date(2026, 10, 23)
    assert (rows[3]["volume"], rows[3]["open_interest"]) == (None, None)
    assert notes == ["2 settlement(s) on instruments not defined as calls or puts by that date skipped (mostly 0.0 "
                     "or reference settlements for strikes listed for the next session)",
                     "1 settlement(s) of 0.0 from 2017-05-19 on skipped (placeholders, never with open interest)"]


def test_zero_was_a_cabinet_before_2017_05_19():
    defs = definitions((1, "OZNN7 C1400", "C", 140.0, "2017-06-23T21:00Z", "ZNU7", "2017-01-03", "2017-06-23"))
    df = stats(("2017-05-18T23:00Z", 1, "2017-05-18", 3, 3, 0.0, None),
               ("2017-05-19T23:00Z", 1, "2017-05-19", 3, 3, 0.001, None),
               ("2017-05-22T23:00Z", 1, "2017-05-22", 3, 3, 0.0, None))
    rows = option_rows(df, defs, "ZN")[0].to_pylist()
    assert [(r["asof"], r["settle"], r["cabinet"]) for r in rows] == [(date(2017, 5, 18), None, True),
                                                                      (date(2017, 5, 19), None, True)]


@pytest.mark.parametrize("symbol, expiry, label", [("OZNZ6 C1050", date(2026, 11, 20), "DEC26"),
                                                   ("OZNF7 P1000", date(2026, 12, 24), "JAN27"),
                                                   ("OZBG0 C1600", date(2019, 12, 27), "FEB20"),
                                                   ("OZTX6 P1013", date(2016, 10, 21), "NOV16")])
def test_option_label(symbol, expiry, label):
    assert option_label(symbol, expiry) == label


def test_option_label_checks_the_expiry():
    with pytest.raises(ValueError, match="doesn't follow its expiry"):
        option_label("OZNZ6 C1050", date(2026, 8, 21))


def test_bulletin_rows():
    settles = [OptionSettle("ZN", "NOV26", "C", 104.5, 42 / 64, 0.896, 8366, 65200),
               OptionSettle("ZN", "JAN27", "P", 100.0, None, None, 0, 200)]
    out, notes = bulletin_rows(date(2026, 10, 16), settles, {("ZN", "NOV26"): date(2026, 10, 23)})
    assert out[0] == {"asof": date(2026, 10, 16), "product": "ZN", "label": "NOV26", "expiry": date(2026, 10, 23),
                      "underlying_month": date(2026, 12, 1), "right": "C", "strike": 104.5, "settle": 42 / 64,
                      "cabinet": False, "volume": 8366, "open_interest": 65200}
    assert (out[1]["expiry"], out[1]["underlying_month"], out[1]["settle"], out[1]["cabinet"]) == \
        (None, date(2027, 3, 1), None, True)
    assert notes == ["no last trade date on page 1 for ZN JAN27"]


def test_missing_trading_days_are_listed(store):
    dstore = DerivedStore(store.root)
    for d in (date(2026, 11, 20), date(2026, 11, 24), date(2026, 11, 25), date(2026, 11, 27)):
        put(store, d, "b", rows(1.0))  # b wins from 2026-10-16
    report = build(dstore, store, TOY, log=quiet)
    # Monday the 23rd is missing; Thanksgiving (the 26th) is a holiday on the cme calendar
    assert report.missing_days == {"ZN": ["2026-11-23"]}
    assert dstore.state("toy")["missing_days"] == {"ZN": ["2026-11-23"]}
    assert build(dstore, store, replace(TOY, calendar=None), full=True, log=quiet).missing_days == {}


def test_chain_quality_flags_stale_parity_and_order():
    days = [date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4), date(2026, 3, 5), date(2026, 3, 6)]
    strikes = [96 + 0.5 * i for i in range(17)]
    rows_, fut = [], []
    for i, d in enumerate(days):
        tv = 1.6 if i == 2 else 1.0  # the 4th: a stale straddle, 60% rich
        for k in strikes:
            c, p = max(100 - k, 0) + tv, max(k - 100, 0) + tv
            if i == 4 and k >= 103.5:
                c += 0.1 * (k - 103)  # the 6th: calls rising with strike at two strikes
            for right, settle in (("C", c), ("P", p)):
                rows_.append({"asof": d, "product": "ZN", "label": "JUN26", "expiry": date(2026, 5, 22),
                              "underlying_month": date(2026, 6, 1), "right": right, "strike": k, "settle": settle,
                              "cabinet": False, "volume": 0, "open_interest": 0, "source": "test"})
        fut.append({"asof": d, "product": "ZN", "month": date(2026, 6, 1), "contract": "ZNM6",
                    "settle": 100.5 if i == 3 else 100.0})  # the 5th: futures 16/32 away from the options
    q = chain_quality(pd.DataFrame(rows_), pd.DataFrame(fut), "ZN")
    assert q["issues"].tolist() == ["", "", "stale", "parity", "order"]
    assert q["ok"].tolist() == [True, True, False, False, False]
    assert q.loc[2, "straddle_log"] == pytest.approx(np.log(1.6), abs=1e-3)  # less a day of time decay
    assert q.loc[3, "parity"] == pytest.approx(-0.5) and q.loc[4, "order_breaks"] == 2
    assert pd.isna(q.loc[0, "straddle_log"]) and pd.isna(q.loc[4, "straddle_log"])  # one neighbour only


def test_a_build_with_nothing_new_changes_nothing(store):
    dstore = DerivedStore(store.root)
    put(store, date(2026, 11, 20), "b", rows(1.0))
    build(dstore, store, TOY, log=quiet)
    before = (dstore.table_dir("toy") / "_build.json").read_bytes()
    build(dstore, store, TOY, log=quiet)
    assert (dstore.table_dir("toy") / "_build.json").read_bytes() == before


def test_chain_quality_compares_chains_on_the_same_futures():
    rows_ = []
    for d in (date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4)):
        for label, expiry in (("APR26", date(2026, 3, 27)), ("MAY26", date(2026, 4, 24)), ("JUN26", date(2026, 5, 22))):
            f = 100.5 if (d.day, label) == (3, "MAY26") else 100.0  # MAY26 on the 3rd: priced off 16/32 higher
            for k in [98 + 0.5 * i for i in range(9)]:
                for right, settle in (("C", max(f - k, 0) + 1.0), ("P", max(k - f, 0) + 1.0)):
                    rows_.append({"asof": d, "product": "ZN", "label": label, "expiry": expiry,
                                  "underlying_month": date(2026, 6, 1), "right": right, "strike": k, "settle": settle,
                                  "cabinet": False, "volume": 0, "open_interest": 0, "source": "test"})
    no_futures = pd.DataFrame(columns=["asof", "product", "month", "contract", "settle"])
    q = chain_quality(pd.DataFrame(rows_), no_futures, "ZN")
    flagged = q.loc[~q["ok"], ["asof", "label", "issues"]]
    assert [(r.asof.day, r.label, r.issues) for r in flagged.itertuples()] == [(3, "MAY26", "forward")]
    assert q["parity"].isna().all()  # no futures price: parity isn't checked, and doesn't fail
    assert q.loc[(q["asof"].dt.day == 3) & (q["label"] == "MAY26"), "forward_gap"].item() == pytest.approx(0.5)


PRICE_FILE = b"""912797QX8,MARKET BASED BILL,0.000000,11/19/2026,,0.000000,99.649444,99.649444
912810QC5,MARKET BASED BOND,0.045,08/15/2039,,93.484375,93.406250,93.281250
91282CRF0,MARKET BASED NOTE,0.04125,08/15/2036,,0.000000,95.000000,0.000000
912828V49,TIPS,0.00375,01/15/2027,,0.000000,99.843750,0.000000
"""


def test_bond_price_rows():
    rows, notes = price_rows(date(2026, 10, 21), PRICE_FILE)
    assert [(r["type"], r["cusip"], r["buy"], r["sell"], r["eod"]) for r in rows] == [
        ("BILL", "912797QX8", None, 99.649444, 99.649444), ("BOND", "912810QC5", 93.484375, 93.40625, 93.28125),
        ("NOTE", "91282CRF0", None, 95.0, None), ("TIPS", "912828V49", None, 99.84375, None)]
    assert rows[1]["coupon"] == 0.045 and rows[1]["maturity"] == date(2039, 8, 15) and rows[1]["call_date"] is None
    assert not any(r["provisional"] for r in rows) and notes == []  # the bond has end of day
    same_evening = PRICE_FILE.replace(b",93.281250", b",0.000000")
    assert all(r["provisional"] for r in price_rows(date(2026, 10, 21), same_evening)[0])
    odd, notes = price_rows(date(2026, 10, 21), PRICE_FILE.replace(b"TIPS", b"STRIPS"))
    assert odd[3]["type"] == "STRIPS" and notes == ["security types not recognised, kept as printed: ['STRIPS']"]


def test_bond_prices_partitioned_by_type_on_the_bond_market_calendar(store):
    dstore = DerivedStore(store.root)
    for d in (date(2026, 10, 9), date(2026, 10, 13)):  # Columbus Day (the 12th) closes the bond market
        store.write(d, "td_prices", "securityprice", f"securityprice_{d.isoformat()}.csv", PRICE_FILE, {})
    report = build(dstore, store, bonds.PRICES, log=quiet)
    assert report.missing_days == {"BILL": [], "BOND": [], "NOTE": [], "TIPS": []}
    assert sorted(p.name for p in dstore.table_dir("bond_prices").glob("type=*")) == \
        ["type=BILL", "type=BOND", "type=NOTE", "type=TIPS"]
    notes = dstore.read("bond_prices", ["NOTE", "BOND"])
    assert sorted(notes["cusip"].unique()) == ["912810QC5", "91282CRF0"] and len(notes) == 4


def test_securities_one_row_per_cusip():
    auctions = [
        {"cusip": "91282CFV8", "type": "Note", "securityTerm": "9-Year 10-Month", "originalSecurityTerm": "10-Year",
         "interestRate": "4.125", "issueDate": "2023-01-17T00:00:00", "maturityDate": "2032-11-15T00:00:00",
         "datedDate": "2022-11-15T00:00:00", "callable": "No"},
        {"cusip": "91282CFV8", "type": "Note", "securityTerm": "10-Year", "originalSecurityTerm": "10-Year",
         "interestRate": "4.125", "issueDate": "2022-11-15T00:00:00", "maturityDate": "2032-11-15T00:00:00",
         "datedDate": "2022-11-15T00:00:00", "callable": "No"},
        {"cusip": "912797QX8", "type": "Bill", "securityTerm": "4-Week", "interestRate": "",
         "issueDate": "2026-10-22T00:00:00", "maturityDate": "2026-11-19T00:00:00", "datedDate": None}]
    rows, notes = securities_rows(auctions)
    note, bill = sorted(rows, key=lambda r: r["type"], reverse=True)
    assert (note["original_term"], note["coupon"], note["original_issue_date"], note["last_issue_date"],
            note["dated_date"], note["auctions"]) == ("10-Year", 0.04125, date(2022, 11, 15), date(2023, 1, 17),
                                                      date(2022, 11, 15), 2)
    assert (bill["coupon"], bill["dated_date"], bill["original_term"]) == (None, date(2026, 10, 22), "4-Week")
    assert notes == []
    auctions[0]["maturityDate"] = "2032-11-30T00:00:00"
    assert securities_rows(auctions)[1] == ["1 CUSIP(s) whose coupon or maturity differs between auctions: ['91282CFV8']"]


YIELD_CURVE_2026 = b'''Date,"1 Mo","1.5 Month","2 Mo","3 Mo","4 Mo","6 Mo","1 Yr","2 Yr","3 Yr","5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"
10/13/2026,4.11,4.11,4.16,4.22,4.30,4.30,4.44,4.69,4.75,4.82,4.89,5.00,5.37,5.33
10/09/2026,4.10,4.10,4.15,4.21,4.29,4.29,4.43,4.68,4.74,4.81,4.88,4.99,5.36,5.32
'''


def test_par_curve_from_treasury_checked_against_fred(store):
    dstore = DerivedStore(store.root)
    store.write(date(2026, 10, 13), "par_curve", "daily_treasury_yield_curve", "daily_treasury_yield_curve_2026.csv",
                YIELD_CURVE_2026, {})
    store.write(date(2026, 10, 13), "fred", "DGS10", "DGS10.csv",
                b"observation_date,DGS10\n2026-10-08,4.97\n2026-10-09,4.99\n2026-10-12,\n2026-10-13,5.01\n", {})
    report = build(dstore, store, rates.PAR_CURVE, log=quiet)
    t = dstore.read("par_curve")
    assert t["asof"].tolist() == [date(2026, 10, 9), date(2026, 10, 13)]  # FRED's 10-08 never fills a gap
    assert t["y_10y"].tolist() == pytest.approx([0.0499, 0.05]) and t["y_1_5m"].tolist() == pytest.approx([0.041, 0.0411])
    [o13] = report.disagreements  # 5.01 vs 5.00; the 10-09 rows agree
    assert (o13["asof"], o13["differ"]) == ("2026-10-13", 1)
    assert o13["examples"][0]["y_10y"] == pytest.approx(0.05) and o13["examples"][0]["y_10y_o"] == pytest.approx(0.0501)
    assert report.missing_days == {"par": []}  # Columbus Day (the 12th) is closed on the sifma calendar


def test_nyfed_rows_keep_the_latest_pull_and_note_revisions():
    old = json.dumps({"refRates": [
        {"effectiveDate": "2019-05-31", "type": "SOFR", "percentRate": 2.38, "percentPercentile1": "NA",
         "volumeInBillions": 1100},
        {"effectiveDate": "2019-06-03", "type": "SOFR", "percentRate": 2.40, "volumeInBillions": 1050}]}).encode()
    new = json.dumps({"refRates": [
        {"effectiveDate": "2019-06-03", "type": "SOFR", "percentRate": 2.41, "volumeInBillions": 1050,
         "targetRateFrom": 2.25, "targetRateTo": 2.5}]}).encode()
    rows, notes = rates.nyfed_rows("sofr", [old, new])
    assert [(r["asof"], r["p1"], r["volume_bn"]) for r in rows] == [(date(2019, 5, 31), None, 1100.0),
                                                                    (date(2019, 6, 3), None, 1050.0)]
    assert [r["value"] for r in rows] == pytest.approx([0.0238, 0.0241])
    assert (rows[1]["target_from"], rows[1]["target_to"]) == pytest.approx((0.0225, 0.025))
    assert notes == ["1 value(s) revised by a later pull"]
    assert rates.fred_values(b"observation_date,DFF\n2026-10-10,3.88\n2026-10-11,.\n") == {date(2026, 10, 10): 0.0388}
