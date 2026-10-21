"""Deliverable grades by contract month (pure). The records are loaded by ``ctd.data.refdata.grades``."""

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Grade:
    """One deliverable-grade rule for a contract, in force from ``from_contract_month``."""

    contract: str
    min_remaining_months: int
    max_remaining_months: int | None
    max_original_months: int | None
    from_contract_month: str | None = None  # "YYYY-MM"; None = earliest known record
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
