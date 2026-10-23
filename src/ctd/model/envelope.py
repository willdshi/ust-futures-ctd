"""Envelope of converted forward prices and the switch points (design 5.7, 5.11; pure).

Every bond's forward yield is shifted in parallel by z (beta = 1 in the light model; betas come
in phase 2) and repriced at the horizon through the single pricing function:

    C_i(z) = P_i(y_i^fwd + z) / CF_i,   E(z) = min_i C_i(z)

The bond achieving the minimum is the CTD at z. A grid locates where it changes; each change is
root-found exactly. If a third bond is cheaper at a root, two switches fell in one grid step and
the interval is split there and solved again. A switch and switch back within one step would be
missed, which a 1bp grid makes negligible. Shifts ``z`` are in basis points throughout.
"""

from dataclasses import dataclass
from datetime import date

import numpy as np
from scipy.optimize import brentq

from ctd.bonds.pricing import clean_price


@dataclass(frozen=True)
class BasketBond:
    cusip: str
    coupon: float  # decimal
    maturity: date
    cf: float
    fwd_yield: float  # decimal, at the horizon


@dataclass(frozen=True)
class Switch:
    """As yields rise through ``z_bp``, the CTD changes from ``from_cusip`` to ``to_cusip``."""

    z_bp: float
    from_cusip: str
    to_cusip: str
    envelope: float  # E(z_bp)


def converted(bonds: list[BasketBond], horizon: date, z_bp) -> np.ndarray:
    """``C_i(z)``: one row per bond, one column per shift (a scalar ``z_bp`` gives one column)."""
    z = np.atleast_1d(np.asarray(z_bp, dtype=float)) / 1e4
    return np.array([np.atleast_1d(clean_price(b.coupon, b.maturity, horizon, b.fwd_yield + z)) / b.cf
                     for b in bonds])


def envelope(bonds: list[BasketBond], horizon: date, z_bp) -> tuple[np.ndarray, list[str]]:
    """``E(z)`` and the CTD's CUSIP at each shift."""
    c = converted(bonds, horizon, z_bp)
    idx = c.argmin(axis=0)
    return c[idx, np.arange(c.shape[1])], [bonds[i].cusip for i in idx]


def switches(bonds: list[BasketBond], horizon: date, lo_bp: float = -100, hi_bp: float = 150,
             step_bp: float = 1) -> list[Switch]:
    """Every change of CTD between ``lo_bp`` and ``hi_bp``, in increasing z."""
    def c(i: int, z: float) -> float:
        return converted([bonds[i]], horizon, z)[0, 0]

    def cheapest(z: float) -> int:
        return int(converted(bonds, horizon, z)[:, 0].argmin())

    def solve(lo: float, hi: float, a: int, b: int) -> list[Switch]:
        if a == b:
            return []
        z = brentq(lambda x: c(a, x) - c(b, x), lo, hi, xtol=1e-10)
        m = cheapest(z)
        if m in (a, b) or c(m, z) >= c(a, z) - 1e-12:
            return [Switch(z, bonds[a].cusip, bonds[b].cusip, min(c(a, z), c(b, z)))]
        return solve(lo, z, a, m) + solve(z, hi, m, b)

    grid = np.arange(lo_bp, hi_bp + step_bp / 2, step_bp)
    ctd = converted(bonds, horizon, grid).argmin(axis=0)
    out = []
    for j in np.flatnonzero(ctd[1:] != ctd[:-1]):
        out += solve(grid[j], grid[j + 1], int(ctd[j]), int(ctd[j + 1]))
    return out
