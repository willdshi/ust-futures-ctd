"""The light model for one contract and one date (design 5.11; pure).

Inputs are what ``ctd run`` reads from the store: the TCF basket and CFs, TreasuryDirect clean
prices, the futures settlement, SOFR (the latest fixing, the month's fixings so far and the SR1
strip) and the contract's quarterly options. Repo is the SR1 strip (``funding.strip``, 5.3 path 3)
when it covers the last delivery day, else flat at the latest SOFR, with a warning. Steps:

1. Forward clean price of each bond to the first and last delivery days at that repo; the
   horizon is the last day if the basket's probability-weighted carry is positive, the first if
   negative (``model.horizon``), weighted by steps 2–4 run with the envelope at the last day, and
   with a warning if flat SOFR would pick the other day. Forward yields at the horizon.
2. Switch points by parallel shifts of the forward yields (``model.envelope``), each recentred
   onto the market settlement, ``K_k = F_market + E(z_k) − E(0)``.
3. A digital at each ``K_k`` from the options (``vol.digitals``), discounted at that repo from
   settlement to expiry.
4. Probabilities per bond (``model.probabilities``).
5. Futures DV01 at z = 0, probability-weighted and CTD-based (``risk.dv01``), and key-rate DV01s from
   par-curve bumps scaled to each bond's DV01 (``risk.krd``), with effective maturity.
6. ATM vol of the same options (``vol.atm``), converted to yield vol with the CTD's DV01/CF: the
   width of the shift distribution to the horizon, each switch's distance in σ, and its normal tail
   at the width to option expiry, comparable with its digital (the gap is skew, phase 1c item 3).
7. Shifted states with that width (``model.profile``): the duration profile from −100 to +100bp,
   its ±1σ and ±2σ points and vol ±10% bands, with normal probabilities and region-weighted DV01
   and KRDs, each bond evaluated where it is CTD (phase 1c item 4). Its state at 0 is the headline
   DV01; step 5's weighting at z = 0 with the option-implied probabilities is the cross-check.

``F_market − E(0)`` is reported as the recentring gap: the net basis the model holds constant
(delivery options, specialness, the timing of the price snapshots).
"""

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from ctd.bonds.forward import forward_clean, forward_yield
from ctd.curve.par import ParCurve, key_rate_curves
from ctd.data.cme_bulletin import OptionSettle
from ctd.data.td_prices import BondPrice
from ctd.funding import strip
from ctd.funding.repo import Growth, flat
from ctd.model import profile as pf
from ctd.model.envelope import BasketBond, Switch, envelope, switches
from ctd.model.horizon import light_horizon, weighted_carry
from ctd.model.probabilities import Probabilities, assemble, strike
from ctd.reference.calendar import BusinessCalendar
from ctd.reference.options import OptionExpiry
from ctd.risk import dv01, krd
from ctd.vol import atm
from ctd.vol.digitals import Digital, digital


EM_WARN_YEARS = 0.05  # warn when interval probabilities could move effective maturity by more


@dataclass(frozen=True)
class LightInputs:
    contract: str  # "ZBZ6"
    asof: date
    settle: date  # T+1
    first_delivery: date
    last_delivery: date
    cfs: dict[str, float]  # the TCF basket: CUSIP -> CF
    prices: dict[str, BondPrice]  # TreasuryDirect, any CUSIPs (the basket's are used)
    f_market: float
    sofr: float  # decimal
    sofr_date: date
    expiry: OptionExpiry  # the quarterly option on the contract
    chain: list[OptionSettle]  # its settlements, both rights
    repo_cal: BusinessCalendar  # sifma
    face: float  # contract unit, $ face per contract
    par_curve: ParCurve  # Treasury par curve, latest on or before asof
    par_date: date
    sr1: dict[date, float] = field(default_factory=dict)  # SR1 month -> implied average (100 − settle) / 100
    fixings: dict[date, float] = field(default_factory=dict)  # SOFR dated on or before asof, this month on


@dataclass(frozen=True)
class Repo:
    path: str  # "sr1" (the strip, 5.3 path 3) or "flat" (path 1)
    term: float  # term rate from settlement to the horizon, actual/360 simple
    months: dict[date, float]  # the strip's overnight rate per month; empty when flat
    why_flat: str | None  # why the strip wasn't used


@dataclass(frozen=True)
class Delivery:
    """The delivery window and the carry that picks the horizon (``model.horizon``)."""

    first: date
    last: date
    carry: float  # probability-weighted carry, converted, price points per 100 face of futures
    carry_flat: float  # the same at flat SOFR
    weights: dict[str, float]  # the probabilities it's weighted by (option digitals, envelope at the last day)
    carry_by_bond: dict[str, float]  # each weighted bond's converted forward, first day minus last


