"""Delivery calendars per contract month (pure).

Computed from the CBOT rule (design section 2), unless an exception record overrides it; the model
reads them through ``ctd.data.refdata.delivery_dates``, which supplies the ``cme`` calendar and the
exceptions.

Rule for ZN, TN, ZB and UB (CBOT rulebook chapters 18-19; ZT and ZF differ and aren't encoded):
- first delivery day: first business day of the contract month
- last trading day: seventh business day before the last business day of the month
- last delivery day: last business day of the month
"""

from dataclasses import dataclass
from datetime import date, timedelta

from ctd.reference.calendar import BusinessCalendar

RULE_CONTRACTS = ("ZN", "TN", "ZB", "UB")


@dataclass(frozen=True)
class DeliveryDates:
    contract: str
    month: str  # "YYYY-MM"
    first_delivery: date
    last_trading: date
    last_delivery: date
    reason: str = ""  # why an exception record departs from the rule; empty for the rule


def rule_dates(contract: str, month: date, cal: BusinessCalendar) -> DeliveryDates:
    """The CBOT rule for ``contract`` in ``month`` (any day of it), on the ``cme`` calendar."""
    if contract not in RULE_CONTRACTS:
        raise ValueError(f"no delivery rule encoded for {contract}")
    first = cal.add_business_days(month.replace(day=1) - timedelta(days=1), 1)
    next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    last = cal.prev_business_day(next_month)
    return DeliveryDates(contract, f"{month:%Y-%m}", first, cal.add_business_days(last, -7), last)


def delivery_for(contract: str, month: date, cal: BusinessCalendar,
                 exceptions: list[DeliveryDates] = ()) -> DeliveryDates:
    """The exception record for ``contract`` in ``month`` (any day of it) if there is one, else the rule."""
    key = f"{month:%Y-%m}"
    for r in exceptions:
        if r.contract == contract and r.month == key:
            return r
    return rule_dates(contract, month, cal)
