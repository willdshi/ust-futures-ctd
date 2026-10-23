"""Digitals against a normal (Bachelier) option model, where the true probabilities are known."""

import math

import pytest

from ctd.data.cme_bulletin import OptionSettle
from ctd.vol.digitals import digital

F, SIGMA, DF = 105.0, 1.5, 0.997  # futures, price vol to expiry, discount factor


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def price(right, k):
    d = (k - F) / SIGMA
    density = math.exp(-d * d / 2) / math.sqrt(2 * math.pi)
    put = DF * ((k - F) * phi(d) + SIGMA * density)
    return put if right == "P" else put + DF * (F - k)  # put-call parity


def chain(step=0.5, lo=98.0, hi=112.0, tick=None, cabinet_below=0.0, drop=()):
    rows, k = [], lo
    while k <= hi + 1e-9:
        for right in "PC":
            if (right, k) in drop:
                continue
            p = price(right, k)
            if tick:
                p = round(p / tick) * tick
            settle = None if p < cabinet_below else p
            rows.append(OptionSettle("ZB", "DEC26", right, k, settle, None, 0, 100))
        k += step
    return rows


# strikes whose neighbouring options are priced above one tick (further out, digitals are bounds)
@pytest.mark.parametrize("k", [103.0, 103.8, 104.6, 106.2, 107.2])
def test_exact_prices_recover_the_normal_probabilities(k):
    d = digital(chain(), k, F, DF)
    exact = phi((k - F) / SIGMA) if k < F else 1 - phi((k - F) / SIGMA)
    assert d.side == ("below" if k < F else "above")
    # linear interpolation between midpoint digitals cuts the corner where the tail bends:
    # about 0.4 points at 103.0 with ½-point strikes
    assert d.prob == pytest.approx(exact, abs=0.005)
    assert not d.upper_bound and d.flags == ()


def test_settlement_rounding_costs_a_couple_of_points():
    # prices rounded to 1/64 on 1-point strikes (ZB): within about 1/64 per point = 1.6%, plus
    # interpolation error
    for k in (103.6, 104.2, 105.8, 106.4):
        d = digital(chain(step=1.0, tick=1 / 64), k, F, DF)
        exact = phi((k - F) / SIGMA) if k < F else 1 - phi((k - F) / SIGMA)
        assert not d.upper_bound
        assert d.prob == pytest.approx(exact, abs=0.025)


def test_tail_next_to_a_minimum_tick_price_is_a_bound():
    # at 106.7 the second pair (107, 108) has the 108 call at 1/64: reported as a bound, at or above the truth
    d = digital(chain(step=1.0, tick=1 / 64), 106.7, F, DF)
    assert d.upper_bound and d.strikes_used == (106.0, 107.0, 108.0)
    assert 1 - phi((106.7 - F) / SIGMA) <= d.prob <= 1 - phi((106.7 - F) / SIGMA) + 0.03


def test_missing_strike_widens_the_pair():
    d = digital(chain(drop={("P", 103.0)}), 103.1, F, DF)
    assert 103.0 not in d.strikes_used
    assert d.prob == pytest.approx(phi((103.1 - F) / SIGMA), abs=0.01)


def test_cabinet_gives_an_upper_bound():
    rows = chain(step=1.0, cabinet_below=1 / 64)  # far puts below one tick settle as CAB
    cab = max(o.strike for o in rows if o.right == "P" and o.cabinet)
    d = digital(rows, cab + 0.4, F, DF)
    assert d.upper_bound and cab in d.strikes_used
    # a bound: at least the true probability, at most the upper-strike digital plus one tick per point
    assert phi((cab + 0.4 - F) / SIGMA) <= d.prob <= phi((cab + 1 - F) / SIGMA) + 1 / 64 / DF
    deep = digital(rows, 98.5, F, DF)  # both strikes cabinets: bound is one tick per point
    assert deep.upper_bound and deep.prob == pytest.approx(1 / 64 / DF)


def test_minimum_tick_pair_is_a_bound_not_zero():
    # both puts settle at 1/64, half a point apart (ZN's far strikes on 2026-10-21): "≤ 3%", not 0%
    rows = [OptionSettle("ZN", "DEC26", "P", k, 1 / 64, None, 0, 10) for k in (98.5, 99.0, 99.5)]
    rows += [OptionSettle("ZN", "DEC26", "P", 100.0, 3 / 64, None, 0, 10)]
    d = digital(rows, 99.15, 105.1, DF)
    assert d.upper_bound and d.strikes_used == (98.5, 99.0, 99.5)
    assert d.prob == pytest.approx(1 / 64 / 0.5 / DF)
    above = digital(rows, 99.8, 105.1, DF)  # 1/64 to 3/64: bound 3/64 over ½ point
    assert above.upper_bound and above.prob == pytest.approx(3 / 64 / 0.5 / DF)


def test_beyond_listed_strikes():
    d = digital(chain(), 97.0, F, DF)
    assert d.prob is None and d.flags == ("beyond listed strikes",)


def test_thin_inputs_are_flagged():
    rows = [o if o.strike != 104.0 else OptionSettle(o.product, o.label, o.right, o.strike, o.settle, None, 0, 0)
            for o in chain(step=1.0)]
    assert "zero open interest" in digital(rows, 104.2, F, DF).flags


def test_chain_must_be_one_expiry():
    rows = chain() + [OptionSettle("ZB", "MAR27", "P", 100.0, 1.0, None, 0, 1)]
    with pytest.raises(ValueError):
        digital(rows, 103.0, F, DF)


def test_equal_settlements_are_a_floor_and_give_a_bound():
    # ZN puts from 98.5 to 100.5 all settled at 2/64 on 2026-10-16: a slope of 0 says only "≤ one tick"
    rows = [OptionSettle("ZN", "DEC26", "P", k, 2 / 64, None, 0, 10) for k in (99.5, 100.0, 100.5)]
    rows += [OptionSettle("ZN", "DEC26", "P", 101.0, 3 / 64, None, 0, 10)]
    d = digital(rows, 100.09, 105.45, DF)
    assert d.upper_bound and d.prob == pytest.approx(1 / 64 / 0.5 / DF)
