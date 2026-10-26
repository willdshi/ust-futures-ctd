"""Shifted states and the duration profile (design 5.9; phase 1c item 4; pure).

The shift ``z`` (bp) moves every bond's forward yield in parallel (β = 1), and the Treasury par curve
with it for the key-rate shapes. A state centred at ``c`` has ``z ~ N(c, S²)``, with ``S`` the ATM
width to the horizon (``vol.atm``) and the same width at every centre (the remaining vol is kept).
With β = 1 the envelope and its switches don't move with ``c``, so every state is a reweighting of
one set of cells:

- The shift axis is cut into cells of at most ``step`` bp, with every switch point as an edge, so
  each cell has one CTD. The end cells reach ±∞.
- Each cell carries its CTD's futures DV01 (``DV01 / CF`` at the shifted forward yield) and KRDs
  (par-curve key-rate shares at the shifted curve, scaled to that DV01, ``risk.krd``), at its midpoint.
- A state's weights are each cell's exact normal mass, so the probabilities are exact differences
  of ``Φ`` between switch points, and the region-weighted DV01 and KRDs (design 5.9: each bond
  evaluated where it is CTD) are a midpoint rule within each region.

The CTD-based values at a centre are those of the single CTD at ``z = c``, evaluated there: the
staircase vendor systems show.
"""

from dataclasses import dataclass
from datetime import date

import numpy as np
from scipy.special import ndtr

from ctd.bonds.pricing import dv01
from ctd.curve.par import ParCurve, key_rate_curves
from ctd.model.envelope import BasketBond, Switch, envelope
from ctd.risk import krd

CENTRES_BP = 100  # the profile runs from −100 to +100bp (outputs.md chart 1)
TAIL_WIDTHS = 6.0  # cells reach this many (widest) widths beyond the outermost centre
STEP_BP = 1.0
VOL_BAND = 0.10  # vol ±10% bands (design 6, Tier 2)


@dataclass(frozen=True)
class Cells:
    edges: np.ndarray  # n + 1 increasing shifts in bp (the switch points among them); end cells reach ±∞
    cusips: tuple[str, ...]  # the CTD in each of the n cells
    dv01: np.ndarray  # n: futures DV01 per 100 face of futures (price points per bp)
    krd: np.ndarray  # n × len(NODES): futures KRDs, summing to dv01


