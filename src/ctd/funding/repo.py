"""Term GC repo from overnight rates (design 5.3; pure).

Overnight rates compound daily, actual/360, each rate applying until the next business day
(a Friday rate covers the weekend):

    G(start, end) = Π_i (1 + r_i · d_i / 360),  R_term = (G − 1) × 360 / D

Rates are decimals. ``rate_on(d)`` gives the overnight rate for business day ``d``: the SR1
strip (path 3, ``funding.strip``), or flat at the latest SOFR (path 1, ``flat``) when the strip
can't be solved.
"""

from collections.abc import Callable
from datetime import date

from ctd.reference.calendar import BusinessCalendar

Growth = Callable[[date, date], float]


def growth(start: date, end: date, rate_on: Callable[[date], float], cal: BusinessCalendar) -> float:
    """Gross factor for money lent from ``start`` to ``end`` (both business days; 1.0 if equal)."""
    if end < start:
        raise ValueError(f"end {end} is before start {start}")
    g, d = 1.0, start
    while d < end:
        nxt = min(cal.add_business_days(d, 1), end)
        g *= 1 + rate_on(d) * (nxt - d).days / 360
        d = nxt
    return g


def term_rate(start: date, end: date, rate_on: Callable[[date], float], cal: BusinessCalendar) -> float:
    """Term rate, actual/360 simple, equivalent to compounding the overnight rates."""
    return (growth(start, end, rate_on, cal) - 1) * 360 / (end - start).days


def flat(rate: float, cal: BusinessCalendar) -> Growth:
    """``G(start, end)`` with every overnight rate equal to ``rate`` (path 1)."""
    return lambda start, end: growth(start, end, lambda _: rate, cal)
