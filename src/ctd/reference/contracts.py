"""Futures contract codes such as ``ZBZ6`` (pure)."""

from datetime import date

MONTH_CODES = "FGHJKMNQUVXZ"  # January .. December


def parse_contract(code: str, asof: date) -> tuple[str, date]:
    """``("ZB", date(2026, 12, 1))`` from ``"ZBZ6"``: product and first day of the contract month.

    The one-digit year is the first year ending in that digit not before ``asof``'s year, since a
    contract being run on ``asof`` hasn't expired.
    """
    product, month, digit = code[:-2], code[-2], code[-1]
    if not product or month not in MONTH_CODES or not digit.isdigit():
        raise ValueError(f"not a futures contract code: {code!r}")
    year = asof.year - asof.year % 10 + int(digit)
    if year < asof.year:
        year += 10
    return product, date(year, MONTH_CODES.index(month) + 1, 1)
