"""Which futures contracts run on a date (pure).

The run window (design section 7): a contract runs from the Friday one week before the previous
quarterly contract's options expire (the next business day if that Friday is a holiday) to the day
before its own quarterly options expire. Expiries are the caller's: the rule on a calendar by
default, ``ctd.data.refdata.contracts_on`` passes the expiry records and the holiday-list check.
"""

from collections.abc import Callable, Sequence
from datetime import date, timedelta

from ctd.reference.calendar import BusinessCalendar
from ctd.reference.contracts import MONTH_CODES
from ctd.reference.options import LABELS, rule_expiry


def window_start(previous_expiry: date, cal: BusinessCalendar) -> date:
    """First run date of the contract after the one whose options expire ``previous_expiry``: the Friday
    of that week less seven days (an expiry on a Thursday still counts its own Friday), moved forward
    to a business day."""
    start = previous_expiry + timedelta(days=4 - previous_expiry.weekday()) - timedelta(days=7)
    while not cal.is_business_day(start):
        start += timedelta(days=1)
    return start


def contracts_on(asof: date, products: Sequence[str], cal: BusinessCalendar,
                 expiry_of: Callable[[str, str], date] | None = None) -> list[str]:
    """The contracts that run on ``asof`` (``"ZNZ6"``, ``"ZNH7"``), by product in the order given, then
    by contract month: one per product, two in the week the next contract's window has opened and the
    old one's options haven't expired. ``expiry_of(product, "DEC26")`` is the quarterly options'
    expiry; the default is the CBOT rule on ``cal``."""
    if expiry_of is None:
        def expiry_of(product, label):
            return rule_expiry(product, label, cal).expiry

    def label(month: date) -> str:
        return f"{LABELS[month.month - 1]}{month.year % 100:02d}"

    out = []
    for product in products:
        previous = expiry_of(product, label(date(asof.year - 1, 12, 1)))
        for n in range(8):  # the quarterly months from March of asof's year
            month = date(asof.year + n // 4, 3 * (n % 4) + 3, 1)
            if window_start(previous, cal) > asof:
                break
            expiry = expiry_of(product, label(month))
            if asof < expiry:
                out.append(f"{product}{MONTH_CODES[month.month - 1]}{month.year % 10}")
            previous = expiry
    return out
