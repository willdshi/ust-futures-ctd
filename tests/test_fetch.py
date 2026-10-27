from datetime import date

from fakes import FakeHttp, gov_routes, ok

from ctd.data import manifest as mf
from ctd.data import registry
from ctd.data.fetch import fetch_date
from ctd.data.http import Response
from ctd.data.inbox import ingest

FRI = date(2026, 10, 16)
MON = date(2026, 10, 19)
CME_IDS = {"cme_fut", "cme_bulletin", "cme_stir"}
DATABENTO = "databento_daily"


def run(store, http, asof=FRI, today=FRI, **kw):
    gaps = fetch_date(asof, store, http, today=today, log=lambda _: None, **kw)
    return gaps, mf.load(store, asof)


def statuses(man):
    return {sid: s["status"] for sid, s in man["sources"].items()}


def test_auto_sources_ok_and_cme_manual_needed(store):
    gaps, man = run(store, FakeHttp(gov_routes()))
    st = statuses(man)
    assert set(st) == {s.id for s in registry.daily()}
    assert "cme_opt" not in st  # occasional: never expected
    assert store.names(FRI, "cme_tcf", "csv") == ["TCF_20261016.csv"]
    for sid, status in st.items():
        if sid in CME_IDS:
            assert status == mf.MANUAL_NEEDED
        elif sid == DATABENTO:  # collected from 2026-10-26
            assert status == mf.NOT_EXPECTED
        else:
            assert status == mf.OK, sid
    assert {g.source for g in gaps} == CME_IDS
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


def test_cme_sources_are_never_downloaded(store):
    http = FakeHttp([])
    _, man = run(store, http, sources=[registry.SOURCES[s] for s in sorted(CME_IDS)], fill_missing=False)
    assert set(man["sources"]["cme_fut"]["units"]) == {"ZT", "ZF", "ZN", "TN", "ZB", "UB"}
    assert set(statuses(man).values()) == {mf.MANUAL_NEEDED}
    assert http.calls == []


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


def test_save_keeps_entries_written_by_another_run(store):
    from ctd.data import manifest

    class Interleaved(FakeHttp):
        """While this run fetches FRED, another run records td_prices in the same manifest."""

        def get(self, url, params=None, headers=None):
            if url.startswith("https://fred") and not manifest.load(store, FRI)["sources"]:
                manifest.save(store, FRI, {"asof": FRI.isoformat(), "sources": {"td_prices": {"status": "ok"}}})
            return super().get(url, params, headers)

    _, man = run(store, Interleaved(gov_routes()), sources=[registry.SOURCES["fred"]], fill_missing=False)
    assert statuses(man) == {"td_prices": mf.OK, "fred": mf.OK}


def test_no_data_on_an_old_date_is_not_a_gap(store):
    empty = [("POST", "https://www.treasurydirect.gov/GA-FI/FedInvest/securityPriceDetail", ok("x", b""))]
    spec = [registry.SOURCES["td_prices"]]
    old = date(2024, 11, 28)  # Thanksgiving 2024: not in the holiday list, no prices published
    gaps, man = run(store, FakeHttp(empty + gov_routes()), asof=old, today=MON, sources=spec, fill_missing=False)
    assert statuses(man)["td_prices"] == mf.NOT_EXPECTED and not gaps
    http = FakeHttp(gov_routes())
    run(store, http, asof=old, today=MON, sources=spec, fill_missing=False)
    assert http.calls == []  # settled: not asked again
    # The same empty answer for a recent date is a failure, retried on the next run.
    _, man = run(store, FakeHttp(empty + gov_routes()), sources=spec)
    assert statuses(man)["td_prices"] == mf.FAILED


def test_occasional_source_is_never_a_gap(store):
    gaps, man = run(store, FakeHttp([]), sources=[registry.SOURCES["cme_opt"]], fill_missing=False)
    assert statuses(man)["cme_opt"] == mf.MANUAL_NEEDED and not gaps


def test_bulletin_drop_counts_as_collected(store, tmp_path):
    p = tmp_path / "inbox" / FRI.isoformat() / "cme_bulletin" / "Section42.pdf"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"%PDF-1.4")
    ingest(store, tmp_path / "inbox", registry.units_for)
    gaps, man = run(store, None, sources=[registry.SOURCES["cme_bulletin"]], fill_missing=False)
    assert statuses(man)["cme_bulletin"] == mf.OK and not gaps


def test_provisional_td_prices_replaced_once_complete(store):
    """The one exception to never overwriting: a same-evening TreasuryDirect file (no end-of-day
    prices) is pulled again on later runs and replaced by the completed file, never by a worse one."""
    from fakes import TD
    from ctd.data import td_prices

    evening = b"912810XX0,MARKET BASED BOND,0.045,08/15/2046,,98.6,98.5,0.000000\n"
    complete = b"912810XX0,MARKET BASED BOND,0.045,08/15/2046,,98.6,98.5,98.4\n"
    served = {"body": evening}
    route = ("POST", TD + "securityPriceDetail", lambda url, p: ok(url, served["body"], "application/csv"))
    http = FakeHttp([route] + gov_routes())
    td = [registry.SOURCES["td_prices"]]
    unit = lambda man: man["sources"]["td_prices"]["units"]["securityprice"]  # noqa: E731
    name = "securityprice_2026-10-16.csv"

    assert td_prices.provisional(evening) and not td_prices.provisional(complete)
    assert td_prices.provisional(b"garbage")

    _, man = run(store, http, sources=td)
    assert unit(man)["provisional"] == [name] and unit(man)["status"] == mf.OK
    assert store.read(FRI, "td_prices", "securityprice", name) == evening

    _, man = run(store, http, sources=td, today=MON)  # still provisional upstream: kept, retried
    assert store.read(FRI, "td_prices", "securityprice", name) == evening
    assert "replaced" not in store.meta(FRI, "td_prices", "securityprice", name)

    served["body"] = complete
    _, man = run(store, http, sources=td, today=MON)
    assert store.read(FRI, "td_prices", "securityprice", name) == complete
    assert "provisional" not in unit(man)
    meta = store.meta(FRI, "td_prices", "securityprice", name)
    assert [r["bytes"] for r in meta["replaced"]] == [len(evening)]

    served["body"] = evening  # a complete file is never fetched or replaced again
    n = len(http.calls)
    run(store, http, sources=td, today=MON)
    assert len(http.calls) == n
    assert store.read(FRI, "td_prices", "securityprice", name) == complete