@dataclass(frozen=True)
class BasketRow:
    cusip: str
    coupon: float
    maturity: date
    cf: float
    price: float  # today's clean
    price_from: str  # "eod", "mid" or "sell"
    fwd: float  # forward clean at the horizon
    fwd_yield: float
    converted: float  # fwd / cf
    dv01_cf: float  # forward DV01 / CF: price points per bp per 100 face of futures
    krd_shares: tuple[float, ...]  # each key-rate node's share of dv01_cf (sums to 1)

    @property
    def krd(self) -> np.ndarray:
        """Key-rate DV01s over CF, per 100 face of futures."""
        return np.array(self.krd_shares) * self.dv01_cf

    @property
    def carry(self) -> float:
        """Price points earned holding the bond to the horizon (today's price − forward)."""
        return self.price - self.fwd


@dataclass(frozen=True)
class Crossover:
    switch: Switch
    strike: float  # K_k
    digital: Digital
    sigmas: float  # z_k over the width to the horizon (signed)
    normal: float  # normal tail beyond z_k at the width to option expiry, comparable with the digital


@dataclass(frozen=True)
class LightResult:
    contract: str
    asof: date
    settle: date
    horizon: date
    horizon_reason: str
    delivery: Delivery
    sofr: float
    sofr_date: date
    repo: Repo
    f_market: float
    e0: float
    expiry: OptionExpiry
    df: float
    basket: tuple[BasketRow, ...]  # by maturity
    crossovers: tuple[Crossover, ...]  # in increasing z
    probabilities: Probabilities
    dv01: tuple[float, float]  # probability-weighted, per 100 face of futures (lo, hi)
    ctd_dv01: float  # CTD-based, per 100 face of futures
    face: float  # contract unit
    krd: np.ndarray  # probability-weighted key-rate DV01s per 100 face of futures (interval midpoints)
    ctd_krd: np.ndarray  # CTD-based
    par_date: date
    clusters: tuple[krd.Cluster, ...]  # bonds with a probability, by key-rate profile
    vol: atm.AtmVol
    yield_vol: float  # bp per √year, through the CTD's DV01/CF
    t_horizon: float  # years from the as-of date to the horizon
    profile: pf.Profile  # shifted states with the width to the horizon
    warnings: tuple[str, ...]

    @property
    def effective_maturity(self) -> float:
        return krd.effective_maturity(self.krd)

    @property
    def ctd_effective_maturity(self) -> float:
        return krd.effective_maturity(self.ctd_krd)

    @property
    def width(self) -> float:
        """Width of the shift distribution to the horizon, bp."""
        return atm.width(self.yield_vol, self.t_horizon)

    @property
    def expiry_width(self) -> float:
        """Width to option expiry, bp."""
        return atm.width(self.yield_vol, self.vol.t)

    def nearest(self) -> dict[str, Crossover | None]:
        """The first switch on each side (``"rally"``, ``"selloff"``), None if there is none in range."""
        return {"rally": max((c for c in self.crossovers if c.switch.z_bp < 0), key=lambda c: c.switch.z_bp,
                             default=None),
                "selloff": min((c for c in self.crossovers if c.switch.z_bp > 0), key=lambda c: c.switch.z_bp,
                               default=None)}

    @property
    def gap(self) -> float:
        """Recentring gap ``F_market − E(0)``, in price points."""
        return self.f_market - self.e0


