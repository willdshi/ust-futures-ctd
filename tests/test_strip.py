"""SR1 strip to an overnight SOFR path (design 5.3, path 3)."""

from datetime import date, timedelta

import pytest

from ctd.data import refdata
from ctd.funding.repo import flat
from ctd.funding.strip import solve

SIFMA = refdata.calendar("sifma")
OCT, NOV, DEC, JAN = date(2026, 10, 1), date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1)


def fixings(start: date, end: date, rate) -> dict[date, float]:
    """A fixing on every business day in [start, end]; ``rate`` a number or a function of the day."""
    out, d = {}, start
    while d <= end:
        if SIFMA.is_business_day(d):
            out[d] = rate(d) if callable(rate) else rate
        d += timedelta(days=1)
    return out


def implied_average(s, known: dict[date, float], month: date) -> float:
    """What SR1 settles to under the strip's path: calendar days, each at its business day's rate."""
    days = [month + timedelta(days=i) for i in range(31) if (month + timedelta(days=i)).month == month.month]
    rate = []
    for d in days:
        gov = SIFMA.latest_business_day(d)
        rate.append(known[max(k for k in known if k <= gov)] if gov < s.first_unknown else s.rate_on(gov))
    return sum(rate) / len(rate)


def test_a_flat_strip_gives_back_flat_sofr():
    known = fixings(date(2026, 9, 30), date(2026, 10, 22), 0.039)
    s = solve({OCT: 0.039, NOV: 0.039, DEC: 0.039}, known, date(2026, 12, 30), SIFMA)
    assert s.first_unknown == date(2026, 10, 23)
    assert all(v == pytest.approx(0.039, abs=1e-15) for v in s.rates.values())
    assert s.growth(SIFMA)(date(2026, 10, 23), date(2026, 12, 31)) == pytest.approx(
        flat(0.039, SIFMA)(date(2026, 10, 23), date(2026, 12, 31)), abs=1e-14)


def test_month_to_date_fixings_set_the_rest_of_the_month():
    # October fixed at 3.80% so far, averaging 3.90%: the remaining days make up the difference
    known = fixings(date(2026, 9, 30), date(2026, 10, 22), 0.038)
    s = solve({OCT: 0.039}, known, date(2026, 10, 30), SIFMA)
    # 1–22 Oct (Thu 22 covers itself only) are known, 23–31 Oct (9 days) aren't
    assert s.rates[OCT] == pytest.approx((31 * 0.039 - 22 * 0.038) / 9)
    assert implied_average(s, known, OCT) == pytest.approx(0.039, abs=1e-14)


def test_each_month_reprices_its_average_with_carry_in_days():
    # 1 Nov 2026 is a Sunday and 1 Jan 2027 a holiday-Friday: those days take the previous month's rate
    known = fixings(date(2026, 9, 30), date(2026, 10, 22), lambda d: 0.0385 + d.day * 1e-6)
    avg = {OCT: 0.0390, NOV: 0.0392, DEC: 0.0407, JAN: 0.0413}
    s = solve(avg, known, date(2027, 1, 29), SIFMA)
    for m, a in avg.items():
        assert implied_average(s, known, m) == pytest.approx(a, abs=1e-14)
    # Sunday 1 November carries October's rate (Fri 30 Oct), so November's own 29 days make up the rest
    assert s.rates[NOV] == pytest.approx((30 * avg[NOV] - s.rates[OCT]) / 29)


def test_fixings_must_reach_the_month_start_and_months_must_be_listed():
    known = fixings(date(2026, 10, 9), date(2026, 10, 22), 0.039)  # a 14-day file only
    with pytest.raises(ValueError, match="fixings start 2026-10-09"):
        solve({OCT: 0.039, NOV: 0.039}, known, date(2026, 11, 30), SIFMA)
    known = fixings(date(2026, 9, 30), date(2026, 10, 22), 0.039)
    with pytest.raises(ValueError, match="no SR1 settlement for Nov 2026"):
        solve({OCT: 0.039}, known, date(2026, 11, 30), SIFMA)
    s = solve({OCT: 0.039}, known, date(2026, 10, 30), SIFMA)
    with pytest.raises(ValueError, match="no SR1 rate solved for Nov 2026"):
        s.rate_on(date(2026, 11, 2))
    with pytest.raises(ValueError, match="known fixing"):
        s.rate_on(date(2026, 10, 22))


def test_a_known_day_without_a_fixing_takes_the_one_before():
    # Good Friday 2026 (3 Apr) is a SIFMA early close, open, but the NY Fed publishes no SOFR
    known = fixings(date(2026, 3, 31), date(2026, 4, 7), 0.04)
    del known[date(2026, 4, 3)]
    assert SIFMA.is_business_day(date(2026, 4, 3))
    s = solve({date(2026, 4, 1): 0.04}, known, date(2026, 4, 30), SIFMA)
    assert s.rates[date(2026, 4, 1)] == pytest.approx(0.04, abs=1e-15)
