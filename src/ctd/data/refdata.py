"""Load reference data files shipped in ``ctd/reference/data/``."""

import csv
import tomllib
from datetime import date
from functools import cache
from importlib.resources import files

from ctd.reference.calendar import BusinessCalendar

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
