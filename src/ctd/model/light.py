"""The light model for one contract and one date (design 5.11; pure).

Inputs are what ``ctd run`` reads from the store: the TCF basket and CFs, TreasuryDirect clean
prices, the futures settlement, the latest SOFR and the contract's quarterly options. Steps:

1. Forward clean price of each bond to the first and last delivery days at flat SOFR; the
   horizon is the last day if the CTD's carry is positive, the first if negative
   (``model.horizon``). Forward yields at the horizon.
2. Switch points by parallel shifts of the forward yields (``model.envelope``), each recentred
   onto the market settlement, ``K_k = F_market + E(z_k) − E(0)``.
3. A digital at each ``K_k`` from the options (``vol.digitals``), discounted at flat SOFR from
   settlement to expiry.
4. Probabilities per bond (``model.probabilities``).
5. Futures DV01 at z = 0, probability-weighted and CTD-label (``risk.dv01``), and key-rate DV01s from
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

from dataclasses import dataclass
from datetime import date

import numpy as np

from ctd.bonds.forward import forward_clean, forward_yield
from ctd.curve.par import ParCurve, key_rate_curves
from ctd.data.cme_bulletin import OptionSettle
from ctd.data.td_prices import BondPrice
from ctd.funding.repo import flat
from ctd.model import profile as pf
from ctd.model.envelope import BasketBond, Switch, envelope, switches
from ctd.model.horizon import light_horizon
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
    sofr: float
    sofr_date: date
    f_market: float
    e0: float
    expiry: OptionExpiry
    df: float
    basket: tuple[BasketRow, ...]  # by maturity
    crossovers: tuple[Crossover, ...]  # in increasing z
    probabilities: Probabilities
    dv01: tuple[float, float]  # probability-weighted, per 100 face of futures (lo, hi)
    ctd_dv01: float  # CTD-label, per 100 face of futures
    face: float  # contract unit
    krd: np.ndarray  # probability-weighted key-rate DV01s per 100 face of futures (interval midpoints)
    ctd_krd: np.ndarray  # CTD-label
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
    g = flat(x.sofr, x.repo_cal)
    curves = key_rate_curves(x.par_curve)

    def fwd(c: str, delivery: date) -> float:
        p = x.prices[c]
        return forward_clean(p.price, p.coupon, p.maturity, x.settle, delivery, g)

    last = {c: fwd(c, x.last_delivery) for c in cusips}
    ctd_last = min(cusips, key=lambda c: last[c] / x.cfs[c])
    first_fwd = fwd(ctd_last, x.first_delivery)
    horizon = light_horizon(x.first_delivery, x.last_delivery, first_fwd, last[ctd_last])
    reason = (f"{'positive' if horizon == x.last_delivery else 'negative'} carry: CTD {ctd_last} forward "
              f"{first_fwd:.4f} on {x.first_delivery}, {last[ctd_last]:.4f} on {x.last_delivery}")

    rows = []
    for c in cusips:
        p = x.prices[c]
        f = last[c] if horizon == x.last_delivery else fwd(c, horizon)
        y = forward_yield(p.price, p.coupon, p.maturity, x.settle, horizon, g)
        rows.append(BasketRow(c, p.coupon, p.maturity, x.cfs[c], p.price, p.price_from, f, y, f / x.cfs[c],
                              dv01.per_futures(p.coupon, p.maturity, horizon, y, x.cfs[c]),
                              tuple(krd.shares(p.coupon, p.maturity, horizon, curves))))
    bonds = [BasketBond(r.cusip, r.coupon, r.maturity, r.cf, r.fwd_yield) for r in rows]

    e, ctd = envelope(bonds, horizon, 0)
    e0, ctd0 = float(e[0]), ctd[0]
    sws = switches(bonds, horizon)  # the crossover table's range, −100 to +150bp
    df = 1 / g(x.settle, x.expiry.expiry)
    chain = [o for o in x.chain if o.product == x.expiry.product and o.label == x.expiry.label]
    if not chain:
        raise ValueError(f"no {x.expiry.product} {x.expiry.label} options in the bulletin for {x.asof}")
    per = {r.cusip: r.dv01_cf for r in rows}
    t_h = atm.years(x.asof, horizon)
    vol = atm.atm(chain, x.f_market, df, atm.years(x.asof, x.expiry.expiry))
    warnings += [f"ATM vol: {f}" for f in vol.flags]
    sigma_y = atm.yield_vol(vol.price_vol, per[ctd0])
    s_h, s_e = atm.width(sigma_y, t_h), atm.width(sigma_y, vol.t)
    span = pf.reach(s_h)
    prof = pf.profile(bonds, horizon, x.par_curve, switches(bonds, horizon, -span, span), s_h)
    crossovers = []
    for sw in sws:
        k = strike(sw, x.f_market, e0)
        d = digital(chain, k, x.f_market, df)
        crossovers.append(Crossover(sw, k, d, sw.z_bp / s_h, atm.normal_tail(sw.z_bp, s_e)))
        warnings += [f"switch at {sw.z_bp:+.1f}bp (K {k:.3f}): {f}" for f in d.flags]
    probs = assemble(ctd0, sws, [c.digital for c in crossovers])
    warnings += probs.warnings
    krds = {r.cusip: r.krd for r in rows}
    by_bond = probs.by_bond()
    em_lo, em_hi = krd.effective_maturity_range(krds, by_bond)
    if em_hi - em_lo > EM_WARN_YEARS:
        warnings.append(f"KRDs use interval midpoints of the probabilities; effective maturity could be "
                        f"{em_lo:.2f}–{em_hi:.2f}y")
    return LightResult(x.contract, x.asof, x.settle, horizon, reason, x.sofr, x.sofr_date, x.f_market, e0,
                       x.expiry, df, tuple(rows), tuple(crossovers), probs,
                       dv01.weighted(per, by_bond), per[ctd0], x.face,
                       krd.weighted(krds, krd.point_weights(by_bond)), krds[ctd0], x.par_date,
                       tuple(krd.clusters(krds, by_bond)), vol, sigma_y, t_h, prof, tuple(warnings))
