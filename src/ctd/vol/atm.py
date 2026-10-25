"""At-the-money implied vol and the factor width (design 5.5 steps 1, 2 and 4; phase 1c item 3; pure).

1. Normal (Bachelier) implied price vol of the out-of-the-money option at the priced strikes either
   side of the futures price (a put below, a call at or above, as in ``vol.digitals``), interpolated
   linearly in strike to the futures price. Premiums are paid upfront, so prices carry the discount
   factor to expiry. American exercise is ignored (design 9).
2. Price vol to yield vol with the CTD's forward DV01 / CF at that expiry's underlying:
   ``σ_y = σ_price / (DV01/CF)``, in bp per √year (``DV01/CF`` in price points per bp).
3. Width ``S = σ_y √T``: to the horizon for the shift distribution, to option expiry for the
   comparison with the option digitals (both measure the move by the same date).

One expiry, so the width is scaled by √T (design 5.5 fallback); total-variance interpolation with a
second expiry is phase 1c item 7. Time is calendar days from the as-of date over 365.
"""

import math
from dataclasses import dataclass
from datetime import date

from scipy.optimize import brentq

from ctd.data.cme_bulletin import OptionSettle

DAYS_PER_YEAR = 365
MAX_VOL = 100.0  # price points per √year: far above any Treasury futures option


def years(start: date, end: date) -> float:
    """Calendar days from ``start`` to ``end`` over 365."""
    return (end - start).days / DAYS_PER_YEAR


def _cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _pdf(x: float) -> float:
    return math.exp(-x * x / 2) / math.sqrt(2 * math.pi)


def bachelier(right: str, futures: float, strike: float, vol: float, t: float, df: float) -> float:
    """Premium of a call (``right="C"``) or put on futures under a normal model, ``vol`` in price
    points per √year, ``t`` in years, ``df`` from premium payment to expiry."""
    s = vol * math.sqrt(t)
    d = (futures - strike) / s
    call = df * ((futures - strike) * _cdf(d) + s * _pdf(d))
    return call if right == "C" else call - df * (futures - strike)


def implied_vol(right: str, futures: float, strike: float, premium: float, t: float, df: float) -> float | None:
    """The normal vol that reprices ``premium``; None if the premium is at or below intrinsic value
    (or above any reachable price)."""
    intrinsic = df * max(futures - strike if right == "C" else strike - futures, 0.0)
    if premium <= intrinsic or premium >= bachelier(right, futures, strike, MAX_VOL, t, df):
        return None
    return brentq(lambda v: bachelier(right, futures, strike, v, t, df) - premium, 1e-9, MAX_VOL, xtol=1e-12)


@dataclass(frozen=True)
class AtmVol:
    label: str  # option month, "DEC26"
    futures: float  # the underlying's settlement
    t: float  # years to expiry
    strikes: tuple[float, float]  # the out-of-the-money put below the futures, the call at or above
    vols: tuple[float, float]  # their implied normal vols
    price_vol: float  # interpolated to the futures price, price points per √year
    flags: tuple[str, ...]


def atm(chain: list[OptionSettle], futures: float, df: float, t: float) -> AtmVol:
    """ATM normal price vol from one product's options for one expiry (``chain``)."""
    if len({o.product for o in chain}) != 1 or len({o.label for o in chain}) != 1:
        raise ValueError("chain must hold one product and one expiry")
    puts = [o for o in chain if o.right == "P" and o.strike < futures and not o.cabinet]
    calls = [o for o in chain if o.right == "C" and o.strike >= futures and not o.cabinet]
    if not puts or not calls:
        raise ValueError(f"no priced out-of-the-money option on both sides of the futures price {futures}")
    lo, hi = max(puts, key=lambda o: o.strike), min(calls, key=lambda o: o.strike)
    vols = (implied_vol("P", futures, lo.strike, lo.settle, t, df),
            implied_vol("C", futures, hi.strike, hi.settle, t, df))
    if None in vols:
        raise ValueError(f"no normal vol reprices the {chain[0].label} options at {lo.strike} and {hi.strike}")
    w = (futures - lo.strike) / (hi.strike - lo.strike)

    flags = []
    strikes = sorted({o.strike for o in chain})
    step = min(b - a for a, b in zip(strikes, strikes[1:])) if len(strikes) > 1 else hi.strike - lo.strike
    if hi.strike - lo.strike > step + 1e-9:
        flags.append(f"no priced strike between {lo.strike:g} and {hi.strike:g}")
    if lo.open_interest == 0 or hi.open_interest == 0:
        flags.append("zero open interest")
    return AtmVol(chain[0].label, futures, t, (lo.strike, hi.strike), vols, (1 - w) * vols[0] + w * vols[1],
                  tuple(flags))


def yield_vol(price_vol: float, dv01_cf: float) -> float:
    """Normal yield vol in bp per √year from a price vol, with ``dv01_cf`` in price points per bp."""
    return price_vol / dv01_cf


def width(yield_vol_bp: float, t: float) -> float:
    """``S = σ_y √t`` in bp."""
    return yield_vol_bp * math.sqrt(t)


def normal_tail(z_bp: float, s_bp: float) -> float:
    """Probability of a normal move of width ``s_bp`` going beyond ``z_bp`` on its own side of 0."""
    return _cdf(-abs(z_bp) / s_bp)
