"""Coupon dates and accrued interest for fixed-coupon Treasuries (pure).

Coupons are semiannual on scheduled (unadjusted) dates stepped back from maturity. A
maturity on the last day of its month pays on the last day of each coupon month (30 April
and 31 October; 28/29 February and 31 August). Treasuries are dated on their schedule, so
the stepped-back dates are right for every bond, first period included. Coupon rates are
decimals (0.045 = 4.5%); amounts are per 100 face.
"""

import calendar
from datetime import date


def _is_month_end(d: date) -> bool:
    return d.day == calendar.monthrange(d.year, d.month)[1]


def _months_back(maturity: date, months: int) -> date:
    y, m = divmod(maturity.year * 12 + maturity.month - 1 - months, 12)
    last = calendar.monthrange(y, m + 1)[1]
    day = last if _is_month_end(maturity) else min(maturity.day, last)
    return date(y, m + 1, day)


def coupon_dates(maturity: date, settle: date) -> list[date]:
    """Scheduled coupon dates strictly after ``settle``, up to and including maturity."""
    if settle >= maturity:
        raise ValueError(f"settlement {settle} is on or after maturity {maturity}")
    dates = []
    k = 0
    while (d := _months_back(maturity, 6 * k)) > settle:
        dates.append(d)
        k += 1
    return dates[::-1]


def prev_next_coupon(maturity: date, settle: date) -> tuple[date, date]:
    """The coupon period containing ``settle``: ``prev <= settle < next``."""
    nxt = coupon_dates(maturity, settle)[0]
    k = 0
    while _months_back(maturity, 6 * k) != nxt:
        k += 1
    return _months_back(maturity, 6 * (k + 1)), nxt


def accrued(coupon: float, maturity: date, settle: date) -> float:
    """Accrued interest per 100 face, actual/actual within the coupon period."""
    prev, nxt = prev_next_coupon(maturity, settle)
    return 100 * coupon / 2 * (settle - prev).days / (nxt - prev).days
