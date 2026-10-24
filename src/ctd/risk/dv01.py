"""Futures DV01 from the basket (design 5.9; pure).

A futures price tracks the CTD's converted forward price, so per 100 face of futures each bond
contributes its forward DV01 over its CF, ``DV01_i / CF_i``, with ``DV01_i`` the fall in the
bond's price at the horizon for a 1bp rise in its forward yield (``ctd.bonds.pricing.dv01``).

- Probability-weighted: ``Σ p_i · DV01_i / CF_i`` at z = 0 (phase 1c item 1). Region-weighting
  over shifts (5.9) replaces this when the shifted-state model exists.
- CTD-label: ``DV01 / CF`` of the single CTD at z = 0, the number vendor systems report.

Probabilities can be intervals (``model.probabilities``); the DV01 is then the range over every
probability vector they allow that sums to 1. Values per 100 face of futures are converted to
dollars per bp with ``dollars``: per $100mm notional by default, or per contract with its face.
"""

from datetime import date

from ctd.bonds.pricing import dv01

NOTIONAL = 100_000_000  # $100mm face of futures, the default unit (outputs.md Conventions)


def per_futures(coupon: float, maturity: date, horizon: date, fwd_yield: float, cf: float) -> float:
    """``DV01_i / CF_i``: one bond's contribution per 100 face of futures, in price points per bp."""
    return float(dv01(coupon, maturity, horizon, fwd_yield)) / cf


def weighted(values: dict[str, float], probs: dict[str, tuple[float, float]]) -> tuple[float, float]:
    """``(lo, hi)`` of ``Σ p_i · values_i`` over every ``p`` with ``lo_i ≤ p_i ≤ hi_i`` and ``Σ p_i = 1``.

    Points give ``lo == hi``. Exact: start every bond at its lower bound, then give the remaining
    mass to the lowest values first (for ``lo``) or the highest first (for ``hi``). Probabilities
    that don't bracket 1 (already warned in ``model.probabilities``) are rescaled to sum to 1.
    """
    lo_sum = sum(lo for lo, _ in probs.values())
    hi_sum = sum(hi for _, hi in probs.values())
    if not lo_sum - 1e-9 <= 1 <= hi_sum + 1e-9:
        mids = {c: (lo + hi) / 2 for c, (lo, hi) in probs.items()}
        total = sum(mids.values())
        x = sum(p / total * values[c] for c, p in mids.items())
        return x, x

    def fill(order):
        slack, out = 1 - lo_sum, 0.0
        for c in order:
            lo, hi = probs[c]
            take = min(max(slack, 0.0), hi - lo)
            out += (lo + take) * values[c]
            slack -= take
        return out

    by_value = sorted(probs, key=lambda c: values[c])
    return fill(by_value), fill(reversed(by_value))


def dollars(per_100: float, face: float = NOTIONAL) -> float:
    """$ per bp for ``face`` of futures, from a DV01 in price points per 100 face."""
    return per_100 / 100 * face
