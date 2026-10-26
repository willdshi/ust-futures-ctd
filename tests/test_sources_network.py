"""Live smoke tests: one unit per downloaded source against the real endpoint."""

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
    "cme_tcf": "csv",
    "yahoo_fut": "ZN",
}


@pytest.mark.parametrize("source", sorted(UNITS))
def test_source_live(source):
    spec = registry.SOURCES[source]
    cal = refdata.calendar(spec.calendar)
    asof = cal.prev_business_day(date.today())
    files = list(spec.fetch(asof, UNITS[source], RequestsHttp()))
    assert files and all(f.content for f in files)
