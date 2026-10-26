"""Overnight SOFR path from the 1-month SOFR futures strip (design 5.3, path 3; pure).

An SR1 contract settles at 100 minus the arithmetic average of daily SOFR over its calendar
month, each non-business day taking the rate of the business day before it (which can fall in
the previous month). So a month's implied average ``a_m = (100 − settle) / 100`` fixes

    Σ_{d in m} r(gov(d)) = N_m · a_m,    gov(d) = the business day on or before calendar day d

Months are solved in order from the one holding the first unknown fixing. Each month's unknown
business days share one flat rate; its fixed days are the known fixings (month to date) and the
days carried in from the previous month's last business day:

    x_m = (N_m · a_m − Σ fixed) / (number of unknown days)

FOMC steps and month-end and year-end turns are spread over their months (path 2 would place
them; docs/decisions.md). Convexity and term premium are ignored (5.3).
"""

from dataclasses import dataclass
from datetime import date, timedelta

from ctd.funding.repo import Growth, growth
from ctd.reference.calendar import BusinessCalendar


def month_of(d: date) -> date:
    return d.replace(day=1)


def _next_month(m: date) -> date:
    return (m + timedelta(days=32)).replace(day=1)


def _days(m: date) -> list[date]:
    n = (_next_month(m) - m).days
    return [m + timedelta(days=i) for i in range(n)]


@dataclass(frozen=True)
class Strip:
    """Flat overnight rates per month from ``first_unknown`` on (decimals)."""

    first_unknown: date  # first business day with no fixing known on the as-of evening
    rates: dict[date, float]  # month (first day) -> rate on its unknown business days

    def rate_on(self, d: date) -> float:
        if d < self.first_unknown:
            raise ValueError(f"{d} has a known fixing; the strip starts {self.first_unknown}")
        m = month_of(d)
        if m not in self.rates:
            raise ValueError(f"no SR1 rate solved for {m:%b %Y}")
        return self.rates[m]

    def growth(self, cal: BusinessCalendar) -> Growth:
        return lambda start, end: growth(start, end, self.rate_on, cal)


def solve(averages: dict[date, float], fixings: dict[date, float], through: date,
          cal: BusinessCalendar) -> Strip:
    """The strip from SR1 implied averages (month -> decimal) and the known daily fixings
    (effective date -> decimal), solved through the month of ``through``.

    A known day with no fixing of its own (SOFR isn't published on an early-close Good Friday,
    data.md) takes the latest one before it. Raises ``ValueError`` if a needed month has no
    average or the fixings don't reach back to the current month's first day."""
    if not fixings:
        raise ValueError("no SOFR fixings")
    known = sorted(fixings)
    first = cal.add_business_days(known[-1], 1)
    if known[0] > (need := cal.latest_business_day(month_of(first))):
        raise ValueError(f"SOFR fixings start {known[0]}, after {need} (needed for SR1 {month_of(first):%b %Y})")
    rates: dict[date, float] = {}
    m = month_of(first)
    while m <= month_of(through):
        if m not in averages:
            raise ValueError(f"no SR1 settlement for {m:%b %Y}")
        fixed, unknown = 0.0, 0
        for d in (days := _days(m)):
            gov = cal.latest_business_day(d)
            if gov < first:
                fixed += fixings[max(e for e in known if e <= gov)]
            elif gov < m:
                fixed += rates[month_of(gov)]
            else:
                unknown += 1
        rates[m] = (len(days) * averages[m] - fixed) / unknown
        m = _next_month(m)
    return Strip(first, rates)
