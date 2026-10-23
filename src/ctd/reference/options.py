"""Expiries of the standard (quarterly and serial) options on Treasury futures (pure).

Records are loaded by ``ctd.data.refdata.option_expiries``; the model reads those. The CBOT rule
they're generated from is kept so a test checks every record against it, and every Section 42
bulletin prints CME's own last trade dates as a second check (``cme_bulletin.last_trade_dates``).

Rule (ZT, ZF, ZN, TN, ZB, UB): the last Friday preceding, by at least two business days, the
last business day of the month before the option month; if that Friday isn't a business day,
the business day before it. A quarterly option (Mar, Jun, Sep, Dec) is on the futures of its
own month; a serial option on the next quarterly futures (January and February on March).
Weekly options aren't used (design section 2) and aren't recorded.
"""

from dataclasses import dataclass, field
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
    verified: tuple[str, ...] = field(default=())


def option_month(label: str) -> date:
    """``date(2026, 12, 1)`` from ``"DEC26"``."""
    return date(2000 + int(label[3:]), LABELS.index(label[:3]) + 1, 1)


def rule_expiry(product: str, label: str, cal: BusinessCalendar) -> OptionExpiry:
    month = option_month(label)
    prev_month_end = cal.prev_business_day(month)
    friday = cal.add_business_days(prev_month_end, -2)
    friday -= timedelta(days=(friday.weekday() - 4) % 7)
    expiry = friday if cal.is_business_day(friday) else cal.prev_business_day(friday)
    quarterly = month.month % 3 == 0
    fut_month = month.month if quarterly else month.month + 3 - month.month % 3
    fut_year = month.year + (fut_month > 12)
    fut_month = (fut_month - 1) % 12 + 1
    underlying = f"{product}{MONTH_CODES[fut_month - 1]}{fut_year % 10}"
    return OptionExpiry(product, label, expiry, underlying, quarterly)


def expiry_for(records: list[OptionExpiry], product: str, label: str) -> OptionExpiry:
    for r in records:
        if r.product == product and r.label == label:
            return r
    raise KeyError(f"no option expiry stored for {product} {label} (reference/data/option_expiries.toml)")
