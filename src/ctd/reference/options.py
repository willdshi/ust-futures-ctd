"""Expiries of the standard (quarterly and serial) options on Treasury futures (pure).

Computed from the CBOT rule (design section 2), unless an exception record overrides it; the model
reads them through ``ctd.data.refdata.option_expiry``, which supplies the ``cme`` calendar and the
exceptions. ``ctd derive`` checks the rule against CME's own expiry for every option month in the
derived options table (``ctd.data.derived.options.expiry_disagreements``).

Rule (ZT, ZF, ZN, TN, ZB, UB): the last Friday preceding, by at least two business days, the
last business day of the month before the option month; if that Friday isn't a business day,
the business day before it. A quarterly option (Mar, Jun, Sep, Dec) is on the futures of its
own month; a serial option on the next quarterly futures (January and February on March).
Weekly options aren't used (design section 2) and aren't recorded.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from ctd.reference.calendar import BusinessCalendar
from ctd.reference.contracts import MONTH_CODES

LABELS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


@dataclass(frozen=True)
class OptionExpiry:
    product: str  # futures product, e.g. "ZN"
    label: str  # option month as the bulletin prints it, e.g. "DEC26"
    expiry: date  # last trading day
    underlying: str  # futures contract, e.g. "ZNZ6"
    quarterly: bool
    reason: str = ""  # why an exception record departs from the rule; empty for the rule


def option_month(label: str) -> date:
    """``date(2026, 12, 1)`` from ``"DEC26"``."""
    return date(2000 + int(label[3:]), LABELS.index(label[:3]) + 1, 1)


def underlying_month(label: str) -> date:
    """Contract month (first day) of the futures under option month ``label``: its own month for a
    quarterly, the next quarterly for a serial (``"NOV26"`` → ``date(2026, 12, 1)``, ``"JAN27"`` → March)."""
    month = option_month(label)
    fut_month = month.month + (3 - month.month % 3) % 3
    return date(month.year + (fut_month > 12), (fut_month - 1) % 12 + 1, 1)


def rule_expiry(product: str, label: str, cal: BusinessCalendar) -> OptionExpiry:
    month = option_month(label)
    prev_month_end = cal.prev_business_day(month)
    friday = cal.add_business_days(prev_month_end, -2)
    friday -= timedelta(days=(friday.weekday() - 4) % 7)
    expiry = friday if cal.is_business_day(friday) else cal.prev_business_day(friday)
    fut = underlying_month(label)
    underlying = f"{product}{MONTH_CODES[fut.month - 1]}{fut.year % 10}"
    return OptionExpiry(product, label, expiry, underlying, month.month % 3 == 0)


def expiry_for(product: str, label: str, cal: BusinessCalendar,
               exceptions: list[OptionExpiry] = ()) -> OptionExpiry:
    """The exception record for ``product`` and ``label`` if there is one, else the rule."""
    for r in exceptions:
        if r.product == product and r.label == label:
            return r
    return rule_expiry(product, label, cal)
