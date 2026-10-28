"""Key-rate DV01s (design 5.9, Key rate DV01s; pure).

Par-curve tent bumps give each bond's shape: the fall in the present value of its cash flows
after the horizon for each node's bump, as shares of the total. The shares are scaled to the
bond's forward DV01 from the pricing function, so a bond's KRDs sum to its DV01 exactly. There is
no z-spread (a constant spread per bond so the curve reprices it, held fixed through the bumps):
the scaling sets the level, and the shape is taken at the curve's yields, a difference of about
0.02y for a bond 10bp off the curve (design 5.9). Low-coupon bonds have negative
short-tenor shares: their par-bond hedge is short there.

Futures KRDs are per 100 face of futures, like ``risk.dv01``: each bond's KRDs over its CF,
probability-weighted. Interval probabilities are replaced by their midpoints rescaled to sum to
1 (a point estimate: per-bucket ranges wouldn't add up to one profile).

Clusters group the bonds with a probability by key-rate profile (design 5.9), so the KRDs can be
shown per cluster as well as blended: the risk a switch would jump to.
"""

from dataclasses import dataclass
from datetime import date

import numpy as np

from ctd.bonds.schedule import coupon_dates
from ctd.curve.par import NODES, KeyRateCurves
from ctd.risk.dv01 import fill


def shares(coupon: float, maturity: date, horizon: date, curves: KeyRateCurves) -> np.ndarray:
    """Each node's share of the bond's par-curve key-rate sensitivity at ``horizon`` (sums to 1)."""
    dates = coupon_dates(maturity, horizon)
    t = np.array([(d - horizon).days / 365.25 for d in dates])
    cf = np.full(len(t), 100 * coupon / 2)
    cf[-1] += 100
    base = (cf * curves.base(t)).sum()
    fall = np.array([base - (cf * bumped(t)).sum() for bumped in curves.bumped])
    return fall / fall.sum()


def point_weights(probs: dict[str, tuple[float, float]]) -> dict[str, float]:
    """One probability per bond: interval midpoints, rescaled to sum to 1."""
    mids = {c: (lo + hi) / 2 for c, (lo, hi) in probs.items()}
    total = sum(mids.values())
    return {c: p / total for c, p in mids.items()}


def weighted(krds: dict[str, np.ndarray], weights: dict[str, float]) -> np.ndarray:
    """``Σ p_i · KRD_i`` over the bonds with a weight."""
    return sum(p * krds[c] for c, p in weights.items())


def effective_maturity(krd: np.ndarray) -> float:
    """DV01-weighted maturity on the key-rate grid, ``Σ KRD_k · T_k / Σ KRD_k``, in years."""
    return float((np.asarray(krd) * np.array(NODES)).sum() / np.sum(krd))


def effective_maturity_range(krds: dict[str, np.ndarray],
                             probs: dict[str, tuple[float, float]]) -> tuple[float, float]:
    """How far interval probabilities could move effective maturity: the mass not fixed by lower
    bounds given to the shortest bonds first, then the longest first. Close to the exact extremes
    (the ratio isn't linear in the probabilities, so not always exactly them)."""
    em = {c: effective_maturity(krds[c]) for c in probs}
    by_em = sorted(probs, key=em.get)
    out = [effective_maturity(weighted(krds, fill(probs, order))) for order in (by_em, by_em[::-1])]
    return min(out), max(out)


CLUSTER_DV01_TOLERANCE = 0.05  # bonds join a cluster within 5% of its first bond's DV01 (design 5.9)


@dataclass(frozen=True)
class Cluster:
    """Bonds with similar key-rate profiles: the same dominant node and DV01 within 5%."""

    node: float  # dominant key rate, years
    members: tuple[str, ...]
    prob: tuple[float, float]  # summed over members
    krd: np.ndarray  # the futures' KRDs if this cluster is delivered (members weighted by probability)


def clusters(krds: dict[str, np.ndarray], probs: dict[str, tuple[float, float]]) -> list[Cluster]:
    """Clusters of the bonds in ``probs`` (design 5.9), in order of effective maturity.

    Bonds are grouped by their largest KRD bucket, then, in order of DV01, a bond starts a new
    cluster when its DV01 is more than 5% above the cluster's first. Within a cluster, members
    are weighted by their probabilities (interval midpoints).
    """
    w = point_weights(probs)
    by_node: dict[float, list[str]] = {}
    for c in probs:
        by_node.setdefault(NODES[int(np.argmax(krds[c]))], []).append(c)
    out = []
    for node, bonds in by_node.items():
        groups: list[list[str]] = []
        for c in sorted(bonds, key=lambda c: krds[c].sum()):
            if groups and krds[c].sum() <= krds[groups[-1][0]].sum() * (1 + CLUSTER_DV01_TOLERANCE):
                groups[-1].append(c)
            else:
                groups.append([c])
        for g in groups:
            total = sum(w[c] for c in g)
            k = (sum(w[c] * krds[c] for c in g) / total if total > 0
                 else sum(krds[c] for c in g) / len(g))
            out.append(Cluster(node, tuple(g), (sum(probs[c][0] for c in g), sum(probs[c][1] for c in g)), k))
    return sorted(out, key=lambda cl: effective_maturity(cl.krd))
