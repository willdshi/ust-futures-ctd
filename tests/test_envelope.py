from datetime import date

import numpy as np
import pytest

from ctd.bonds.conversionfactor import conversion_factor
from ctd.bonds.pricing import clean_price, dirty_price, dv01
from ctd.model.envelope import BasketBond, converted, envelope, switches

T = date(2026, 12, 31)


def test_two_bond_basket_with_a_known_crossover():
    # CFs set so both converted prices equal 100 at +20bp: that's the switch, short → long duration
    short, long_ = (0.04, date(2041, 11, 15)), (0.045, date(2050, 5, 15))
    cf_s = clean_price(*short, T, 0.0520) / 100
    cf_l = clean_price(*long_, T, 0.0520) / 100
    bonds = [BasketBond("S", *short, cf_s, 0.05), BasketBond("L", *long_, cf_l, 0.05)]
    [sw] = switches(bonds, T)
    assert sw.z_bp == pytest.approx(20, abs=1e-6)
    assert (sw.from_cusip, sw.to_cusip) == ("S", "L")
    assert sw.envelope == pytest.approx(100, abs=1e-8)
    e, ctd = envelope(bonds, T, [0, 40])
    assert ctd == ["S", "L"]


def test_switches_within_one_grid_step_are_all_found():
    # three bonds with crossovers at about +10 and +30bp; a 100bp step must still find both
    terms = [(0.035, date(2040, 2, 15)), (0.04, date(2045, 5, 15)), (0.045, date(2052, 8, 15))]
    cf = [clean_price(*terms[0], T, 0.051) / 100, clean_price(*terms[1], T, 0.051) / 100, 0.0]
    cf[2] = clean_price(*terms[2], T, 0.053) / (clean_price(*terms[1], T, 0.053) / cf[1])
    bonds = [BasketBond(n, *t, f, 0.05) for n, t, f in zip("ABC", terms, cf)]
    fine = switches(bonds, T, step_bp=1)
    coarse = switches(bonds, T, lo_bp=-50, hi_bp=50, step_bp=100)
    assert [(s.from_cusip, s.to_cusip) for s in fine] == [("A", "B"), ("B", "C")]
    assert [s.z_bp for s in coarse] == pytest.approx([s.z_bp for s in fine], abs=1e-6)
    assert [s.z_bp for s in fine] == pytest.approx([10, 30], abs=1e-6)


def test_flat_six_percent_curve():
    """Design §8: converted prices ≈ 100 on a flat 6% curve; below 6% the low-duration bond is
    cheapest, above it the high-duration one."""
    month = date(2026, 12, 1)
    terms = [(0.02, date(2042, 2, 15)), (0.03125, date(2043, 5, 15)), (0.045, date(2046, 8, 15)),
             (0.04625, date(2049, 11, 15))]
    bonds = [BasketBond(str(i), c, m, conversion_factor(c, m, month, 3), 0.06) for i, (c, m) in enumerate(terms)]
    c = converted(bonds, T, 0)[:, 0]
    np.testing.assert_allclose(c, 100, atol=0.5)
    duration = [dv01(b.coupon, b.maturity, T, 0.06) / dirty_price(b.coupon, b.maturity, T, 0.06) for b in bonds]
    _, ctd = envelope(bonds, T, [-100, 100])
    assert ctd == [str(int(np.argmin(duration))), str(int(np.argmax(duration)))]
    assert ctd == ["1", "3"]  # the 2% 2042 has a longer duration than the 3⅛% 2043
