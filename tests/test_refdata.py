from ctd.data import refdata


def test_treasury_products_have_unique_clearing_codes():
    codes = {p["code"]: p["clearing_code"] for p in refdata.cme_products()["treasury"]}
    assert codes == {"ZT": "26", "ZF": "25", "ZN": "21", "TN": "TN", "ZB": "17", "UB": "UBE"}


def test_zn_grade_changes_with_the_september_2023_contract():
    from datetime import date

    from ctd.reference.grades import grade_for

    grades = refdata.grades()
    june, september = grade_for(grades, "ZN", date(2023, 6, 1)), grade_for(grades, "ZN", date(2023, 9, 1))
    assert (june.min_remaining_months, june.max_remaining_months) == (78, 120)       # 6y6m to 10y
    assert (september.min_remaining_months, september.max_remaining_months) == (78, 96)  # 6y6m to 8y
    assert grade_for(grades, "ZN", date(2026, 12, 1)) == september
    assert grade_for(grades, "ZN", date(2016, 3, 1)) == june
    assert june.max_original_months == september.max_original_months == 120


def test_no_grade_before_the_2016_history_start():
    from datetime import date

    import pytest

    from ctd.reference.grades import grade_for

    with pytest.raises(KeyError, match="earliest starts 2016-03"):
        grade_for(refdata.grades(), "ZN", date(2015, 12, 1))
