from datetime import date

from fakes import FakeHttp, gov_routes

from ctd.data import yahoo_fut


def test_contract_tickers_roll_with_the_asof_month():
    assert yahoo_fut.contract_tickers("ZN", date(2026, 10, 19)) == ["ZNZ26.CBT", "ZNH27.CBT", "ZNM27.CBT", "ZNU27.CBT"]
    assert yahoo_fut.contract_tickers("ZB", date(2026, 12, 15))[0] == "ZBZ26.CBT"  # still in its delivery month
    assert yahoo_fut.contract_tickers("ZT", date(2027, 1, 4))[0] == "ZTH27.CBT"


def test_daily_fetch_skips_tickers_yahoo_lacks_and_asks_for_10_days():
    http = FakeHttp(gov_routes())
    files = list(yahoo_fut.fetch(date(2026, 10, 19), "ZN", http))
    assert [f.name for f in files] == ["ZNZ26.CBT_2026-10-09_2026-10-19.json", "ZNH27.CBT_2026-10-09_2026-10-19.json",
                                       "ZNU27.CBT_2026-10-09_2026-10-19.json", "ZN=F_2026-10-09_2026-10-19.json"]
    params = http.calls[0][2]
    assert int(params["period2"]) - int(params["period1"]) == 11 * 86400  # 10 days back through the as-of date


def test_backfill_names_files_as_history():
    files = list(yahoo_fut.fetch_history(date(2026, 10, 19), "UB", FakeHttp(gov_routes())))
    assert files[0].name == "UBZ26.CBT_history_2026-10-19.json" and files[0].params["period1"] == "946684800"