def run(x: LightInputs) -> LightResult:
    warnings = []
    if x.expiry.expiry <= x.asof:
        raise ValueError(f"{x.expiry.label} options expired {x.expiry.expiry}; the light model stops "
                         f"at option expiry (design 10, phase 1b D)")
    missing = sorted(set(x.cfs) - set(x.prices))
    if missing:
        warnings.append(f"no TreasuryDirect price for {', '.join(missing)}: left out of the basket")
    cusips = sorted((c for c in x.cfs if c in x.prices), key=lambda c: (x.prices[c].maturity, c))
    if not cusips:
        raise ValueError(f"no basket bond of {x.contract} has a price on {x.asof}")
    not_eod = [c for c in cusips if x.prices[c].price_from != "eod"]
    if not_eod:
        warnings.append(f"provisional prices (no end of day) for {', '.join(not_eod)}")

    if x.par_date != x.asof:
        warnings.append(f"par curve is from {x.par_date}, not {x.asof} (none published for {x.asof})")
    if x.sofr_date < x.repo_cal.latest_business_day(x.asof):
        warnings.append(f"latest SOFR is {x.sofr_date}'s, not {x.asof}'s: it is published the next morning, "
                        f"so run again once the next NY Fed file is stored")
    g_flat = flat(x.sofr, x.repo_cal)
    try:
        s = strip.solve(x.sr1, x.fixings, x.repo_cal.prev_business_day(x.last_delivery), x.repo_cal)
        g, months, why_flat = s.growth(x.repo_cal), s.rates, None
    except ValueError as e:
        g, months, why_flat = g_flat, {}, str(e)
        warnings.append(f"repo flat at SOFR {x.sofr:.4%}, not the SR1 strip: {e}")
    curves = key_rate_curves(x.par_curve)

    def fwd(c: str, delivery: date, g: Growth = g) -> float:
        p = x.prices[c]
        return forward_clean(p.price, p.coupon, p.maturity, x.settle, delivery, g)

    df = 1 / g(x.settle, x.expiry.expiry)
    chain = [o for o in x.chain if o.product == x.expiry.product and o.label == x.expiry.label]
    if not chain:
        raise ValueError(f"no {x.expiry.product} {x.expiry.label} options in the bulletin for {x.asof}")

    def at(horizon: date):
        """Steps 1–4 with forwards to ``horizon``: basket rows, E(0), today's CTD, the switches,
        their strikes and digitals, and the option-implied probabilities."""
        rows = []
        for c in cusips:
            p = x.prices[c]
            y = forward_yield(p.price, p.coupon, p.maturity, x.settle, horizon, g)
            f = fwd(c, horizon)
            rows.append(BasketRow(c, p.coupon, p.maturity, x.cfs[c], p.price, p.price_from, f, y, f / x.cfs[c],
                                  dv01.per_futures(p.coupon, p.maturity, horizon, y, x.cfs[c]),
                                  tuple(krd.shares(p.coupon, p.maturity, horizon, curves))))
        bonds = [BasketBond(r.cusip, r.coupon, r.maturity, r.cf, r.fwd_yield) for r in rows]
        e, ctd = envelope(bonds, horizon, 0)
        e0, ctd0 = float(e[0]), ctd[0]
        sws = switches(bonds, horizon)  # the crossover table's range, −100 to +150bp
        digs = [(sw, k, digital(chain, k, x.f_market, df)) for sw in sws for k in [strike(sw, x.f_market, e0)]]
        return rows, bonds, e0, ctd0, sws, digs, assemble(ctd0, sws, [d for _, _, d in digs])

    # The date: probability-weighted carry, weighted by the option-implied probabilities with the
    # envelope at the last delivery day (model.horizon; decisions.md, Delivery date for the light
    # model's forward prices).
    stage = at(x.last_delivery)
    weights = krd.point_weights(stage[6].by_bond())

    def carry(g: Growth) -> tuple[float, dict[str, float]]:
        conv = {d: {c: fwd(c, d, g) / x.cfs[c] for c in weights} for d in (x.first_delivery, x.last_delivery)}
        by_bond = {c: conv[x.first_delivery][c] - conv[x.last_delivery][c] for c in weights}
        return weighted_carry(weights, conv[x.first_delivery], conv[x.last_delivery]), by_bond

    (c_repo, by_bond), (c_flat, _) = carry(g), carry(g_flat)
    horizon = light_horizon(x.first_delivery, x.last_delivery, c_repo)
    reason = (f"{'positive' if horizon == x.last_delivery else 'negative'} probability-weighted carry, "
              f"{c_repo * 32:+.2f}/32 of converted price from {x.first_delivery} to {x.last_delivery}")
    flat_horizon = light_horizon(x.first_delivery, x.last_delivery, c_flat)
    if months and flat_horizon != horizon:
        warnings.append(f"carry sign depends on the repo path: flat SOFR would put the horizon on {flat_horizon}")
    if horizon != x.last_delivery:
        stage = at(horizon)
    rows, bonds, e0, ctd0, sws, digs, probs = stage
    repo = Repo("sr1" if months else "flat", (g(x.settle, horizon) - 1) * 360 / (horizon - x.settle).days,
                months, why_flat)
    per = {r.cusip: r.dv01_cf for r in rows}
    t_h = atm.years(x.asof, horizon)
    vol = atm.atm(chain, x.f_market, df, atm.years(x.asof, x.expiry.expiry))
    warnings += [f"ATM vol: {f}" for f in vol.flags]
    sigma_y = atm.yield_vol(vol.price_vol, per[ctd0])
    s_h, s_e = atm.width(sigma_y, t_h), atm.width(sigma_y, vol.t)
    span = pf.reach(s_h)
    prof = pf.profile(bonds, horizon, x.par_curve, switches(bonds, horizon, -span, span), s_h)
    crossovers = []
    for sw, k, d in digs:
        crossovers.append(Crossover(sw, k, d, sw.z_bp / s_h, atm.normal_tail(sw.z_bp, s_e)))
        warnings += [f"switch at {sw.z_bp:+.1f}bp (K {k:.3f}): {f}" for f in d.flags]
    warnings += probs.warnings
    krds = {r.cusip: r.krd for r in rows}
    by_bond = probs.by_bond()
    em_lo, em_hi = krd.effective_maturity_range(krds, by_bond)
    if em_hi - em_lo > EM_WARN_YEARS:
        warnings.append(f"KRDs use interval midpoints of the probabilities; effective maturity could be "
                        f"{em_lo:.2f}–{em_hi:.2f}y")
    delivery = Delivery(x.first_delivery, x.last_delivery, c_repo, c_flat, weights, by_bond)
    return LightResult(x.contract, x.asof, x.settle, horizon, reason, delivery, x.sofr, x.sofr_date, repo, x.f_market, e0,
                       x.expiry, df, tuple(rows), tuple(crossovers), probs,
                       dv01.weighted(per, by_bond), per[ctd0], x.face,
                       krd.weighted(krds, krd.point_weights(by_bond)), krds[ctd0], x.par_date,
                       tuple(krd.clusters(krds, by_bond)), vol, sigma_y, t_h, prof, tuple(warnings))
