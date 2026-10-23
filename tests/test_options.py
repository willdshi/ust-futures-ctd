"""Option expiry records (B1) and the Section 42 parser (B2). Rows are copied from stored bulletins."""

from datetime import date

import pytest

from ctd.data import refdata
from ctd.data.cme_bulletin import decode_premium, decode_strike, last_trade_dates, parse_options
from ctd.reference.options import expiry_for, rule_expiry

CME = refdata.calendar("cme")

PAGE_BREAK = """VOLUME AND OPEN INTEREST "RECORDS" SHOWN FOR CBOT PRODUCTS, ARE COMPRISED OF VOLUME AND OPEN INTEREST DATA
42 10YR NOTE, 5YR NOTE, 2YR NOTE, AND 30YR BOND OPTIONS 42
Side 02 Side 02
2026 DAILY INFORMATION BULLETIN - http://www.cmegroup.com/dailybulletin
PG42 BULLETIN # 203@ 10YR NOTE, 5YR NOTE, 2YR NOTE AND 30YR BOND OPTIONS Wed, Oct 21, 2026 PG42"""

SECTION42 = f"""10 YEAR NOTE CALLS
STRIKE OPEN RANGE HIGH LOW CLOSING RANGE & PT.CHGE. DELTA CISES CLEARED INTEREST HIGH LOW
10Y NOTE CALL
NOV26 10Y NOTE CALL
1045 61 103 39A ---- 42 - 12 .896 ---- 8366 65200 - 3156 457B 130A
{PAGE_BREAK}
1047 37 52B 26A ---- 28 - 12 .798 ---- 1063 21124 - 4 ---- ----
1185 ---- ---- ---- ---- CAB ---- ---- ---- ---- 200 UNCH 2B 1A
TOTAL 9429 86524 - 3160
DEC26
1000 ---- 535B 505A ---- 508 - 13 .973 ---- ---- 352 UNCH 848B 544A
1025 258 306B 242A ---- 245 - 13 .906 ---- 306 1089 UNCH 703B 320A
TOTAL 306 1441 UNCH
5Y NOTE CALL
NOV26 5Y NOTE CALL
985 5260 5385B 5180A ---- 5195 + NEW .995 ---- 20 10 + 10 7615B 5395A
TOTAL 20 10 + 10
2Y NOTE CALL
NOV26 2Y NOTE CALL
1013 ---- 380B 320A ---- 325 - 35 .787 ---- ---- 6 UNCH 1455B 410A
TOTAL 0 6 UNCH
30Y BOND PUT
NOV26 30Y BOND PUT
800 ---- 2607B 2527A ---- 2534 - 6 1.000 ---- ---- 1 UNCH 2959B 2606A
TOTAL 0 1 UNCH
10-YEAR WEEK1 NOTE CALLS
10Y WK1 NOTE C
NOV26 10Y WK1 NOTE C
1050 ---- 10B 5A ---- 7 - 1 .500 ---- 5 10 UNCH ---- ----
TOTAL 5 10 UNCH
OPTIONS EOO'S, BLOCKS and EXERCISES
10Y NOTE CALL 10-YR NOTE OPTIONS
NOV26 CALL
TC 1040 ---- ---- 21200 ---- ---- 115.00
"""


def test_expiry_records_agree_with_the_rule():
    for r in refdata.option_expiries():
        rule = rule_expiry(r.product, r.label, CME)
        assert (r.expiry, r.underlying, r.quarterly) == (rule.expiry, rule.underlying, rule.quarterly), r


def test_december_quarterly_and_serials():
    dec = expiry_for(refdata.option_expiries(), "ZB", "DEC26")
    assert (dec.expiry, dec.underlying, dec.quarterly) == (date(2026, 11, 20), "ZBZ6", True)
    jan = expiry_for(refdata.option_expiries(), "ZN", "JAN27")
    assert (jan.expiry, jan.underlying) == (date(2026, 12, 24), "ZNH7")  # Christmas Friday: day before
    assert rule_expiry("ZN", "NOV26", CME).underlying == "ZNZ6"
    with pytest.raises(KeyError):
        expiry_for(refdata.option_expiries(), "ZN", "SEP27")


def test_page_one_last_trade_dates():
    page1 = """EXPIRATION: OCT26 NOV26 DEC26 JAN27 FEB27 MAR27 JUN27
30YR BOND OPT 09/25 10/23 11/20 12/24 01/22 02/19 05/21
10YR NOTE OPT 09/25 10/23 11/20 12/24 01/22 02/19 05/21
10YR NOTE FUT 12/21 03/19 06/21"""
    ltd = last_trade_dates(page1)
    assert ltd[("ZN", "DEC26")] == date(2026, 11, 20)
    assert ltd[("ZB", "JAN27")] == date(2026, 12, 24)
    assert ltd[("ZB", "OCT26")] == date(2026, 9, 25)
    assert ("ZN", "MAR27") in ltd and not any(p == "ZT" for p, _ in ltd)
    for (product, label), d in ltd.items():
        if label != "OCT26":
            assert expiry_for(refdata.option_expiries(), product, label).expiry == d


@pytest.mark.parametrize("product, code, strike", [("ZN", "1045", 104.5), ("ZN", "1047", 104.75),
                                                   ("ZN", "1042", 104.25), ("ZB", "1050", 105.0),
                                                   ("ZB", "1055", 105.5), ("ZT", "1013", 101.375),
                                                   ("ZT", "1016", 101.625), ("ZF", "977", 97.75)])
def test_strike_codes(product, code, strike):
    assert decode_strike(product, code) == strike


@pytest.mark.parametrize("product, code, premium", [("ZN", "461", 4 + 61 / 64), ("ZN", "42", 42 / 64),
                                                    ("ZB", "2534", 25 + 34 / 64), ("ZF", "6035", 6 + 3.5 / 64),
                                                    ("ZT", "1365", 1 + 36.5 / 64), ("ZN", "1", 1 / 64)])
def test_premium_codes(product, code, premium):
    assert decode_premium(product, code) == pytest.approx(premium, abs=1e-12)


def test_parse_standard_blocks_only():
    rows = parse_options(SECTION42)
    assert [(r.product, r.label, r.right, r.strike) for r in rows] == [
        ("ZN", "NOV26", "C", 104.5), ("ZN", "NOV26", "C", 104.75), ("ZN", "NOV26", "C", 118.5),
        ("ZN", "DEC26", "C", 100.0), ("ZN", "DEC26", "C", 102.5),
        ("ZF", "NOV26", "C", 98.5), ("ZT", "NOV26", "C", 101.375), ("ZB", "NOV26", "P", 80.0)]
    first, cab, dec = rows[0], rows[2], rows[3]
    assert (first.settle, first.delta, first.volume, first.open_interest) == (42 / 64, 0.896, 8366, 65200)
    assert cab.cabinet and cab.delta is None and cab.open_interest == 200
    assert dec.settle == 5 + 8 / 64
    assert rows[5].settle == pytest.approx(5 + 19.5 / 64)  # "+ NEW" change
    assert rows[7].settle == 25 + 34 / 64


def test_block_checks():
    with pytest.raises(ValueError, match="rows don't add up"):
        parse_options(SECTION42.replace("TOTAL 306 1441 UNCH", "TOTAL 306 1442 UNCH"))
    swapped = SECTION42.replace("1000 ---- 535B", "1030 ---- 535B")
    with pytest.raises(ValueError, match="strikes not increasing"):
        parse_options(swapped)
