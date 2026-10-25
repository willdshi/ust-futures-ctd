"""Deliverable baskets from the grade rules (design 2, 8), and the check against CME's TCF tables."""

from datetime import date

import pandas as pd

from ctd.bonds.conversionfactor import conversion_factor
from ctd.data import refdata
from ctd.data.derived.baskets import basket_rows, tcf_check
from ctd.reference.grades import add_months, eligible, grade_for

GRADES = refdata.grades()


def deliverable(contract: str, month: date, maturity: date, issued: date) -> bool:
    return eligible(grade_for(GRADES, contract, month), month, maturity, issued)


def test_91282CFV8_crosses_the_zn_grade_change():
    """4 1/8% November 2032: deliverable for June 2023 (6.5 to 10 years) but not September 2023 (8 years)."""
    maturity, issued = date(2032, 11, 15), date(2022, 11, 15)
    assert deliverable("ZN", date(2023, 6, 1), maturity, issued)
    assert not deliverable("ZN", date(2023, 9, 1), maturity, issued)
    assert deliverable("ZN", date(2024, 12, 1), maturity, issued)  # back under 8 years


def test_a_bond_moves_from_ub_to_zb_at_25_years():
    maturity, issued = date(2050, 12, 1), date(2020, 12, 1)
    assert deliverable("UB", date(2025, 9, 1), maturity, issued) and not deliverable("ZB", date(2025, 9, 1), maturity, issued)
    # exactly 25 years from the first day of the delivery month: UB ("not less than"), not ZB ("less than")
    assert deliverable("UB", date(2025, 12, 1), maturity, issued) and not deliverable("ZB", date(2025, 12, 1), maturity, issued)
    assert deliverable("ZB", date(2026, 3, 1), maturity, issued) and not deliverable("UB", date(2026, 3, 1), maturity, issued)


def test_zt_maximum_runs_from_the_last_day_of_the_month():
    issued = date(2026, 11, 30)
    assert deliverable("ZT", date(2026, 12, 1), date(2028, 12, 31), issued)  # 2 years from 31 December
    assert not deliverable("ZT", date(2026, 12, 1), date(2029, 1, 31), issued)
    assert deliverable("ZT", date(2026, 12, 1), date(2028, 9, 1), issued)  # 1 year 9 months from 1 December
    assert not deliverable("ZT", date(2026, 12, 1), date(2028, 8, 31), issued)
    assert add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)


def securities_frame(*bonds) -> pd.DataFrame:
    return pd.DataFrame([{"cusip": c, "type": "Note", "coupon": cpn, "maturity": mat, "original_issue_date": iss,
                          "first_auction_date": auc, "inflation_protected": False, "floating_rate": False}
                         for c, cpn, mat, iss, auc in bonds])


def test_a_7_year_reopened_as_a_5_year_joins_zf_at_the_reopening():
    """91282CGQ8: 4% February 2030, a 7-year (2023-02) reopened as a 5-year (2025-02)."""
    securities = securities_frame(("91282CGQ8", 0.04, date(2030, 2, 28), date(2023, 2, 28), date(2023, 2, 23)))
    auctions = pd.DataFrame({"cusip": ["91282CGQ8"] * 2, "auction_date": [date(2023, 2, 23), date(2025, 2, 25)],
                             "issue_date": [date(2023, 2, 28), date(2025, 2, 28)]})
    rows = basket_rows(securities, auctions, date(2025, 3, 1))
    zf = rows[rows["contract"] == "ZF"]
    assert zf[["month", "eligible_from"]].values.tolist() == [[date(2025, 3, 1), date(2025, 2, 25)]]
    assert zf["cf"].item() == conversion_factor(0.04, date(2030, 2, 28), date(2025, 3, 1), 1) == 0.9159
    # ZN while more than 6.5 years were left, from its first auction (original term 7 years)
    assert rows.loc[rows["contract"] == "ZN", ["month", "eligible_from"]].values.tolist() == [
        [date(2023, 3, 1), date(2023, 2, 23)], [date(2023, 6, 1), date(2023, 2, 23)]]


def test_tcf_check_tells_late_listings_from_disagreements():
    month = date(2025, 6, 1)
    ours = pd.DataFrame([
        {"contract": "ZT", "month": month, "cusip": "A", "cf": 0.95, "eligible_from": date(2024, 1, 1)},
        {"contract": "ZT", "month": month, "cusip": "NEW", "cf": 0.96, "eligible_from": date(2025, 5, 27)},
        {"contract": "ZT", "month": month, "cusip": "WRONG", "cf": 0.97, "eligible_from": date(2024, 1, 1)}])
    cme = pd.DataFrame([
        {"asof": date(2025, 5, 30), "contract": "ZT", "month": month, "cusip": "A", "cf": 0.95},
        {"asof": date(2025, 5, 30), "contract": "ZT", "month": month, "cusip": "MISSED", "cf": 0.93},
        {"asof": date(2025, 6, 4), "contract": "ZT", "month": month, "cusip": "A", "cf": 0.9501},
        {"asof": date(2025, 6, 4), "contract": "ZT", "month": month, "cusip": "NEW", "cf": 0.96}])
    [c] = tcf_check(ours, cme).values()
    assert (c["missing_from_rules"], c["extra_in_rules"], c["cme_late"], c["cf_differ"]) == (
        ["MISSED"], ["WRONG"], ["NEW"], ["A"])
