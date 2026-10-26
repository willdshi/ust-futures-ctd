"""Digitals from option settlements: the light model's probabilities (design 5.11 step 3; pure).

A premium is paid upfront, so the slope of the put price in strike, divided by the discount
factor to expiry, is the probability of the futures finishing below the strike:

    P(F_E < K) ≈ [Put(K_hi) − Put(K_lo)] / (K_hi − K_lo) / DF
    P(F_E > K) ≈ [Call(K_lo) − Call(K_hi)] / (K_hi − K_lo) / DF

Out-of-the-money options are used: puts for a strike below the futures price (sell-off side),
calls above it (rally side). Each pair of neighbouring priced strikes gives a digital at its
midpoint, and ``K`` is interpolated linearly between neighbouring midpoints.

A cabinet settlement (``OptionSettle.cabinet``) only says the option is worth less than one tick,
and a settlement at the minimum tick says little more once rounded, so a pair that includes either
gives an upper bound, not a probability: each price is taken as an interval (exact if priced
above one tick, 0 to one tick otherwise) and the bound is the widest slope those intervals allow.
Two such strikes half a point apart give "≤ 3%" (1/64 over ½). So do two equal settlements, which
wings often show (a floor: ZN puts from 98.5 to 100.5 all at 2/64 on 2026-10-16): once rounded
they are at most one tick apart. A ``K`` beyond the listed strikes
gets no value. Results are flagged where open interest is zero or the slope falls outside [0, 1].
"""

from dataclasses import dataclass

from ctd.data.cme_bulletin import OptionSettle

TICK = {"ZN": 1 / 64, "TN": 1 / 64, "ZB": 1 / 64, "UB": 1 / 64, "ZF": 1 / 128, "ZT": 1 / 128}  # TN: every stored settlement a multiple of 1/64 (October 2026)


@dataclass(frozen=True)
class Digital:
    """``P(F_E < strike)`` (``side="below"``, from puts) or ``P(F_E > strike)`` (``"above"``, calls).

    ``prob`` is None when ``strike`` is beyond the listed strikes. With ``upper_bound`` True it is
    a bound (``P ≤ prob``) because a cabinet or minimum-tick settlement was involved.
    """

    strike: float
    side: str
    prob: float | None
    upper_bound: bool
    strikes_used: tuple[float, ...]
    flags: tuple[str, ...]


def _below_tick(o: OptionSettle, tick: float) -> bool:
    """Cabinet, or settled at the minimum tick: worth somewhere between 0 and one tick."""
    return o.cabinet or o.settle <= tick + 1e-12


def _slope(a: OptionSettle, b: OptionSettle, right: str, tick: float, df: float) -> tuple[float, bool]:
    """Digital from strikes ``a < b`` and whether it is only an upper bound (a price below one tick involved)."""
    fuzzy = _below_tick(a, tick) or _below_tick(b, tick)
    lo = lambda o: 0.0 if _below_tick(o, tick) else o.settle  # noqa: E731
    hi = lambda o: tick if _below_tick(o, tick) else o.settle  # noqa: E731
    gap = b.strike - a.strike
    if not fuzzy and a.settle == b.settle:  # a floor: equal once rounded, so at most one tick apart
        return tick / gap / df, True
    if right == "P":  # put rises with strike
        value = (hi(b) - lo(a)) if fuzzy else (b.settle - a.settle)
    else:  # call falls with strike
        value = (hi(a) - lo(b)) if fuzzy else (a.settle - b.settle)
    return value / gap / df, fuzzy


def digital(chain: list[OptionSettle], strike: float, futures: float, df: float) -> Digital:
    """The digital at ``strike`` from one product's options for one expiry (``chain``).

    ``futures`` is the underlying's settlement: a ``strike`` below it is read from puts as
    ``P(F_E < strike)``, at or above it from calls as ``P(F_E > strike)``. ``df`` is the discount
    factor from premium payment to expiry.
    """
    right, side = ("P", "below") if strike < futures else ("C", "above")
    opts = sorted((o for o in chain if o.right == right), key=lambda o: o.strike)
    products = {o.product for o in chain}
    if len(products) != 1 or len({o.label for o in chain}) != 1:
        raise ValueError("chain must hold one product and one expiry")
    tick = TICK[products.pop()]
    if not opts or not opts[0].strike <= strike <= opts[-1].strike:
        return Digital(strike, side, None, False, (), ("beyond listed strikes",))

    pairs = list(zip(opts, opts[1:]))
    mids = [(a.strike + b.strike) / 2 for a, b in pairs]
    j = max([i for i, m in enumerate(mids) if m <= strike], default=0)
    if strike <= mids[0] or j == len(mids) - 1:  # near an end: the one bracketing pair
        used = [pairs[0] if strike <= mids[0] else pairs[-1]]
        weights = [1.0]
    else:  # between midpoints j and j + 1
        used = [pairs[j], pairs[j + 1]]
        w = (strike - mids[j]) / (mids[j + 1] - mids[j])
        weights = [1 - w, w]
    slopes = [_slope(a, b, right, tick, df) for a, b in used]
    prob = sum(wt * s for wt, (s, _) in zip(weights, slopes))
    bound = any(fuzzy for _, fuzzy in slopes)  # touching a price below one tick: a bound

    options = {o for pair in used for o in pair}
    flags = []
    if any(o.open_interest == 0 for o in options):
        flags.append("zero open interest")
    if prob < 0 or prob > 1:
        flags.append(f"slope {prob:.3f} outside [0, 1], clipped")
        prob = min(max(prob, 0.0), 1.0)
    return Digital(strike, side, prob, bound, tuple(sorted(o.strike for o in options)), tuple(flags))
