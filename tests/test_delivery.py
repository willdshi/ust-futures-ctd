import csv
from datetime import date
from pathlib import Path

import pytest

from ctd.data import refdata
from ctd.data.derived.futures import last_trading_disagreements
from ctd.reference.delivery import DeliveryDates, delivery_for, rule_dates

CME = refdata.calendar("cme")


def test_december_2026_checked_against_cme():
    for contract in ("ZN", "TN", "ZB", "UB"):  # CME's published calendar, checked 2026-10-22
        d = refdata.delivery_dates(contract, date(2026, 12, 1))
        assert (d.first_delivery, d.last_trading, d.last_delivery) == \
            (date(2026, 12, 1), date(2026, 12, 21), date(2026, 12, 31))  # last trading skips Christmas


def futures_last_dates() -> list[tuple[str, date, date]]:
    """Each expired ZN, TN, ZB and UB contract's last date in the derived futures table (the Databento
    backfill: H6 2016 to U6 2026)."""
    with (Path(__file__).parent / "data" / "futures_last_dates.csv").open(newline="", encoding="utf-8") as f:
        return [(r["product"], date.fromisoformat(r["month"] + "-01"), date.fromisoformat(r["last"]))
                for r in csv.DictReader(f)]


def test_rule_matches_every_last_trading_day():
    rows = futures_last_dates()
    assert len(rows) == 172
    assert last_trading_disagreements([(p, m, last, date(2026, 10, 21)) for p, m, last in rows]) == (172, [])


def test_last_trading_disagreements():
    latest = date(2026, 12, 21)
    checked, wrong = last_trading_disagreements([
        ("ZN", date(2026, 9, 1), date(2026, 9, 18), latest),  # a day short
        ("ZB", date(2026, 12, 1), date(2026, 12, 21), latest),  # expires on the last date
        ("ZB", date(2027, 3, 1), date(2026, 12, 21), latest),  # still trading
        ("UB", date(2028, 3, 1), date(2026, 12, 21), latest)])  # past the holiday list, not looked up
    assert checked == 2 and wrong == ["ZNU6 (2026-09): last row 2026-09-18, rule 2026-09-21"]


def test_rule_skips_holidays_and_weekends():
    march = rule_dates("ZB", date(2027, 3, 15), CME)
    assert march.last_trading == date(2027, 3, 19)  # Good Friday 26 March isn't counted
    assert rule_dates("ZN", date(2026, 11, 1), CME).first_delivery == date(2026, 11, 2)  # 1 Nov is a Sunday


def test_an_exception_record_replaces_the_rule():
    moved = DeliveryDates("ZN", "2026-12", date(2026, 12, 1), date(2026, 12, 18), date(2026, 12, 31), "closure")
    assert delivery_for("ZN", date(2026, 12, 15), CME, [moved]) == moved
    assert delivery_for("ZB", date(2026, 12, 15), CME, [moved]).last_trading == date(2026, 12, 21)


def test_month_beyond_the_holiday_list_and_unencoded_contract():
    with pytest.raises(ValueError, match="holidays.csv ends"):
        refdata.delivery_dates("ZB", date(refdata.holidays_through().year + 1, 1, 1))
    with pytest.raises(ValueError, match="no delivery rule encoded for ZT"):
        rule_dates("ZT", date(2026, 12, 1), CME)
