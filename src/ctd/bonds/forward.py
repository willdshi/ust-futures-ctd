"""Forward prices to a delivery date (design 5.1, 5.3; pure).

Buy the bond at settlement, finance it at repo, and receive every coupon paid after settlement
up to and including delivery (reinvested at the same repo):

    F_dirty = P_dirty · G(settle, T) − Σ_k c_k · G(t_k, T),   F_clean = F_dirty − AI(T)

``G(start, end)`` is the gross repo factor (``ctd.funding.repo``). Coupons are counted on their
scheduled dates; a coupon due on the delivery date is paid to the holder, so the bond delivered
that day has no accrued.
"""

from datetime import date

from ctd.bonds.pricing import yield_from_clean
from ctd.bonds.schedule import accrued, coupon_dates
from ctd.funding.repo import Growth


def forward_clean(clean: float, coupon: float, maturity: date, settle: date, delivery: date, g: Growth) -> float:
    """Forward clean price at ``delivery`` from today's ``clean`` price for settlement ``settle``."""
    if delivery < settle:
        raise ValueError(f"delivery {delivery} is before settlement {settle}")
    dirty = clean + accrued(coupon, maturity, settle)
    paid = [d for d in coupon_dates(maturity, settle) if d <= delivery]
    fwd_dirty = dirty * g(settle, delivery) - sum(100 * coupon / 2 * g(d, delivery) for d in paid)
    return fwd_dirty - accrued(coupon, maturity, delivery)


def forward_yield(clean: float, coupon: float, maturity: date, settle: date, delivery: date, g: Growth) -> float:
    """Yield at ``delivery`` of the forward clean price, through the single pricing function."""
    return yield_from_clean(coupon, maturity, delivery, forward_clean(clean, coupon, maturity, settle, delivery, g))
