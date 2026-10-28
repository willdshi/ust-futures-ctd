"""Load reference data files shipped in ``ctd/reference/data/``."""

import csv
import tomllib
from datetime import date, timedelta
from functools import cache
from importlib.resources import files

from ctd.reference.calendar import BusinessCalendar
from ctd.reference.delivery import DeliveryDates, delivery_for
from ctd.reference.grades import Grade
from ctd.reference.options import OptionExpiry, expiry_for, option_month

CALENDARS = ("cme", "sifma")


def _ref_file(name: str):
    return files("ctd.reference").joinpath("data", name)


@cache
def calendar(name: str) -> BusinessCalendar:
    """Business calendar ``cme`` (CME interest rate settlements) or ``sifma`` (cash Treasuries)."""
    if name not in CALENDARS:
        raise ValueError(f"unknown calendar {name!r}; expected one of {CALENDARS}")
    with _ref_file("holidays.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    closed = frozenset(date.fromisoformat(r["date"]) for r in rows if r[f"{name}_closed"] == "y")
    return BusinessCalendar(name, closed)


@cache
def cme_products() -> dict:
    with _ref_file("cme_products.toml").open("rb") as f:
        return tomllib.load(f)


@cache
def grades() -> list[Grade]:
    """Deliverable-grade records from ``contract_grades.toml``."""
    with _ref_file("contract_grades.toml").open("rb") as f:
        records = tomllib.load(f)["grade"]
    return [Grade(**{**r, "verified": tuple(r.get("verified", ())), "to_verify": tuple(r.get("to_verify", ()))})
            for r in records]


@cache
def holidays_through() -> date:
    """Last day the holiday list covers: the end of the latest year with a row in ``holidays.csv``."""
    with _ref_file("holidays.csv").open(newline="", encoding="utf-8") as f:
        return date(max(int(r["date"][:4]) for r in csv.DictReader(f)), 12, 31)


@cache
def rule_exceptions() -> dict[str, list]:
    """Records in ``rule_exceptions.toml`` that override the delivery and option expiry rules."""
    with _ref_file("rule_exceptions.toml").open("rb") as f:
        records = tomllib.load(f)
    return {"delivery": [DeliveryDates(**r) for r in records.get("delivery", [])],
            "expiry": [OptionExpiry(**r) for r in records.get("expiry", [])]}


def _covered(needed: date, what: str) -> None:
    if needed > holidays_through():
        raise ValueError(f"{what} needs holidays to {needed}; reference/data/holidays.csv ends {holidays_through()}")


def delivery_dates(contract: str, month: date) -> DeliveryDates:
    """Delivery calendar for ``contract`` in ``month`` (any day of it): the CBOT rule on the ``cme`` calendar,
    or an exception record (design section 2)."""
    next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    _covered(next_month - timedelta(days=1), f"delivery calendar {contract} {month:%Y-%m}")
    return delivery_for(contract, month, calendar("cme"), rule_exceptions()["delivery"])


def option_expiry(product: str, label: str) -> OptionExpiry:
    """Expiry of the standard option ``label`` (``"DEC26"``) on ``product``: the CBOT rule on the ``cme``
    calendar, or an exception record (design section 2)."""
    _covered(option_month(label) - timedelta(days=1), f"option expiry {product} {label}")
    return expiry_for(product, label, calendar("cme"), rule_exceptions()["expiry"])
