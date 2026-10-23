"""Store readers: one as-of date's raw files into clean records (rows copied from stored 2026-10-21 files)."""

from datetime import date

import pytest

from ctd.data import cme_settlements, cme_tcf, nyfed, td_prices
from ctd.reference.contracts import parse_contract

ASOF = date(2026, 10, 21)

PRICES = b"""912797QX8,MARKET BASED BILL,0.000000,11/19/2026,,0.000000,99.649444,99.649444
912810QC5,MARKET BASED BOND,0.045,08/15/2039,,93.484375,93.406250,93.281250
91282CRF0,MARKET BASED NOTE,0.04125,08/15/2036,,0.000000,95.000000,0.000000
91282CNA6,FRN,0.000000,04/30/2027,,0.000000,100.020000,0.000000
"""

TCF = b"""Exch,Period,PFCode,CUSIP,Invoice_Conversion_Factor,Create_Time
CBT,202612,17,912810QU5,0.7182,2026-10-21 11:30:23
CBT,202703,17,912810QU5,0.7203,2026-10-21 11:30:23
CBT,202612,21,91282CMV0,0.8743,2026-10-21 11:30:23
"""

ZN = (b'{"settlements":[{"month":"DEC 26","open":"105\'105","high":"105\'180","low":"105\'015","last":"105\'080",'
      b'"change":"-\'065","settle":"105\'035","volume":"1,969,012","openInterest":"5,857,268"},'
      b'{"month":"MAR 27","open":"105\'015","high":"105\'105B","low":"104\'270A","last":"105\'010",'
      b'"change":"-\'065","settle":"104\'285","volume":"713","openInterest":"11,027"},'
      b'{"month":"Total","open":"-","high":"-","low":"-","last":"-","change":"0","settle":"-",'
      b'"volume":"1,969,725","openInterest":"5,868,295"}],'
      b'"updateTime":"Wednesday, 21 Oct 2026 11:55 PM","dsHeader":"10-Year T-Note Future",'
      b'"reportType":"Final","tradeDate":"10/21/2026","empty":false}')

SOFR = (b'{"refRates": [{"effectiveDate": "2026-10-20", "type": "SOFR", "percentRate": 3.88},'
        b' {"effectiveDate": "2026-10-19", "type": "SOFR", "percentRate": 3.87}]}')


def test_parse_contract():
    assert parse_contract("ZBZ6", ASOF) == ("ZB", date(2026, 12, 1))
    assert parse_contract("ZNH7", ASOF) == ("ZN", date(2027, 3, 1))
    assert parse_contract("UBZ6", date(2026, 12, 28)) == ("UB", date(2026, 12, 1))  # still trading
    assert parse_contract("ZBZ6", date(2016, 10, 3)) == ("ZB", date(2016, 12, 1))
    with pytest.raises(ValueError):
        parse_contract("ZBA6", ASOF)


def test_td_prices_notes_and_bonds_with_price_rule(store):
    store.write(ASOF, "td_prices", "securityprice", "securityprice_2026-10-21.csv", PRICES, {})
    prices, provisional = td_prices.read(store, ASOF)
    assert set(prices) == {"912810QC5", "91282CRF0"}  # bill and FRN skipped
    bond = prices["912810QC5"]
    assert (bond.coupon, bond.maturity, bond.price, bond.price_from) == (0.045, date(2039, 8, 15), 93.28125, "eod")
    assert not provisional  # one note or bond with end of day is enough


def test_td_prices_provisional_falls_back_to_mid_then_sell():
    evening = b"""912810QC5,MARKET BASED BOND,0.045,08/15/2039,,93.484375,93.406250,0.000000
91282CRF0,MARKET BASED NOTE,0.04125,08/15/2036,,0.000000,95.000000,0.000000
"""
    prices = td_prices.parse(evening)
    assert prices["912810QC5"].price == pytest.approx((93.484375 + 93.40625) / 2)
    assert prices["912810QC5"].price_from == "mid"
    assert (prices["91282CRF0"].price, prices["91282CRF0"].price_from) == (95.0, "sell")
    assert td_prices.provisional(evening)


def test_tcf_basket_by_contract_and_month(store):
    store.write(ASOF, "cme_tcf", "csv", "TCF_20261021.csv", TCF, {})
    assert cme_tcf.read_basket(store, ASOF, "ZB", date(2026, 12, 1)) == {"912810QU5": 0.7182}
    assert cme_tcf.read_basket(store, ASOF, "ZB", date(2027, 3, 1)) == {"912810QU5": 0.7203}
    assert cme_tcf.read_basket(store, ASOF, "ZN", date(2026, 12, 1)) == {"91282CMV0": 0.8743}
    with pytest.raises(ValueError, match="no UB basket"):
        cme_tcf.read_basket(store, ASOF, "UB", date(2026, 12, 1))


@pytest.mark.parametrize("text, price", [("105'17", 105 + 17 / 32), ("105'035", 105 + 3.5 / 32),
                                         ("104'285", 104 + 28.5 / 32), ("105'102", 105 + 10.25 / 32),
                                         ("105'107", 105 + 10.75 / 32), ("105'105B", 105 + 10.5 / 32),
                                         ("106'00", 106.0)])
def test_parse_32nds(text, price):
    assert cme_settlements.parse_price(text) == price


def test_futures_settlements(store):
    store.write(ASOF, "cme_fut", "ZN", "ZN.json", ZN, {})
    fut = cme_settlements.read_futures(store, ASOF, "ZN")
    assert set(fut) == {date(2026, 12, 1), date(2027, 3, 1)}  # Total row skipped
    dec = fut[date(2026, 12, 1)]
    assert (dec.settle, dec.open_interest, dec.volume) == (105 + 3.5 / 32, 5_857_268, 1_969_012)
    with pytest.raises(ValueError, match="trade date 2026-10-21"):
        cme_settlements.parse_futures(ZN, date(2026, 10, 22))
    with pytest.raises(FileNotFoundError):
        cme_settlements.read_futures(store, ASOF, "ZB")


def test_sofr_latest_known_on_the_evening(store):
    store.write(ASOF, "nyfed_rates", "sofr", "sofr_2026-10-07_2026-10-21.json", SOFR, {})
    assert nyfed.read_latest(store, ASOF) == (date(2026, 10, 20), 0.0388)
