from datetime import date

import pytest

from ctd.data import refdata
from ctd.reference.delivery import delivery_for, rule_dates

CME = refdata.calendar("cme")


def test_december_2026_checked_against_cme():
    for contract in ("ZN", "TN", "ZB", "UB"):
        d = delivery_for(refdata.delivery_calendar(), contract, date(2026, 12, 1))
        assert (d.first_delivery, d.last_trading, d.last_delivery) == \
            (date(2026, 12, 1), date(2026, 12, 21), date(2026, 12, 31))  # last trading skips Christmas
        assert set(d.verified) == {"first_delivery", "last_trading", "last_delivery"}


def test_every_record_agrees_with_the_rule():
    for r in refdata.delivery_calendar():
        month = date.fromisoformat(r.month + "-01")
        rule = rule_dates(r.contract, month, CME)
        assert (r.first_delivery, r.last_trading, r.last_delivery) == \
            (rule.first_delivery, rule.last_trading, rule.last_delivery), r


def test_rule_skips_holidays_and_weekends():
    march = rule_dates("ZB", date(2027, 3, 15), CME)
    assert march.last_trading == date(2027, 3, 19)  # Good Friday 26 March isn't counted
    assert rule_dates("ZN", date(2026, 11, 1), CME).first_delivery == date(2026, 11, 2)  # 1 Nov is a Sunday


def test_missing_month_and_unencoded_contract():
    with pytest.raises(KeyError, match="no delivery calendar stored for ZB 2030-12"):
        delivery_for(refdata.delivery_calendar(), "ZB", date(2030, 12, 1))
    with pytest.raises(ValueError, match="no delivery rule encoded for ZT"):
        rule_dates("ZT", date(2026, 12, 1), CME)
