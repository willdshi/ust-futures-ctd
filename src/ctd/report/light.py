"""Text output of a light-model run (design 5.11, roadmap 1b.B5): the basket and crossover tables."""

from ctd.curve.par import NODES
from ctd.model.light import LightResult
from ctd.risk.dv01 import dollars
from ctd.risk.krd import effective_maturity


def prob(lo: float, hi: float) -> str:
    """``19.4%`` for a point, ``≤ 3.1%`` for an upper bound, ``27.0–30.0%`` for an interval."""
    if abs(hi - lo) < 5e-4:
        return f"{lo:.1%}"
    if lo < 5e-4:
        return f"≤ {hi:.1%}"
    return f"{lo * 100:.1f}–{hi:.1%}"


def money(lo: float, hi: float) -> str:
    """``$121,400`` for a point, ``$118,200–121,400`` for a range (rounded to $100 or $1)."""
    if max(abs(lo), abs(hi)) >= 10_000:
        lo, hi = round(lo, -2), round(hi, -2)
    else:
        lo, hi = round(lo), round(hi)
    return f"${lo:,.0f}" if lo == hi else f"${lo:,.0f}–{hi:,.0f}"


def _row(cells, widths) -> str:
    return "  ".join(f"{c:<{w}}" if i < 2 else f"{c:>{w}}" for i, (c, w) in enumerate(zip(cells, widths))).rstrip()


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header))]
    return [_row(header, widths), _row(["-" * w for w in widths], widths), *(_row(r, widths) for r in rows)]


def _k(v: float) -> str:
    """A DV01 per 100 face of futures as $k per $100mm."""
    return f"{dollars(v) / 1000:,.1f}"


STATE = {-2: "−2σ", -1: "−1σ", 0: "today", 1: "+1σ", 2: "+2σ"}


def _distance(side: str, c) -> str:
    if c is None:
        return f"{side} none in range"
    return f"{side} {c.switch.z_bp:+.1f}bp ({abs(c.sigmas):.2f}σ{', below 1σ' if abs(c.sigmas) < 1 else ''})"


def _repo(r: LightResult) -> str:
    sofr = f"SOFR {r.sofr:.4%} ({r.sofr_date})"
    if r.repo.path == "flat":
        return f"repo: flat {sofr}, {r.repo.term:.4%} to the horizon"
    months = ", ".join(f"{m:%b} {v:.3%}" for m, v in r.repo.months.items())
    return f"repo: SR1 strip, {r.repo.term:.4%} to the horizon ({months}); latest {sofr}"


NEXT_CHEAPEST = 3  # bonds listed beyond those with a probability: the cheapest of the rest at z = 0


def traded(strikes_used, traded_strikes) -> str:
    """Which of the strikes behind a digital or the ATM vol traded that day: ``"all"``, ``"none"``
    or the strikes that did (design 3.1, Strikes with no open interest are kept)."""
    if not strikes_used:
        return "-"
    if not traded_strikes:
        return "none"
    return "all" if set(traded_strikes) == set(strikes_used) else " ".join(f"{s:g}" for s in traded_strikes)


def format_line(r: LightResult) -> str:
    """One line per run for ``ctd history``: the CTD and its probability, today's DV01 against the
    CTD-based, the recentring gap, the nearest switch each side and the number of warnings."""
    lo, hi = r.probabilities.by_bond().get(r.probabilities.ctd, (0.0, 0.0))
    p = f"{lo:.0%}" if round(lo, 2) == round(hi, 2) else f"{lo:.0%}–{hi:.0%}"
    dv01 = r.profile.points.dv01[r.profile.point(0)]
    near = r.nearest()
    switch = "/".join(f"{c.switch.z_bp:+.0f}bp" if c else "none" for c in (near["rally"], near["selloff"]))
    return (f"{r.asof}  {r.contract}  CTD {r.probabilities.ctd} {p:>7}  DV01 {money(dollars(dv01), dollars(dv01))} "
            f"(CTD-based {money(dollars(r.ctd_dv01), dollars(r.ctd_dv01))})  gap {r.gap * 32:+.1f}/32  "
            f"switches {switch}  {len(r.warnings)} warning(s)")


