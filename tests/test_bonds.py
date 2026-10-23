from datetime import date

import numpy as np
import pytest

from ctd.bonds.pricing import clean_price, dirty_price, dv01, yield_from_clean
from ctd.bonds.schedule import accrued, coupon_dates, prev_next_coupon


def test_coupon_dates_mid_month():
    assert prev_next_coupon(date(2046, 8, 15), date(2026, 10, 22)) == (date(2026, 8, 15), date(2027, 2, 15))
    dates = coupon_dates(date(2028, 8, 15), date(2026, 10, 22))
    assert dates == [date(2027, 2, 15), date(2027, 8, 15), date(2028, 2, 15), date(2028, 8, 15)]


def test_coupon_dates_month_end():
    # 30 April maturity pays 31 October, not 30 October
    assert prev_next_coupon(date(2033, 4, 30), date(2026, 10, 22)) == (date(2026, 4, 30), date(2026, 10, 31))
    # 28 February (non-leap) maturity pays 31 August, and 29 February in leap years
    assert coupon_dates(date(2031, 2, 28), date(2027, 9, 1))[:2] == [date(2028, 2, 29), date(2028, 8, 31)]
    assert coupon_dates(date(2031, 2, 28), date(2026, 10, 22))[0] == date(2027, 2, 28)


def test_accrued_actual_actual():
    # 15 Aug → 22 Oct is 68 days of a 184-day period
    assert accrued(0.045, date(2046, 8, 15), date(2026, 10, 22)) == pytest.approx(100 * 0.0225 * 68 / 184, abs=1e-12)
    # 30 Apr → 22 Oct is 175 days of a 184-day period
    assert accrued(0.04, date(2033, 4, 30), date(2026, 10, 22)) == pytest.approx(2 * 175 / 184, abs=1e-12)


def test_settlement_on_coupon_date():
    settle = date(2026, 11, 15)
    assert prev_next_coupon(date(2046, 11, 15), settle) == (settle, date(2027, 5, 15))
    assert accrued(0.045, date(2046, 11, 15), settle) == 0
    assert coupon_dates(date(2046, 11, 15), settle)[0] == date(2027, 5, 15)  # today's coupon already paid


def test_par_bond_on_coupon_date_prices_at_100():
    for maturity in (date(2033, 11, 15), date(2056, 5, 15), date(2033, 4, 30)):
        settle = date(2026, 11, 15) if maturity.day == 15 else date(2026, 10, 31)
        assert clean_price(0.0425, maturity, settle, 0.0425) == pytest.approx(100, abs=1e-12)


@pytest.mark.parametrize("coupon, maturity", [(0.04125, date(2032, 11, 15)), (0.045, date(2046, 8, 15)),
                                              (0.0475, date(2056, 5, 15)), (0.04, date(2033, 4, 30)),
                                              (0.0125, date(2031, 5, 15))])
@pytest.mark.parametrize("y", [0.0, 0.01, 0.0437, 0.08])
def test_price_yield_round_trip(coupon, maturity, y):
    settle = date(2026, 10, 22)
    p = clean_price(coupon, maturity, settle, y)
    y2 = yield_from_clean(coupon, maturity, settle, p)
    assert y2 == pytest.approx(y, abs=1e-12)
    assert clean_price(coupon, maturity, settle, y2) == pytest.approx(p, abs=1e-10)


def test_clean_is_dirty_minus_accrued():
    args = (0.045, date(2046, 8, 15), date(2026, 10, 22))
    assert dirty_price(*args, 0.05) - clean_price(*args, 0.05) == pytest.approx(accrued(*args), abs=1e-12)


def test_dv01_matches_finite_difference():
    args = (0.045, date(2046, 8, 15), date(2026, 10, 22))
    h = 1e-6
    fd = (dirty_price(*args, 0.05 - h) - dirty_price(*args, 0.05 + h)) / (2 * h) * 1e-4
    assert dv01(*args, 0.05) == pytest.approx(fd, rel=1e-8)


def test_array_yields_match_scalar():
    args = (0.045, date(2046, 8, 15), date(2026, 10, 22))
    ys = np.array([0.04, 0.045, 0.05])
    np.testing.assert_allclose(clean_price(*args, ys), [clean_price(*args, y) for y in ys], rtol=0, atol=1e-12)
    np.testing.assert_allclose(dv01(*args, ys), [dv01(*args, y) for y in ys], rtol=0, atol=1e-15)


def test_final_coupon_period_raises():
    with pytest.raises(ValueError, match="final coupon period"):
        clean_price(0.04, date(2027, 2, 15), date(2026, 10, 22), 0.04)
    with pytest.raises(ValueError, match="on or after maturity"):
        accrued(0.04, date(2026, 10, 22), date(2026, 10, 22))


@pytest.mark.parametrize("coupon, maturity", [(0.04125, date(2032, 11, 15)), (0.045, date(2046, 8, 15)),
                                              (0.0475, date(2056, 5, 15)), (0.04, date(2033, 4, 30)),
                                              (0.04, date(2031, 2, 28))])
def test_against_quantlib(coupon, maturity):
    """Independent check: QuantLib with Actual/Actual (ISMA) on the bond's own schedule is street convention."""
    ql = pytest.importorskip("QuantLib")
    settle, y = date(2026, 10, 22), 0.0437
    d = lambda x: ql.Date(x.day, x.month, x.year)  # noqa: E731
    issue = date(maturity.year - 30, maturity.month, 1)  # any date well before settlement
    eom = maturity.day != 15
    schedule = ql.Schedule(d(issue), d(maturity), ql.Period(ql.Semiannual), ql.NullCalendar(), ql.Unadjusted,
                           ql.Unadjusted, ql.DateGeneration.Backward, eom)
    dc = ql.ActualActual(ql.ActualActual.ISMA, schedule)
    bond = ql.FixedRateBond(0, 100.0, schedule, [coupon], dc)
    ql_clean = ql.BondFunctions.cleanPrice(bond, y, dc, ql.Compounded, ql.Semiannual, d(settle))
    assert bond.accruedAmount(d(settle)) == pytest.approx(accrued(coupon, maturity, settle), abs=1e-10)
    assert clean_price(coupon, maturity, settle, y) == pytest.approx(ql_clean, abs=1e-9)
