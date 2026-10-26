"""Shifted states and the duration profile on synthetic baskets (design 5.9, 8; phase 1c item 4)."""

from datetime import date

import numpy as np
import pytest
from scipy.special import ndtr

from ctd.bonds.conversionfactor import conversion_factor
from ctd.curve.par import ParCurve
from ctd.model import profile as pf
from ctd.model.envelope import BasketBond, envelope, switches

HORIZON = date(2026, 12, 31)
PAR = ParCurve((0.5, 30.0), (0.055, 0.055))
S = 40.0


def basket(*terms):
    month = date(2026, 12, 1)
    return [BasketBond(c, cpn, m, conversion_factor(cpn, m, month, 3), 0.055) for c, (cpn, m) in terms]


TWO = basket(("A", (0.03125, date(2042, 2, 15))), ("D", (0.02, date(2050, 2, 15))))
FOUR = basket(("A", (0.03125, date(2042, 2, 15))), ("B", (0.045, date(2044, 2, 15))),
              ("C", (0.0475, date(2045, 5, 15))), ("D", (0.02, date(2050, 2, 15))))


def build(bonds, s=S):
    span = pf.reach(s)
    return pf.profile(bonds, HORIZON, PAR, switches(bonds, HORIZON, -span, span), s)


def test_two_bond_probabilities_are_normal_tails_beyond_the_switch():
    [sw] = switches(TWO, HORIZON, -300, 300)
    p = build(TWO).curve
    long_ = 1 - ndtr((sw.z_bp - p.centres) / S)
    assert p.probs[sw.to_cusip] == pytest.approx(long_, abs=1e-12)
    assert p.probs[sw.from_cusip] + p.probs[sw.to_cusip] == pytest.approx(np.ones(len(p.centres)), abs=1e-12)


def test_region_weighted_dv01_is_the_slope_of_the_expected_envelope():
    # design 8: DV01_F(c) = −d/dc E_c[min_i C_i(z)] per bp, checked by finite differences on a fine grid
    prof = build(FOUR)
    z = np.arange(-pf.reach(S), pf.reach(S) + 0.05, 0.1)
    e, _ = envelope(FOUR, HORIZON, z)

    def expected(c):
        w = np.exp(-((z - c) / S) ** 2 / 2)
        return (w * e).sum() / w.sum()

    for c in (-60.0, -10.0, 0.0, 25.0, 70.0):
        fd = -(expected(c + 0.5) - expected(c - 0.5))
        j = int(np.flatnonzero(prof.curve.centres == c)[0])
        assert prof.curve.dv01[j] == pytest.approx(fd, rel=2e-4)


def test_krds_add_up_and_probabilities_sum_to_one():
    p = build(FOUR).curve
    assert p.krd.sum(axis=1) == pytest.approx(p.dv01, rel=1e-12)
    assert sum(p.probs.values()) == pytest.approx(np.ones(len(p.centres)), abs=1e-12)
    assert p.percentiles == pytest.approx(ndtr(p.centres / S))


def test_narrow_width_approaches_the_ctd_label_staircase():
    p = build(FOUR, s=0.5).curve
    sws = [s.z_bp for s in switches(FOUR, HORIZON, -100, 100)]
    away = np.array([min(abs(c - z) for z in sws) > 3 for c in p.centres])
    assert p.dv01[away] == pytest.approx(p.label_dv01[away], rel=1e-4)
    assert p.krd[away] == pytest.approx(p.label_krd[away], rel=1e-3, abs=1e-9)


def test_points_bands_and_label():
    prof = build(FOUR)
    pts = prof.points
    assert pts.centres == pytest.approx([-2 * S, -S, 0, S, 2 * S])
    assert pts.percentiles[prof.point(1)] == pytest.approx(0.841345, abs=1e-6)
    _, label = envelope(FOUR, HORIZON, pts.centres)
    assert list(pts.label) == label
    # the CTD-based DV01 at today's state is the CTD's DV01/CF at its forward yield
    from ctd.risk.dv01 import per_futures
    ctd = next(b for b in FOUR if b.cusip == pts.label[prof.point(0)])
    assert pts.label_dv01[prof.point(0)] == pytest.approx(per_futures(ctd.coupon, ctd.maturity, HORIZON, 0.055, ctd.cf))
    lo, hi = prof.band_dv01
    assert lo.shape == hi.shape == prof.curve.dv01.shape
    assert not np.allclose(lo, hi)  # the width matters near the switches


def test_shifted_curve_moves_key_rate_shapes():
    # Against the par curve, a bond below par sits beyond its maturity and one above par short of it
    # (a par bond lands on its maturity at any level), so as yields rise every fixed-coupon bond's
    # effective maturity lengthens: the opposite of a cash-flow-weighted maturity.
    from ctd.risk.krd import effective_maturity
    one = basket(("D", (0.02, date(2050, 2, 15))))
    _, k = pf.values({"D": one[0]}, HORIZON, PAR, np.array([-100.0, 0.0, 100.0]), ["D"] * 3)
    em = [effective_maturity(x) for x in k]
    assert em[0] < em[1] < em[2]
    assert em[0] > (date(2050, 2, 15) - HORIZON).days / 365.25  # deep discount even at −100bp


def test_the_profile_widens_to_take_in_two_sigma():
    assert pf.half_range(45.1) == 100  # ±2σ = ±90bp: the standard ±100bp
    assert pf.half_range(48.0) == 110  # ±96bp would sit 4bp from the end
    assert pf.half_range(55.3) == 120
    assert pf.reach(55.3) >= 120 + pf.TAIL_WIDTHS * 55.3 * (1 + pf.VOL_BAND)

