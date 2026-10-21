from ctd.data import refdata


def test_treasury_products_have_unique_clearing_codes():
    codes = {p["code"]: p["clearing_code"] for p in refdata.cme_products()["treasury"]}
    assert codes == {"ZT": "26", "ZF": "25", "ZN": "21", "TN": "TN", "ZB": "17", "UB": "UBE"}
