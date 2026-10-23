"""Load reference data files shipped in ``ctd/reference/data/``."""

import csv
import tomllib
from datetime import date
from functools import cache
from importlib.resources import files

from ctd.reference.calendar import BusinessCalendar
from ctd.reference.delivery import DeliveryDates
from ctd.reference.grades import Grade
from ctd.reference.options import OptionExpiry

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
def delivery_calendar() -> list[DeliveryDates]:
    """Delivery dates per contract month from ``delivery_calendar.toml``."""
    with _ref_file("delivery_calendar.toml").open("rb") as f:
        records = tomllib.load(f)["month"]
    return [DeliveryDates(**{**r, "verified": tuple(r.get("verified", ()))}) for r in records]


@cache
def option_expiries() -> list[OptionExpiry]:
    """Standard option expiries from ``option_expiries.toml``."""
    with _ref_file("option_expiries.toml").open("rb") as f:
        records = tomllib.load(f)["expiry"]
    return [OptionExpiry(**{**r, "verified": tuple(r.get("verified", ()))}) for r in records]
