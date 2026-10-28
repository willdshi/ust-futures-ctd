"""Par curve, bootstrap and key-rate DV01s (design 5.9, Key rate DV01s)."""

from datetime import date

import numpy as np
import pytest

from ctd.bonds.pricing import dv01
from ctd.curve.par import NODES, ParCurve, key_rate_curves, tent
from ctd.data import par_curve
from ctd.risk.krd import (clusters, effective_maturity, effective_maturity_range, point_weights, shares,
                          weighted)

ASOF = date(2026, 10, 21)

# rows copied from the stored 2026 file (newest first), plus a later date the file could hold
# when fetched after the fact, and a row with a blank tenor
CURVE = (b'\xef\xbb\xbfDate,"1 Mo","1.5 Month","2 Mo","3 Mo","4 Mo","6 Mo","1 Yr","2 Yr","3 Yr","5 Yr","7 Yr",'
         b'"10 Yr","20 Yr","30 Yr"\n'
         b"10/22/2026,4.10,4.12,4.16,4.25,4.34,4.35,4.50,4.79,4.87,4.93,5.01,5.11,5.45,5.40\n"
         b"10/21/2026,4.09,4.12,4.16,4.25,4.34,4.35,4.52,4.81,4.89,4.95,5.03,5.13,5.47,5.42\n"
         b"10/20/2026,4.09,,4.16,4.25,4.34,4.35,4.52,4.81,4.89,4.95,5.03,5.13,5.47,5.42\n")
REAL = ParCurve.from_points(par_curve.parse(CURVE)[ASOF])
H = date(2026, 12, 31)


def test_reader_takes_the_latest_curve_on_or_before_asof(store):
    store.write(ASOF, "par_curve", "daily_treasury_yield_curve", "daily_treasury_yield_curve_2026.csv", CURVE, {})
    d, points = par_curve.read_latest(store, ASOF)
    assert d == ASOF
    assert points[0.5] == pytest.approx(0.0435) and points[30.0] == pytest.approx(0.0542)
    assert points[0.125] == pytest.approx(0.0412)  # "1.5 Month"
    assert 0.125 not in par_curve.parse(CURVE)[date(2026, 10, 20)]  # blank tenor left out


def test_bootstrap_reprices_par_bonds_at_par():
    df = key_rate_curves(REAL).base
    for n in (4, 14, 20, 40, 60):  # 2, 7, 10, 20 and 30y par bonds paying semiannually
        t = 0.5 * np.arange(1, n + 1)
        c = REAL.par(n / 2)
        assert 100 * (c / 2 * df(t).sum() + df(t[-1])) == pytest.approx(100, abs=1e-9)


def test_flat_curve_discounts_at_the_yield():
    df = key_rate_curves(ParCurve((0.5, 30.0), (0.05, 0.05))).base
    t = np.array([0.5, 7.0, 29.5])
    np.testing.assert_allclose(df(t), 1.025 ** (-2 * t), rtol=1e-12)


def test_tent_weights():
    w = tent([1.0, 2.0, 6.0, 17.0, 31.0])
    np.testing.assert_allclose(w.sum(axis=0), 1)
    assert w[0, 0] == 1 and w[-1, -1] == 1  # below the first node and beyond the last
    assert w[NODES.index(5.0), 2] == pytest.approx(0.5) and w[NODES.index(7.0), 2] == pytest.approx(0.5)
    assert w[NODES.index(15.0), 3] == pytest.approx(0.6) and w[NODES.index(20.0), 3] == pytest.approx(0.4)


def test_a_par_bond_maturing_on_a_node_loads_only_on_it():
    # a par bond at 20y prices at 100 whatever the par yields at other tenors
    h, m = date(2026, 11, 15), date(2046, 11, 15)
    flat = key_rate_curves(ParCurve((0.5, 30.0), (0.05, 0.05)))
    s = shares(0.05, m, h, flat)
    assert s.sum() == pytest.approx(1)
    assert s[NODES.index(20.0)] == pytest.approx(1, abs=0.01)
    assert np.abs(np.delete(s, NODES.index(20.0))).max() < 0.01


