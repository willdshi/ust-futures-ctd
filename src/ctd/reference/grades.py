"""Deliverable grades by contract month (pure). The records are loaded by ``ctd.data.refdata.grades``."""

import calendar
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Grade:
    """One deliverable-grade rule for a contract, in force from ``from_contract_month``."""

    contract: str
    min_remaining_months: int
    max_remaining_months: int | None = None  # None: no maximum (ZF, UB)
    max_original_months: int | None = None  # None: any original term (ZB, UB)
    from_contract_month: str | None = None  # "YYYY-MM"; None = earliest known record
    max_remaining_exclusive: bool = False  # "less than" the maximum (ZB) rather than "not more than"
    max_remaining_from: str = "first"  # the maximum is measured from the "first" or "last" day of the delivery month (ZT)
    verified: tuple[str, ...] = field(default=())
    to_verify: tuple[str, ...] = field(default=())


def grade_for(grades: list[Grade], contract: str, contract_month: date) -> Grade:
    """The rule in force for ``contract``'s delivery month ``contract_month`` (any day in that month)."""
    month = f"{contract_month.year:04d}-{contract_month.month:02d}"
    rules = sorted((g for g in grades if g.contract == contract), key=lambda g: g.from_contract_month or "")
    if not rules:
        raise KeyError(f"no deliverable grade recorded for {contract}")
    in_force = [g for g in rules if (g.from_contract_month or "") <= month]
    if not in_force:
        raise KeyError(f"no {contract} grade in force for {month}; earliest starts {rules[0].from_contract_month}")
    return in_force[-1]


def add_months(d: date, months: int) -> date:
    """``d`` moved by whole months, clipped to the month's end (31 January + 1 month = 28/29 February)."""
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def eligible(grade: Grade, contract_month: date, maturity: date, original_issue: date) -> bool:
    """Whether a note or bond is deliverable into ``contract_month`` (any day of it) under ``grade``.

    Remaining term is measured from the first day of the delivery month (ZT's maximum from the last
    day), original term from the original issue date; limits are inclusive except ZB's maximum.
    """
    first = contract_month.replace(day=1)
    if maturity < add_months(first, grade.min_remaining_months):
        return False
    if grade.max_remaining_months is not None:
        base = first if grade.max_remaining_from == "first" else             first.replace(day=calendar.monthrange(first.year, first.month)[1])
        limit = add_months(base, grade.max_remaining_months)
        if maturity > limit or (grade.max_remaining_exclusive and maturity == limit):
            return False
    return grade.max_original_months is None or maturity <= add_months(original_issue, grade.max_original_months)
