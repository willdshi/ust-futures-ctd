import csv
from datetime import date
from pathlib import Path

import pytest

from ctd.bonds.conversionfactor import conversion_factor
from ctd.data import refdata

# TCF_20261021.csv rows for the six Treasury contracts, with coupon and maturity joined from that
# day's TreasuryDirect price file (CUSIPs without a price are left out).
FIXTURE = Path(__file__).parent / "data" / "tcf_2026-10-21.csv"


def _rows():
    with FIXTURE.open(newline="") as f:
        return list(csv.DictReader(f))


def test_formula_matches_cme_table():
    products = {p["clearing_code"]: p for p in refdata.cme_products()["treasury"]}
    rows = _rows()
    assert {products[r["pfcode"]]["code"] for r in rows} == {"ZT", "ZF", "ZN", "TN", "ZB", "UB"}
    for r in rows:
        month = date(int(r["period"][:4]), int(r["period"][4:]), 1)
        cf = conversion_factor(float(r["coupon"]), date.fromisoformat(r["maturity"]), month,
                               products[r["pfcode"]]["cf_round_months"])
        assert cf == float(r["cf"]), r


def test_six_percent_bond_has_factor_about_one():
    # whole half-years after rounding (19y 0m, 29y 6m): exactly 1
    for maturity in (date(2046, 2, 15), date(2056, 8, 15)):
        assert conversion_factor(0.06, maturity, date(2026, 12, 1), 3) == 1.0
    # an odd quarter (6y 11m → 6y 9m): the stub is discounted compounded but accrued linearly
    assert conversion_factor(0.06, date(2033, 11, 15), date(2026, 12, 1), 3) == 0.9999


def test_quarter_rounding():
    # 15 Feb 2042 from 1 Dec 2026 is 15y 2m: rounds down to 15y 0m, the same factor as 15 Dec 2041
    assert conversion_factor(0.04, date(2042, 2, 15), date(2026, 12, 1), 3) == \
        conversion_factor(0.04, date(2041, 12, 15), date(2026, 12, 1), 3)
    assert conversion_factor(0.04, date(2042, 2, 15), date(2026, 12, 1), 1) != \
        conversion_factor(0.04, date(2041, 12, 15), date(2026, 12, 1), 1)


def test_matured_bond_raises():
    with pytest.raises(ValueError, match="not after delivery month"):
        conversion_factor(0.04, date(2026, 12, 31), date(2026, 12, 1), 3)
