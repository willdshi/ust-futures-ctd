"""CTD probabilities from the switch points and their digitals (design 5.11 steps 2 and 4; pure).

Each switch ``z_k`` is recentred onto the market futures settlement, ``K_k = F_market + E(z_k) − E(0)``,
and its digital read there (``ctd.vol.digitals``): ``P(F < K_k)`` for a switch on the sell-off side
(z > 0), ``P(F > K_k)`` on the rally side (z < 0). On each side, counting outward from z = 0, the
bond beyond switch k gets ``D_k − D_{k+1}`` and the bond beyond the last switch its full tail
``D_n``; the current CTD gets the remainder, ``1 − D_1(sell-off) − D_1(rally)``.

A digital that is only an upper bound (cabinet, minimum-tick or floor settlements) is the
interval [0, bound]; a missing one (beyond the listed strikes) is [0, the next digital inward].
A bound is also capped at the digital inward; both hold if digitals fall with distance. Every probability is therefore an interval ``[lo, hi]``,
a point when ``lo == hi``. Negative regions are clipped to 0, with a warning when digitals rise
with distance or the probabilities no longer bracket 1.
"""

from dataclasses import dataclass

from ctd.model.envelope import Switch
from ctd.vol.digitals import Digital


@dataclass(frozen=True)
class Region:
    """The bond that is CTD beyond ``switch`` (on ``side`` "rally" or "selloff"), or the current
    CTD (``side="ctd"``, no switch), with probability between ``lo`` and ``hi``."""

    cusip: str
    side: str
    lo: float
    hi: float
    switch: Switch | None = None
    digital: Digital | None = None

    @property
    def point(self) -> bool:
        return self.lo == self.hi


@dataclass(frozen=True)
class Probabilities:
    ctd: str
    regions: tuple[Region, ...]  # rally side outermost first, then the CTD, then sell-off outward
    warnings: tuple[str, ...]

    def by_bond(self) -> dict[str, tuple[float, float]]:
        """``(lo, hi)`` per CUSIP, summed over its regions (a bond can be CTD in more than one)."""
        out: dict[str, tuple[float, float]] = {}
        for r in self.regions:
            lo, hi = out.get(r.cusip, (0.0, 0.0))
            out[r.cusip] = (lo + r.lo, hi + r.hi)
        return out


def strike(switch: Switch, f_market: float, e0: float) -> float:
    """``K_k``: the futures price at the switch, recentred onto the market settlement."""
    return f_market + switch.envelope - e0


def _interval(d: Digital, inner_hi: float) -> tuple[float, float]:
    if d.prob is None:
        return 0.0, inner_hi
    return (0.0, min(d.prob, inner_hi)) if d.upper_bound else (d.prob, d.prob)


def _side(name: str, ctd: str, pairs: list[tuple[Switch, Digital]], warnings: list[str]) -> list[Region]:
    """Regions on one side, innermost first; ``pairs`` are ordered outward from z = 0."""
    want = "below" if name == "selloff" else "above"
    cur, inner_hi, bands = ctd, 1.0, []
    for sw, d in pairs:
        start, beyond = (sw.from_cusip, sw.to_cusip) if name == "selloff" else (sw.to_cusip, sw.from_cusip)
        if start != cur:
            raise ValueError(f"switch at {sw.z_bp:+.1f}bp starts from {start}, not {cur}")
        if d.side != want:
            raise ValueError(f"{name} switch at {sw.z_bp:+.1f}bp needs a digital {want} K, got {d.side}")
        lo, hi = _interval(d, inner_hi)
        if d.prob is None:
            warnings.append(f"switch at {sw.z_bp:+.1f}bp: no digital (beyond listed strikes), "
                            f"bounded by the switch inward")
        bands.append((beyond, lo, hi, sw, d))
        cur, inner_hi = beyond, hi

    regions = []
    for k, (cusip, lo, hi, sw, d) in enumerate(bands):
        next_lo, next_hi = (bands[k + 1][1], bands[k + 1][2]) if k + 1 < len(bands) else (0.0, 0.0)
        if next_lo > hi + 1e-12:
            warnings.append(f"digital rises with distance at {bands[k + 1][3].z_bp:+.1f}bp "
                            f"({next_lo:.3f} > {hi:.3f}); region beyond {sw.z_bp:+.1f}bp clipped to 0")
        regions.append(Region(cusip, name, max(0.0, lo - next_hi), max(0.0, hi - next_lo), sw, d))
    return regions


def assemble(ctd: str, switches: list[Switch], digitals: list[Digital]) -> Probabilities:
    """Probabilities per region; ``digitals[i]`` is read at ``strike(switches[i], ...)``.

    ``ctd`` is the cheapest bond at z = 0; switches at z < 0 are on the rally side, z > 0 on the
    sell-off side.
    """
    if len(switches) != len(digitals):
        raise ValueError("one digital per switch")
    pairs = sorted(zip(switches, digitals), key=lambda p: p[0].z_bp)
    warnings: list[str] = []
    rally = _side("rally", ctd, [p for p in reversed(pairs) if p[0].z_bp < 0], warnings)
    selloff = _side("selloff", ctd, [p for p in pairs if p[0].z_bp > 0], warnings)

    # the whole tail of a side is its innermost digital, D_1
    d1 = [_interval(s[0].digital, 1.0) if s else (0.0, 0.0) for s in (rally, selloff)]
    lo, hi = 1.0 - d1[0][1] - d1[1][1], 1.0 - d1[0][0] - d1[1][0]
    if hi < 0:
        warnings.append(f"tails sum to {d1[0][0] + d1[1][0]:.3f} > 1; CTD clipped to 0")
    regions = (*reversed(rally), Region(ctd, "ctd", max(0.0, lo), max(0.0, hi)), *selloff)

    total_lo, total_hi = sum(r.lo for r in regions), sum(r.hi for r in regions)
    if not total_lo - 1e-9 <= 1 <= total_hi + 1e-9:
        warnings.append(f"probabilities sum to {total_lo:.3f}" if total_lo == total_hi
                        else f"probabilities sum to {total_lo:.3f}–{total_hi:.3f}, not bracketing 1")
    return Probabilities(ctd, regions, tuple(warnings))