def format_run(r: LightResult, all_bonds: bool = False) -> str:
    """The run as text. The basket lists the bonds with a probability and the next few cheapest
    (``NEXT_CHEAPEST``), or every bond with ``all_bonds``."""
    p = r.probabilities
    by_bond = p.by_bond()
    pts, curve = r.profile.points, r.profile.curve
    today, i0 = r.profile.point(0), int(abs(curve.centres).argmin())
    normal = {c: float(v[today]) for c, v in pts.probs.items() if v[today] >= 5e-4}
    shown = set(by_bond) | set(normal)
    rest = sorted((b for b in r.basket if b.cusip not in shown), key=lambda b: b.converted)
    shown |= {b.cusip for b in rest[:NEXT_CHEAPEST]}
    basket = r.basket if all_bonds else [b for b in r.basket if b.cusip in shown]
    lines = [
        f"{r.contract} as of {r.asof} (settlement {r.settle})",
        f"horizon {r.horizon}: {r.horizon_reason}",
        _repo(r),
        f"options: {r.expiry.product} {r.expiry.label}, expiry {r.expiry.expiry}, DF {r.df:.6f}",
        f"futures settlement {r.f_market:.4f}, envelope E(0) {r.e0:.4f}, "
        f"recentring gap {r.gap:+.4f} ({r.gap * 32:+.1f}/32)",
        f"futures DV01 per bp: {money(*[dollars(pts.dv01[today])] * 2)} per $100mm "
        f"({money(*[dollars(pts.dv01[today], r.face)] * 2)} per contract), region-weighted (normal, ATM width; "
        f"vol ±10%: {money(*(dollars(b[i0]) for b in r.profile.band_dv01))}); "
        f"{money(*(dollars(v) for v in r.dv01))} at today's yields with the option-implied probabilities; "
        f"CTD-based {money(dollars(r.ctd_dv01), dollars(r.ctd_dv01))} ({money(*[dollars(r.ctd_dv01, r.face)] * 2)})",
        f"ATM vol: {r.vol.price_vol:.2f} points per √year (put {r.vol.strikes[0]:g} {r.vol.vols[0]:.2f}, "
        f"call {r.vol.strikes[1]:g} {r.vol.vols[1]:.2f}; traded that day: {traded(r.vol.strikes, r.vol.traded)}), "
        f"{r.yield_vol:.1f}bp per √year through the CTD's DV01/CF; "
        f"width {r.width:.1f}bp to the horizon, {r.expiry_width:.1f}bp to option expiry",
        "distance to switch: " + "; ".join(_distance(side, c) for side, c in r.nearest().items()),
        "",
        f"Basket of {len(r.basket)} (forwards at the horizon, CTD at z = 0 marked *; DV01/CF per $100mm)",
    ]
    rows = []
    for b in basket:
        lo, hi = by_bond.get(b.cusip, (0.0, 0.0))
        rows.append([b.cusip + (" *" if b.cusip == p.ctd else ""), f"{b.coupon * 100:.3f} {b.maturity}",
                     f"{b.cf:.4f}", f"{b.price:.4f}" + ("" if b.price_from == "eod" else f" ({b.price_from})"),
                     f"{b.fwd:.4f}", f"{b.fwd_yield:.4%}", f"{b.carry:+.4f}", f"{b.converted:.4f}",
                     f"{dollars(b.dv01_cf) / 1000:,.1f}",
                     prob(lo, hi) if b.cusip in by_bond else "",
                     f"{normal[b.cusip]:.1%}" if b.cusip in normal else ""])
    lines += _table(["cusip", "coupon maturity", "cf", "price", "fwd", "fwd yield", "carry", "converted",
                     "DV01/CF $k", "P(CTD)", "P normal"],
                    rows)
    lines.append("(P(CTD) from the option digitals, measured at option expiry; P normal from the ATM normal "
                 "factor at the horizon, which spreads further. Both read CME settlement prices, which come off "
                 "CME's skew for the expiry whether or not a strike traded: see 'traded' in the crossovers)")
    if len(basket) < len(r.basket):
        lines.append(f"(bonds with a probability and the next {NEXT_CHEAPEST} cheapest; "
                     f"{len(r.basket) - len(basket)} more with --all-bonds)")

    lines += ["", f"Key-rate DV01 per $100mm, $k (par curve of {r.par_date}; can be negative)"]
    rows = [[name, *(f"{dollars(v) / 1000:,.1f}" for v in k), f"{dollars(k.sum()) / 1000:,.1f}", f"{m:.1f}y"]
            for name, k, m in (("region-weighted (normal)", pts.krd[today], pts.effective_maturity[today]),
                               ("option-implied at z = 0", r.krd, r.effective_maturity),
                               ("CTD-based", r.ctd_krd, r.ctd_effective_maturity))]
    lines += _table(["", *(f"{n:g}y" for n in NODES), "total", "eff. maturity"], rows)

    lines += ["", f"Shifted states (normal factor, β = 1, width {r.width:.1f}bp to the horizon; percentile of "
                  f"today's distribution of the move; DV01 $k per $100mm)"]
    rows = [[STATE[k], f"{pts.centres[j]:+.1f}", f"{pts.percentiles[j]:.1%}", pts.label[j], _k(pts.dv01[j]),
             _k(pts.label_dv01[j]), f"{pts.effective_maturity[j]:.1f}y", f"{pts.label_effective_maturity[j]:.1f}y"]
            for j, k in enumerate(r.profile.POINTS)]
    lines += _table(["state", "shift bp", "pct", "CTD at shift", "DV01", "CTD-based", "eff. maturity",
                     "CTD-based eff. maturity"], rows)
    lines += ["", "Change in key-rate DV01 from today, $k per $100mm"]
    rows = []
    for k in (-2, -1, 1, 2):
        j = r.profile.point(k)
        rows += [[STATE[k], *(_k(v) for v in pts.krd[j] - pts.krd[today]), _k(pts.dv01[j] - pts.dv01[today])],
                 [f"{STATE[k]} CTD-based", *(_k(v) for v in pts.label_krd[j] - pts.label_krd[today]),
                  _k(pts.label_dv01[j] - pts.label_dv01[today])]]
    lines += _table(["", *(f"{n:g}y" for n in NODES), "total"], rows)

    lines += ["", "Clusters (same dominant key rate, DV01 within 5%): key-rate DV01 if delivered, $k per $100mm"]
    rows = [[f"{cl.node:g}y: {', '.join(cl.members)}", prob(*cl.prob), *(f"{dollars(v) / 1000:,.1f}" for v in cl.krd),
             f"{dollars(cl.krd.sum()) / 1000:,.1f}", f"{effective_maturity(cl.krd):.1f}y"] for cl in r.clusters]
    lines += _table(["cluster", "P", *(f"{n:g}y" for n in NODES), "total", "eff. maturity"], rows)

    lines += ["", "Crossovers (as yields rise; K = futures price at the switch; σ = distance over the width to the "
                  "horizon; normal = ATM normal tail at option expiry, to compare with the digital; traded = the "
                  "digital's strikes that traded that day: with none it rests on CME's skew from other strikes, "
                  "so treat it as indicative, as any digital beyond about 1.5σ)"]
    region = {id(reg.switch): reg for reg in p.regions if reg.switch is not None}
    rows = []
    for c in r.crossovers:
        sw, d = c.switch, c.digital
        reg = region[id(sw)]
        rows.append([f"{sw.from_cusip} → {sw.to_cusip}", reg.side, f"{sw.z_bp:+.1f}", f"{c.sigmas:+.2f}",
                     f"{c.strike:.4f}", f"{c.strike - r.f_market:+.4f}",
                     " ".join(f"{s:g}" for s in d.strikes_used) or "-",
                     ("P(F<K) " if d.side == "below" else "P(F>K) ")
                     + ("-" if d.prob is None else ("≤ " if d.upper_bound else "") + f"{d.prob:.1%}"),
                     traded(d.strikes_used, d.traded), f"{c.normal:.1%}", f"{reg.cusip} {prob(reg.lo, reg.hi)}"])
    lines += _table(["from → to", "side", "z bp", "σ", "K", "K − F", "strikes", "digital", "traded", "normal",
                     "beyond"],
                    rows) \
        if rows else ["(no switches between -100 and +150bp)"]

    [kept] = [reg for reg in p.regions if reg.side == "ctd"]
    lines += ["", f"{p.ctd} (CTD) keeps {prob(kept.lo, kept.hi)}"]
    if r.warnings:
        lines += ["", "Warnings", *(f"- {w}" for w in r.warnings)]
    return "\n".join(lines)