def test_low_coupon_bonds_have_negative_short_tenor_shares():
    # the 2¼% Aug-46 on a flat 5.55% curve: short at 2-15y, more than 100% at 20y (design 5.9)
    s = shares(0.0225, date(2046, 8, 15), H, key_rate_curves(ParCurve((0.5, 30.0), (0.0555, 0.0555))))
    assert (s[:5] < 0).all()
    assert s[NODES.index(10.0)] == pytest.approx(-0.073, abs=0.003)
    assert s[NODES.index(20.0)] == pytest.approx(1.171, abs=0.005)
    assert effective_maturity(s) == pytest.approx(21.7, abs=0.05)


def test_krds_scaled_to_dv01_sum_to_it():
    c, m, y = 0.05, date(2045, 5, 15), 0.055
    k = shares(c, m, H, key_rate_curves(REAL)) * float(dv01(c, m, H, y))
    assert k.sum() == pytest.approx(float(dv01(c, m, H, y)), rel=1e-12)
    assert effective_maturity(k) == pytest.approx(18.6, abs=0.1)  # matures 18.4y after the horizon


def test_weighting():
    w = point_weights({"A": (0.5, 0.5), "B": (0.0, 0.2), "C": (0.3, 0.3)})
    assert w == pytest.approx({"A": 0.5 / 0.9, "B": 0.1 / 0.9, "C": 0.3 / 0.9})
    krds = {"A": np.array([1.0, 0, 0, 0, 0, 0, 0, 0]), "B": np.array([0, 0, 0, 0, 0, 0, 0, 2.0])}
    np.testing.assert_allclose(weighted(krds, {"A": 0.75, "B": 0.25}), [0.75, 0, 0, 0, 0, 0, 0, 0.5])
    assert effective_maturity(np.array([1.0, 0, 0, 0, 0, 0, 0, 1.0])) == pytest.approx(16)


def test_effective_maturity_range_from_interval_probabilities():
    # A has all its risk at 2y, B at 30y; B is "≤ 10%", so between 0 and 10% can move from A to B
    krds = {"A": np.array([1.0, 0, 0, 0, 0, 0, 0, 0]), "B": np.array([0, 0, 0, 0, 0, 0, 0, 1.0])}
    assert effective_maturity_range(krds, {"A": (0.9, 1.0), "B": (0.0, 0.1)}) == pytest.approx((2.0, 4.8))
    assert effective_maturity_range(krds, {"A": (0.9, 0.9), "B": (0.1, 0.1)}) == pytest.approx((4.8, 4.8))


def test_clusters_by_dominant_key_rate_and_dv01():
    k = lambda node, dv01: dv01 * np.eye(len(NODES))[NODES.index(node)]  # noqa: E731
    krds = {"A": k(20.0, 1.00), "B": k(20.0, 1.04), "C": k(20.0, 1.20), "D": k(25.0, 1.02), "E": k(20.0, 1.03)}
    probs = {"A": (0.4, 0.4), "B": (0.1, 0.1), "C": (0.2, 0.2), "D": (0.0, 0.2), "E": (0.2, 0.2)}
    got = clusters(krds, probs)
    # A, E, B within 5% of A at 20y; C 20% higher; D dominated by 25y. Ordered by effective maturity.
    assert [(cl.node, cl.members) for cl in got] == [(20.0, ("A", "E", "B")), (20.0, ("C",)), (25.0, ("D",))]
    assert got[0].prob == pytest.approx((0.7, 0.7)) and got[2].prob == pytest.approx((0.0, 0.2))
    w = point_weights(probs)
    np.testing.assert_allclose(got[0].krd, (w["A"] * krds["A"] + w["E"] * krds["E"] + w["B"] * krds["B"])
                               / (w["A"] + w["E"] + w["B"]))
