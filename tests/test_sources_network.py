"""Live smoke tests: one unit per source against the real endpoint. CME only with CTD_CME_AUTO=1."""

import os
from datetime import date

import pytest

from ctd.data import refdata, registry
from ctd.data.http import RequestsHttp

pytestmark = pytest.mark.network

UNITS = {
    "td_prices": "securityprice",
    "td_securities": "Bond",
    "fiscaldata_auctions": "auctions_query",
    "par_curve": "daily_treasury_yield_curve",
    "fred": "DGS10",
    "nyfed_rates": "sofr",
    "cme_fut": "ZN",
    "cme_opt": "ZN",
    "cme_stir": "SR3",
    "cme_tcf": "csv",
    "yahoo_fut": "ZN",
}


@pytest.mark.parametrize("source", sorted(UNITS))
def test_source_live(source):
    spec = registry.SOURCES[source]
    if spec.cme and os.environ.get("CTD_CME_AUTO") != "1":
        pytest.skip("CME fetch is off (set CTD_CME_AUTO=1 after checking CME's terms of use)")
    cal = refdata.calendar(spec.calendar)
    asof = cal.prev_business_day(date.today())
    files = list(spec.fetch(asof, UNITS[source], RequestsHttp()))
    assert files and all(f.content for f in files)
