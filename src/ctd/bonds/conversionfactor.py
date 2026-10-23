"""CBOT conversion factor: the price per 1 of par at a 6% yield (pure).

Remaining term is measured from the first day of the delivery month and rounded down to
``round_months`` (3 for ZN, TN, ZB and UB; 1 for ZT and ZF, from ``cme_products.toml``):

    n = whole years, z = leftover months (rounded down)
    v = z if z < 7 else z − 6
    a = 1.03^(−v/6),  b = (coupon/2)(6 − v)/6
    c = 1.03^(−2n) if z < 7 else 1.03^(−(2n + 1))
    d = (coupon/0.06)(1 − c)
    CF = a (coupon/2 + c + d) − b, rounded to 4 decimals

CME's published tables (TCF) are validation data for this formula, not inputs (design 2).
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal


def conversion_factor(coupon: float, maturity: date, contract_month: date, round_months: int) -> float:
    """CF for a bond with decimal ``coupon`` and ``maturity``, delivered in ``contract_month`` (any day of it)."""
    months = (maturity.year - contract_month.year) * 12 + maturity.month - contract_month.month
    if months <= 0:
        raise ValueError(f"maturity {maturity} is not after delivery month {contract_month:%Y-%m}")
    n, z = divmod(months, 12)
    z -= z % round_months
    v = z if z < 7 else z - 6
    a = 1.03 ** (-v / 6)
    b = coupon / 2 * (6 - v) / 6
    c = 1.03 ** -(2 * n if z < 7 else 2 * n + 1)
    d = coupon / 0.06 * (1 - c)
    cf = a * (coupon / 2 + c + d) - b
    return float(Decimal(repr(cf)).quantize(Decimal("0.0001"), ROUND_HALF_UP))
