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

``F_market − E(0)`` is reported as the recentring gap: the net basis the model holds constant
(delivery options, specialness, the timing of the price snapshots).
"""

from dataclasses import dataclass
from datetime import date

from ctd.bonds.forward import forward_clean, forward_yield
from ctd.data.cme_bulletin import OptionSettle
from ctd.data.td_prices import BondPrice
from ctd.funding.repo import flat
from ctd.model.envelope import BasketBond, Switch, envelope, switches
from ctd.model.horizon import light_horizon
from ctd.model.probabilities import Probabilities, assemble, strike
from ctd.reference.calendar import BusinessCalendar
from ctd.reference.options import OptionExpiry
from ctd.vol.digitals import Digital, digital


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

    @property
    def carry(self) -> float:
        """Price points earned holding the bond to the horizon (today's price − forward)."""
        return self.price - self.fwd


@dataclass(frozen=True)
class Crossover:
    switch: Switch
    strike: float  # K_k
    digital: Digital


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
    warnings: tuple[str, ...]

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

    g = flat(x.sofr, x.repo_cal)

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
        rows.append(BasketRow(c, p.coupon, p.maturity, x.cfs[c], p.price, p.price_from, f, y, f / x.cfs[c]))
    bonds = [BasketBond(r.cusip, r.coupon, r.maturity, r.cf, r.fwd_yield) for r in rows]

    e, ctd = envelope(bonds, horizon, 0)
    e0, ctd0 = float(e[0]), ctd[0]
    sws = switches(bonds, horizon)
    df = 1 / g(x.settle, x.expiry.expiry)
    chain = [o for o in x.chain if o.product == x.expiry.product and o.label == x.expiry.label]
    if not chain:
        raise ValueError(f"no {x.expiry.product} {x.expiry.label} options in the bulletin for {x.asof}")
    crossovers = []
    for sw in sws:
        k = strike(sw, x.f_market, e0)
        d = digital(chain, k, x.f_market, df)
        crossovers.append(Crossover(sw, k, d))
        warnings += [f"switch at {sw.z_bp:+.1f}bp (K {k:.3f}): {f}" for f in d.flags]
    probs = assemble(ctd0, sws, [c.digital for c in crossovers])
    warnings += probs.warnings
    return LightResult(x.contract, x.asof, x.settle, horizon, reason, x.sofr, x.sofr_date, x.f_market, e0,
                       x.expiry, df, tuple(rows), tuple(crossovers), probs, tuple(warnings))
