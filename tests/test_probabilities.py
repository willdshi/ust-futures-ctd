"""Probability assembly: regions from switch points and digitals (design 5.11 step 4)."""

import math

import pytest

from ctd.data.cme_bulletin import OptionSettle
from ctd.model.envelope import Switch
from ctd.model.probabilities import assemble, strike
from ctd.vol.digitals import Digital, digital

F, SIGMA, DF = 105.0, 1.5, 0.997


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def normal_chain(step=0.5, lo=98.0, hi=112.0):
    rows, k = [], lo
    while k <= hi + 1e-9:
        d = (k - F) / SIGMA
        put = DF * ((k - F) * phi(d) + SIGMA * math.exp(-d * d / 2) / math.sqrt(2 * math.pi))
        rows += [OptionSettle("ZB", "DEC26", "P", k, put, None, 0, 100),
                 OptionSettle("ZB", "DEC26", "C", k, put + DF * (F - k), None, 0, 100)]
        k += step
    return rows


def d(side, prob, bound=False):
    return Digital(100.0, side, prob, bound, (), ())


# rally: A ← B at -30bp; CTD B; sell-off: B → C at +15bp, C → D at +40bp
SWITCHES = [Switch(-30, "A", "B", 0), Switch(15, "B", "C", 0), Switch(40, "C", "D", 0)]


def test_regions_from_a_normal_option_chain():
    # envelope values chosen so the recentred strikes sit at 107.1 (rally), 103.6 and 102.8
    e0, f_mkt = 98.0, F + 0.25  # the market settles 8/32 above E(0): recentring moves every K
    sw = [Switch(-30, "A", "B", 99.85), Switch(15, "B", "C", 96.35), Switch(40, "C", "D", 95.55)]
    ks = [strike(s, f_mkt, e0) for s in sw]
    assert ks == pytest.approx([107.1, 103.6, 102.8])
    chain = normal_chain()
    p = assemble("B", sw, [digital(chain, k, F, DF) for k in ks])

    up, dn1, dn2 = 1 - phi((107.1 - F) / SIGMA), phi((103.6 - F) / SIGMA), phi((102.8 - F) / SIGMA)
    expect = {"A": up, "B": 1 - up - dn1, "C": dn1 - dn2, "D": dn2}
    assert [r.cusip for r in p.regions] == ["A", "B", "C", "D"]
    assert [r.side for r in p.regions] == ["rally", "ctd", "selloff", "selloff"]
    for r in p.regions:
        assert r.point
        assert r.lo == pytest.approx(expect[r.cusip], abs=0.01)  # the CTD takes two interpolation errors
    assert sum(r.lo for r in p.regions) == pytest.approx(1, abs=1e-12)
    assert p.warnings == ()


def test_point_digitals_telescope():
    p = assemble("B", SWITCHES, [d("above", 0.10), d("below", 0.30), d("below", 0.05)])
    assert {k: lo for k, (lo, hi) in p.by_bond().items()} == pytest.approx(
        {"A": 0.10, "B": 0.60, "C": 0.25, "D": 0.05})
    assert p.warnings == ()


def test_order_of_switches_does_not_matter():
    digs = [d("above", 0.10), d("below", 0.30), d("below", 0.05)]
    a = assemble("B", SWITCHES, digs)
    b = assemble("B", SWITCHES[::-1], digs[::-1])
    assert a.regions == b.regions


def test_upper_bounds_give_intervals():
    # the outer sell-off digital is "≤ 3%": D gets [0, 3%], C gets [30 − 3, 30]%
    p = assemble("B", SWITCHES, [d("above", 0.10), d("below", 0.30), d("below", 0.03, bound=True)])
    got = p.by_bond()
    assert got["D"] == pytest.approx((0.0, 0.03))
    assert got["C"] == pytest.approx((0.27, 0.30))
    assert got["B"] == pytest.approx((0.60, 0.60))
    assert sum(lo for lo, _ in got.values()) <= 1 <= sum(hi for _, hi in got.values())
    assert p.warnings == ()


def test_missing_digital_is_bounded_by_the_one_inward():
    p = assemble("B", SWITCHES, [d("above", 0.10), d("below", 0.30), d("below", None)])
    got = p.by_bond()
    assert got["D"] == pytest.approx((0.0, 0.30))
    assert got["C"] == pytest.approx((0.0, 0.30))
    assert any("beyond listed strikes" in w for w in p.warnings)


def test_digital_rising_with_distance_is_clipped_and_warned():
    p = assemble("B", SWITCHES, [d("above", 0.10), d("below", 0.20), d("below", 0.25)])
    got = p.by_bond()
    assert got["C"] == (0.0, 0.0)
    assert any("rises with distance" in w for w in p.warnings)
    assert any("sum to 1.050" in w for w in p.warnings)


def test_tails_above_one_clip_the_ctd():
    p = assemble("B", SWITCHES[:2], [d("above", 0.6), d("below", 0.5)])
    assert p.by_bond()["B"] == (0.0, 0.0)
    assert any("tails sum to 1.100" in w for w in p.warnings)


def test_no_switches_leaves_everything_to_the_ctd():
    p = assemble("B", [], [])
    assert p.by_bond() == {"B": (1.0, 1.0)}


def test_a_bond_ctd_on_both_sides_is_summed():
    sw = [Switch(-20, "A", "B", 0), Switch(30, "B", "A", 0)]
    p = assemble("B", sw, [d("above", 0.1), d("below", 0.2)])
    assert p.by_bond()["A"] == pytest.approx((0.3, 0.3))


def test_inconsistent_inputs_raise():
    with pytest.raises(ValueError, match="starts from"):
        assemble("C", SWITCHES, [d("above", 0.1), d("below", 0.3), d("below", 0.05)])
    with pytest.raises(ValueError, match="needs a digital below"):
        assemble("B", SWITCHES, [d("above", 0.1), d("above", 0.3), d("below", 0.05)])
    with pytest.raises(ValueError, match="one digital per switch"):
        assemble("B", SWITCHES, [d("above", 0.1)])
