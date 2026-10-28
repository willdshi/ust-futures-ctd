"""Par curve, bootstrap and key-rate bumps (design 5.9, Key rate DV01s; pure).

Par yields (decimals, semiannual bond-equivalent) are interpolated linearly between the
published tenors, flat beyond the ends, onto a semiannual grid. Each grid point is a par bond
paying semiannual coupons, which gives discount factors by bootstrap:

    DF_n = (1 − c_n/2 · Σ_{i<n} DF_i) / (1 + c_n/2)

Log discount factors are interpolated linearly between grid points (and from 1 at t = 0).
A key-rate bump adds 1bp × the tent weight of node k to every par yield and bootstraps again;
tenors below the first node load fully on it, beyond the last fully on the last. Times are in
years.
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

NODES = (2.0, 5.0, 7.0, 10.0, 15.0, 20.0, 25.0, 30.0)  # fixed key-rate grid (design 5.9)
BUMP = 1e-4


@dataclass(frozen=True)
class ParCurve:
    tenors: tuple[float, ...]  # years, increasing
    yields: tuple[float, ...]  # decimals

    @classmethod
    def from_points(cls, points: dict[float, float]) -> "ParCurve":
        t = sorted(points)
        return cls(tuple(t), tuple(points[x] for x in t))

    def par(self, t) -> np.ndarray:
        return np.interp(t, self.tenors, self.yields)


def tent(t) -> np.ndarray:
    """Weights on ``NODES`` for tenors ``t``: one row per node, one column per tenor."""
    t = np.clip(np.atleast_1d(np.asarray(t, dtype=float)), NODES[0], NODES[-1])
    return np.array([np.interp(t, NODES, np.eye(len(NODES))[k]) for k in range(len(NODES))])


def _bootstrap(par: np.ndarray) -> np.ndarray:
    df, total = np.empty(len(par)), 0.0
    for n, c in enumerate(par):
        df[n] = (1 - c / 2 * total) / (1 + c / 2)
        total += df[n]
    return df


def _discount(grid: np.ndarray, df: np.ndarray) -> Callable[[np.ndarray], np.ndarray]:
    x, y = np.r_[0.0, grid], np.r_[0.0, np.log(df)]
    return lambda t: np.exp(np.interp(t, x, y))


@dataclass(frozen=True)
class KeyRateCurves:
    """The base discount function and one per key-rate bump, out to ``tmax`` years."""

    base: Callable[[np.ndarray], np.ndarray]
    bumped: tuple[Callable[[np.ndarray], np.ndarray], ...]  # one per node in NODES


def key_rate_curves(curve: ParCurve, tmax: float = 31.0) -> KeyRateCurves:
    grid = np.arange(0.5, tmax + 0.25, 0.5)
    par = curve.par(grid)
    bumps = tent(grid) * BUMP
    return KeyRateCurves(_discount(grid, _bootstrap(par)),
                         tuple(_discount(grid, _bootstrap(par + b)) for b in bumps))
