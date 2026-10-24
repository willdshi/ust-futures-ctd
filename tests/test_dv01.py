"""Futures DV01 from the basket (design 5.9, phase 1c item 1)."""

from datetime import date

import pytest

from ctd.bonds.pricing import clean_price
from ctd.risk.dv01 import NOTIONAL, dollars, per_futures, weighted

T = date(2026, 12, 31)


def test_per_futures_is_the_converted_price_change_per_bp():
    # DV01/CF equals the fall in the converted forward price C = P(y)/CF for a 1bp rise
    c, m, y, cf = 0.05, date(2045, 5, 15), 0.055, 0.8899
    fd = (clean_price(c, m, T, y - 1e-5) - clean_price(c, m, T, y + 1e-5)) / 2 / 0.1 / cf
    assert per_futures(c, m, T, y, cf) == pytest.approx(fd, rel=1e-7)


def test_points_give_the_weighted_sum():
    values = {"A": 0.12, "B": 0.15, "C": 0.19}
    probs = {"A": (0.5, 0.5), "B": (0.3, 0.3), "C": (0.2, 0.2)}
    assert weighted(values, probs) == pytest.approx((0.143, 0.143))


def test_intervals_give_the_exact_range():
    # C is "≤ 10%", B "20–30%": mass left after the lower bounds (1 − 0.6 − 0.2 = 0.2) goes to the
    # lowest values first for the low end, the highest first for the high end
    values = {"A": 0.12, "B": 0.15, "C": 0.19}
    probs = {"A": (0.6, 0.6), "B": (0.2, 0.3), "C": (0.0, 0.1)}
    lo, hi = weighted(values, probs)
    # slack 0.2 equals the room (0.1 + 0.1): B and C must both fill, so the range is a point
    assert (lo, hi) == pytest.approx((0.136, 0.136))
    probs = {"A": (0.5, 0.7), "B": (0.2, 0.3), "C": (0.0, 0.1)}  # slack 0.3, room 0.4
    lo, hi = weighted(values, probs)
    assert lo == pytest.approx(0.7 * 0.12 + 0.3 * 0.15 + 0.0 * 0.19)  # A fills 0.2, then B 0.1
    assert hi == pytest.approx(0.6 * 0.12 + 0.3 * 0.15 + 0.1 * 0.19)  # C fills 0.1, then B 0.1, then A 0.1


def test_probabilities_not_bracketing_one_are_rescaled():
    lo, hi = weighted({"A": 0.1, "B": 0.2}, {"A": (0.55, 0.55), "B": (0.5, 0.5)})
    assert lo == hi == pytest.approx((0.55 * 0.1 + 0.5 * 0.2) / 1.05)


def test_dollars():
    assert NOTIONAL == 100_000_000
    assert dollars(0.124) == pytest.approx(124_000)  # per $100mm
    assert dollars(0.124, 100_000) == pytest.approx(124)  # per ZB contract
