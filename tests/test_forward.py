from datetime import date

import pytest

from ctd.bonds.forward import forward_clean, forward_yield
from ctd.bonds.pricing import clean_price
from ctd.data import refdata
from ctd.funding.repo import flat, growth, term_rate
from ctd.model.horizon import light_horizon

SIFMA = refdata.calendar("sifma")
R = 0.04


def simple(start, end):
    """Hand-check repo: simple interest, actual/360."""
    return 1 + R * (end - start).days / 360


def test_term_repo_compounds_over_weekends_and_holidays():
    g = flat(R, SIFMA)
    assert g(date(2026, 10, 16), date(2026, 10, 19)) == pytest.approx(1 + R * 3 / 360, abs=1e-15)  # Fri rate, 3 days
    assert g(date(2026, 10, 16), date(2026, 10, 20)) == pytest.approx((1 + R * 3 / 360) * (1 + R / 360), abs=1e-15)
    assert g(date(2026, 11, 25), date(2026, 11, 27)) == pytest.approx(1 + R * 2 / 360, abs=1e-15)  # Thanksgiving
    assert g(date(2026, 10, 22), date(2026, 10, 22)) == 1.0


def test_term_rate_is_slightly_above_the_overnight_rate():
    start, end = date(2026, 10, 22), date(2026, 12, 31)
    rt = term_rate(start, end, lambda _: R, SIFMA)
    assert R < rt < R * (1 + R * 70 / 360)
    stepped = term_rate(start, end, lambda d: R if d < date(2026, 12, 10) else R - 0.0025, SIFMA)
    assert stepped < rt
    with pytest.raises(ValueError):
        growth(end, start, lambda _: R, SIFMA)


def test_forward_price_matches_hand_carry_with_a_coupon_before_delivery():
    # 4½% Nov 2046 at 90 for settlement 22 Oct, delivered 31 Dec; 15 Nov coupon in between
    ai_settle = 2.25 * 160 / 184  # 15 May → 22 Oct of a 184-day period
    ai_delivery = 2.25 * 46 / 181  # 15 Nov → 31 Dec of a 181-day period
    dirty_fwd = (90 + ai_settle) * (1 + R * 70 / 360) - 2.25 * (1 + R * 46 / 360)
    fwd = forward_clean(90.0, 0.045, date(2046, 11, 15), date(2026, 10, 22), date(2026, 12, 31), simple)
    assert fwd == pytest.approx(dirty_fwd - ai_delivery, abs=1e-12)


def test_forward_with_no_coupon_before_delivery():
    # 4½% Aug 2046: next coupon 15 Feb, after delivery
    ai_settle, ai_delivery = 2.25 * 68 / 184, 2.25 * 138 / 184
    fwd = forward_clean(90.0, 0.045, date(2046, 8, 15), date(2026, 10, 22), date(2026, 12, 31), simple)
    assert fwd == pytest.approx((90 + ai_settle) * (1 + R * 70 / 360) - ai_delivery, abs=1e-12)


def test_coupon_on_the_delivery_date_is_paid_to_the_holder():
    # 30 Nov maturity note (coupons 31 May, 30 Nov), delivered on its 30 Nov coupon date: no accrued at delivery
    ai_settle = 2.0 * 144 / 183  # 31 May → 22 Oct of a 183-day period
    fwd = forward_clean(99.0, 0.04, date(2033, 11, 30), date(2026, 10, 22), date(2026, 11, 30), simple)
    assert fwd == pytest.approx((99 + ai_settle) * (1 + R * 39 / 360) - 2.0, abs=1e-12)


def test_forward_yield_reprices_the_forward():
    args = (90.0, 0.045, date(2046, 11, 15), date(2026, 10, 22), date(2026, 12, 31), flat(R, SIFMA))
    y = forward_yield(*args)
    assert clean_price(0.045, date(2046, 11, 15), date(2026, 12, 31), y) == pytest.approx(forward_clean(*args), abs=1e-10)


def test_light_horizon():
    first, last = date(2026, 12, 1), date(2026, 12, 31)
    assert light_horizon(first, last, 80.10, 80.05) == last  # forward falls: positive carry
    assert light_horizon(first, last, 80.05, 80.10) == first
