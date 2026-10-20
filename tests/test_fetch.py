from datetime import date

from fakes import FakeHttp, cme_routes, gov_routes, ok

from ctd.data import manifest as mf
from ctd.data import registry
from ctd.data.fetch import fetch_date
from ctd.data.http import Response
from ctd.data.inbox import ingest

FRI = date(2026, 10, 16)
MON = date(2026, 10, 19)
CME_IDS = {"cme_fut", "cme_opt", "cme_stir", "cme_delivery"}


def run(store, http, asof=FRI, today=FRI, **kw):
    gaps = fetch_date(asof, store, http, today=today, log=lambda _: None, **kw)
    return gaps, mf.load(store, asof)


def statuses(man):
    return {sid: s["status"] for sid, s in man["sources"].items()}


def test_auto_sources_ok_and_cme_manual_needed(store):
    gaps, man = run(store, FakeHttp(gov_routes()))
    st = statuses(man)
    assert set(st) == {s.id for s in registry.daily()}
    for sid, status in st.items():
        if sid == "cme_delivery":
            assert status == mf.NOT_EXPECTED  # October: no deliveries
        elif sid in CME_IDS:
            assert status == mf.MANUAL_NEEDED
        else:
            assert status == mf.OK, sid
    assert {g.source for g in gaps} == CME_IDS - {"cme_delivery"}
    assert store.names(FRI, "fiscaldata_auctions", "auctions_query") == ["auctions_query_p001.json",
                                                                         "auctions_query_p002.json"]
    assert store.names(FRI, "td_prices", "securityprice") == ["securityprice_2026-10-16.csv"]
    assert (store.root / "gaps.log").read_text().count("manual_needed") == len(gaps)


def test_rerun_is_idempotent(store):
    http = FakeHttp(gov_routes())
    run(store, http)
    n = len(http.calls)
    before = {p: p.read_bytes() for p in store.asof_dir(FRI).rglob("*.gz")}
    _, man = run(store, http)
    assert len(http.calls) == n  # nothing re-downloaded
    assert {p: p.read_bytes() for p in store.asof_dir(FRI).rglob("*.gz")} == before
    assert statuses(man)["fred"] == mf.OK


def test_cme_auto(store):
    _, man = run(store, FakeHttp(gov_routes() + cme_routes()), cme_auto=True)
    assert set(man["sources"]["cme_fut"]["units"]) == {"ZT", "ZF", "ZN", "TN", "ZB", "UB"}
    assert statuses(man)["cme_fut"] == statuses(man)["cme_opt"] == statuses(man)["cme_stir"] == mf.OK
    assert "cme_cf" not in man["sources"]  # occasional: only when asked for
    _, man = run(store, FakeHttp(cme_routes()), cme_auto=True, sources=[registry.SOURCES["cme_cf"]])
    zn_opt = store.names(FRI, "cme_opt", "ZN")
    assert len(zn_opt) == 3 and "ZN_expirations_2026-10-16.json" in zn_opt  # expirations + 2 series
    assert store.names(FRI, "cme_cf", "tables") == ["cf-table.xlsx", "cf.html"]


def test_past_asof_snapshot_not_recoverable(store):
    every = [registry.SOURCES["cme_cf"], registry.SOURCES["cme_stir"]]
    _, man = run(store, FakeHttp(gov_routes() + cme_routes()), today=MON, cme_auto=True, sources=every)
    assert man["sources"]["cme_cf"]["status"] == mf.NOT_RECOVERABLE
    assert man["sources"]["cme_stir"]["status"] == mf.OK  # 1 business day back, within CME's window
    _, man = run(store, FakeHttp(gov_routes() + cme_routes()), asof=date(2026, 10, 15), today=date(2026, 10, 30),
                 cme_auto=True, sources=every)
    assert man["sources"]["cme_stir"]["status"] == mf.NOT_RECOVERABLE  # 11 business days back
    assert man["sources"]["cme_cf"]["status"] == mf.NOT_RECOVERABLE


def test_holidays_not_expected(store):
    _, man = run(store, FakeHttp(gov_routes()), asof=date(2026, 11, 26), today=date(2026, 11, 26))
    assert set(statuses(man).values()) == {mf.NOT_EXPECTED}
    _, man = run(store, FakeHttp(gov_routes()), asof=date(2026, 10, 12), today=date(2026, 10, 12))
    assert statuses(man)["td_prices"] == mf.NOT_EXPECTED  # bond market closed on Columbus Day
    assert statuses(man)["fred"] == mf.OK


def test_failing_source_does_not_stop_others(store):
    routes = [("GET", "https://fred.stlouisfed.org/", Response("x", 500, b"oops"))] + gov_routes()
    gaps, man = run(store, FakeHttp(routes))
    assert statuses(man)["fred"] == mf.FAILED
    assert "HTTP 500" in man["sources"]["fred"]["units"]["DGS10"]["error"]
    assert statuses(man)["td_prices"] == mf.OK
    assert any(g.source == "fred" for g in gaps)
    # The next run retries the failed units.
    _, man = run(store, FakeHttp(gov_routes()))
    assert statuses(man)["fred"] == mf.OK


def test_invalid_response_is_not_stored(store):
    routes = [("POST", "https://www.treasurydirect.gov/GA-FI/FedInvest/securityPriceDetail", ok("x", b""))]
    _, man = run(store, FakeHttp(routes + gov_routes()), sources=[registry.SOURCES["td_prices"]])
    assert statuses(man)["td_prices"] == mf.FAILED
    assert store.names(FRI, "td_prices", "securityprice") == []


def test_manual_drop_fills_cme_gap(store, tmp_path):
    run(store, FakeHttp(gov_routes()))
    p = tmp_path / "inbox" / FRI.isoformat() / "cme_fut" / "ZN" / "ZN_settlements.json"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"{}")
    ingest(store, tmp_path / "inbox", registry.units_for)
    _, man = run(store, None, sources=[registry.SOURCES["cme_fut"]])
    units = man["sources"]["cme_fut"]["units"]
    assert units["ZN"]["status"] == mf.OK and units["ZN"]["origin"] == "manual"
    assert units["ZB"]["status"] == mf.MANUAL_NEEDED
    assert statuses(man)["fred"] == mf.OK  # other sources keep their entries


def test_source_filter_records_others_missing(store):
    _, man = run(store, FakeHttp(gov_routes()), sources=[registry.SOURCES["fred"]])
    assert statuses(man)["fred"] == mf.OK
    assert statuses(man)["td_prices"] == mf.MISSING
