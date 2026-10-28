"""ATM vol against a normal (Bachelier) option model with a known vol (design 5.5, roadmap 1c.3)."""

import math
from datetime import date

import pytest

from ctd.data.cme_bulletin import OptionSettle
from ctd.vol.atm import atm, bachelier, implied_vol, normal_tail, width, years, yield_vol

F, VOL, T, DF = 117.3, 7.5, 30 / 365, 0.997  # futures, price vol per √year, years to expiry, discount factor


def chain(futures=F, step=0.5, tick=None, drop=(), oi=100):
    rows = []
    for i in range(-20, 21):
        k = round(futures / step) * step + i * step
        for right in "PC":
            if (right, k) in drop:
                continue
            p = bachelier(right, futures, k, VOL, T, DF)
            if tick:
                p = round(p / tick) * tick
            rows.append(OptionSettle("ZB", "DEC26", right, k, p, None, 0, oi))
    return rows


def test_bachelier_parity_and_round_trip():
    for k in (110.0, 117.3, 121.5):
        c, p = bachelier("C", F, k, VOL, T, DF), bachelier("P", F, k, VOL, T, DF)
        assert c - p == pytest.approx(DF * (F - k), abs=1e-12)
        assert implied_vol("C", F, k, c, T, DF) == pytest.approx(VOL, abs=1e-10)
        assert implied_vol("P", F, k, p, T, DF) == pytest.approx(VOL, abs=1e-10)
    assert implied_vol("C", F, 110.0, DF * (F - 110.0), T, DF) is None  # at intrinsic: no vol


def test_atm_recovers_a_flat_vol():
    v = atm(chain(), F, DF, T)
    assert v.strikes == (117.0, 117.5) and v.flags == ()
    assert v.price_vol == pytest.approx(VOL, abs=1e-9)


def test_futures_on_a_strike_uses_that_call():
    v = atm(chain(futures=117.5), 117.5, DF, T)
    assert v.strikes == (117.0, 117.5)
    assert v.price_vol == pytest.approx(VOL, abs=1e-9)


def test_rounding_to_64ths_costs_well_under_one_percent():
    # an ATM ZB premium near 0.85 points, rounded to 1/128 at worst: about 1% of the vol at most
    v = atm(chain(tick=1 / 64), F, DF, T)
    assert v.price_vol == pytest.approx(VOL, rel=0.01)


def test_matches_the_straddle_rule_of_thumb():
    # ATM straddle ≈ 2 · DF · σ√T / √(2π)
    straddle = bachelier("C", F, F, VOL, T, DF) + bachelier("P", F, F, VOL, T, DF)
    assert straddle / (2 * DF * math.sqrt(T)) * math.sqrt(2 * math.pi) == pytest.approx(VOL, rel=1e-12)


def test_missing_strike_and_thin_inputs_are_flagged():
    v = atm(chain(drop={("P", 117.0)}), F, DF, T)
    assert v.strikes == (116.5, 117.5)
    assert "no priced strike between 116.5 and 117.5" in v.flags
    assert v.price_vol == pytest.approx(VOL, abs=1e-9)  # still exact: the vol is flat
    thin = atm(chain(oi=0), F, DF, T)  # no open interest: recorded, not a warning
    assert thin.no_open_interest == thin.strikes and thin.traded == () and thin.flags == ()


def test_traded_strikes_are_recorded():
    rows = [o if (o.right, o.strike) != ("C", 117.5) else OptionSettle(o.product, o.label, o.right, o.strike,
                                                                       o.settle, None, 25, 100) for o in chain()]
    v = atm(rows, F, DF, T)
    assert v.strikes == (117.0, 117.5) and v.traded == (117.5,) and v.no_open_interest == ()


def test_needs_options_on_both_sides():
    with pytest.raises(ValueError, match="both sides"):
        atm([o for o in chain() if o.right == "P"], F, DF, T)
    with pytest.raises(ValueError, match="one product and one expiry"):
        atm(chain() + [OptionSettle("ZB", "MAR27", "P", 100.0, 1.0, None, 0, 1)], F, DF, T)


def test_units_from_price_vol_to_width():
    assert years(date(2026, 10, 21), date(2026, 11, 20)) == pytest.approx(30 / 365)
    # 8 points per √year over a DV01/CF of 0.1 points per bp: 80bp per √year; a quarter-year width 40bp
    assert yield_vol(8.0, 0.1) == pytest.approx(80.0)
    assert width(80.0, 0.25) == pytest.approx(40.0)
    assert normal_tail(40.0, 40.0) == pytest.approx(0.158655, abs=1e-6)
    assert normal_tail(-40.0, 40.0) == normal_tail(40.0, 40.0)