def values(bonds: dict[str, BasketBond], horizon: date, par: ParCurve, z_bp: np.ndarray,
           cusips: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """``DV01 / CF`` and KRDs of bond ``cusips[j]`` at shift ``z_bp[j]``."""
    z = np.asarray(z_bp, dtype=float)
    d = np.empty(len(z))
    for c in set(cusips):
        b = bonds[c]
        at = np.array([x == c for x in cusips])
        d[at] = np.atleast_1d(dv01(b.coupon, b.maturity, horizon, b.fwd_yield + z[at] / 1e4)) / b.cf
    shapes = []
    for zj, c in zip(z, cusips):
        curves = key_rate_curves(ParCurve(par.tenors, tuple(y + zj / 1e4 for y in par.yields)))
        shapes.append(krd.shares(bonds[c].coupon, bonds[c].maturity, horizon, curves))
    return d, np.array(shapes) * d[:, None]


def cells(bonds: list[BasketBond], horizon: date, par: ParCurve, switches: list[Switch], lo_bp: float,
          hi_bp: float, step_bp: float = STEP_BP) -> Cells:
    """Cells from ``lo_bp`` to ``hi_bp``; ``switches`` are the envelope's over at least that range."""
    grid = np.arange(lo_bp, hi_bp + step_bp / 2, step_bp)
    edges = np.unique(np.r_[grid, [s.z_bp for s in switches if lo_bp < s.z_bp < hi_bp]])
    edges = edges[np.r_[True, np.diff(edges) > 1e-9]]
    mids = (edges[:-1] + edges[1:]) / 2
    _, ctd = envelope(bonds, horizon, mids)
    d, k = values({b.cusip: b for b in bonds}, horizon, par, mids, ctd)
    return Cells(edges, tuple(ctd), d, k)


def weights(c: Cells, centres, s_bp: float) -> np.ndarray:
    """Each cell's normal mass for a state centred at each of ``centres``: one row per centre."""
    e = np.asarray(c.edges, dtype=float)
    cdf = ndtr((e[None, :] - np.asarray(centres, dtype=float)[:, None]) / s_bp)
    cdf[:, 0], cdf[:, -1] = 0.0, 1.0  # the end cells take the tails
    return np.diff(cdf, axis=1)


@dataclass(frozen=True)
class States:
    """Region-weighted values and CTD-based values at each centre."""

    centres: np.ndarray  # bp
    width: float  # S, bp
    probs: dict[str, np.ndarray]  # per CUSIP, its probability of being CTD at each centre
    dv01: np.ndarray  # per centre, per 100 face of futures
    krd: np.ndarray  # centres × nodes
    label: tuple[str, ...]  # the CTD at z = c
    label_dv01: np.ndarray
    label_krd: np.ndarray

    @property
    def effective_maturity(self) -> np.ndarray:
        return np.array([krd.effective_maturity(k) for k in self.krd])

    @property
    def label_effective_maturity(self) -> np.ndarray:
        return np.array([krd.effective_maturity(k) for k in self.label_krd])

    @property
    def percentiles(self) -> np.ndarray:
        """Where each centre sits in today's distribution of the move to the horizon."""
        return ndtr(self.centres / self.width)


def states(c: Cells, bonds: list[BasketBond], horizon: date, par: ParCurve, centres, s_bp: float) -> States:
    centres = np.asarray(centres, dtype=float)
    w = weights(c, centres, s_bp)
    probs = {b: w[:, [x == b for x in c.cusips]].sum(axis=1) for b in sorted(set(c.cusips))}
    _, label = envelope(bonds, horizon, centres)
    ld, lk = values({b.cusip: b for b in bonds}, horizon, par, centres, label)
    return States(centres, s_bp, probs, w @ c.dv01, w @ c.krd, tuple(label), ld, lk)


@dataclass(frozen=True)
class Profile:
    """The duration profile across shifts, its ±1σ and ±2σ points, and vol ±10% bands (design 5.9)."""

    curve: States  # centres from −100 to +100bp
    points: States  # centres at −2σ, −1σ, 0, +1σ, +2σ
    band_dv01: tuple[np.ndarray, np.ndarray]  # region-weighted DV01 on ``curve.centres`` at width × 0.9, × 1.1

    POINTS = (-2, -1, 0, 1, 2)  # in σ

    def point(self, k: int) -> int:
        """Index in ``points`` of the state at ``k``σ."""
        return self.POINTS.index(k)


def profile(bonds: list[BasketBond], horizon: date, par: ParCurve, switches: list[Switch], s_bp: float,
            centres_bp: float = CENTRES_BP, step_bp: float = STEP_BP) -> Profile:
    """``switches`` must cover ±(``centres_bp`` + 2σ + ``TAIL_WIDTHS`` widths at vol +10%): see ``reach``."""
    span = reach(s_bp, centres_bp)
    c = cells(bonds, horizon, par, switches, -span, span, step_bp)
    centres = np.arange(-centres_bp, centres_bp + step_bp / 2, step_bp)
    curve = states(c, bonds, horizon, par, centres, s_bp)
    points = states(c, bonds, horizon, par, [k * s_bp for k in Profile.POINTS], s_bp)
    band = tuple(weights(c, centres, s_bp * f) @ c.dv01 for f in (1 - VOL_BAND, 1 + VOL_BAND))
    return Profile(curve, points, band)


def reach(s_bp: float, centres_bp: float = CENTRES_BP) -> float:
    """How far the cells (and the switches) must reach either side of 0, in bp."""
    return float(np.ceil(max(centres_bp, 2 * s_bp) + TAIL_WIDTHS * s_bp * (1 + VOL_BAND)))
