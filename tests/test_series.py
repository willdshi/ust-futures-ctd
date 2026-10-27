"""Chart 3's series (outputs.md Tier 1): rows from saved results, the chart and its page section."""

import copy
import json
import math
import re
from datetime import date

import numpy as np
import pytest
from test_light import ASOF, inputs
from test_report import PNG

from ctd.cli import main
from ctd.model.light import run
from ctd.report import charts, page, results, series


@pytest.fixture(scope="module")
def rec():
    return results.light_record(run(inputs()), [], "abc1234")


def on(rec: dict, day: str, ctd: str | None = None, drop: str | None = None) -> dict:
    """``rec`` moved to ``day``, with another CTD or a bond out of the basket."""
    r = copy.deepcopy(rec)
    r["asof"] = day
    if ctd:
        r["ctd"] = ctd
    if drop:
        r["basket"] = [b for b in r["basket"] if b["cusip"] != drop]
    return r


def other(rec: dict) -> str:
    return next(b["cusip"] for b in rec["basket"] if b["cusip"] != rec["ctd"])


def test_a_row_reads_today_and_the_states_from_the_profile(rec):
    [row] = series.series([rec])
    pts, sig = rec["profile"]["points"], rec["profile"]["points_sigma"]
    i = sig.index(0)
    assert row.asof == ASOF and row.dv01 == pts["dv01"][i] and row.ctd_dv01 == pts["label_dv01"][i]
    assert row.states == {s: pts["dv01"][j] for j, s in enumerate(sig) if s} and set(row.states) == {-2, -1, 1, 2}
    assert row.em == pts["effective_maturity"][i] and row.ctd_em == pts["label_effective_maturity"][i]
    assert row.nearest_sigmas == min(abs(c["sigmas"]) for c in rec["crossovers"])
    assert row.events == ()


def test_the_constant_ctd_bond_is_the_first_dates_ctd(rec):
    b = next(b for b in rec["basket"] if b["cusip"] == rec["ctd"])
    rows = series.series([on(rec, "2026-10-22", ctd=other(rec)), rec])  # out of order: sorted by date
    assert [r.asof for r in rows] == [ASOF, date(2026, 10, 22)]
    assert all(r.constant_dv01 == b["dv01_cf"] for r in rows)
    assert rows[0].constant_name == page.bond_name(b["coupon"], b["maturity"]) == rows[1].constant_name
    # on the first date the constant CTD is the CTD, so its effective maturity is the CTD-based one
    assert rows[0].constant_em == pytest.approx(rows[0].ctd_em, abs=1e-12)
    assert rows[0].constant_em == pytest.approx(np.dot(b["krd_shares"], rec["krd"]["nodes"]))


def test_the_constant_ctd_is_nan_once_it_leaves_the_basket(rec):
    rows = series.series([rec, on(rec, "2026-10-22", ctd=other(rec), drop=rec["ctd"])])
    assert math.isnan(rows[1].constant_dv01) and math.isnan(rows[1].constant_em)


def test_events_flag_ctd_and_basket_changes_against_the_previous_date(rec):
    rows = series.series([rec, on(rec, "2026-10-22", ctd=other(rec)), on(rec, "2026-10-23", ctd=other(rec)),
                          on(rec, "2026-10-26", ctd=other(rec), drop=rec["ctd"])])
    assert [r.events for r in rows] == [(), (series.CTD,), (), (series.BASKET,)]
    assert rows[1].ctd_name != rows[0].ctd_name


def test_series_stops_at_the_date(rec):
    rows = series.series([rec, on(rec, "2026-10-22")], until=ASOF)
    assert [r.asof for r in rows] == [ASOF]
    assert series.series([rec], until=date(2026, 10, 20)) == []


def test_chart_3_is_a_png_and_the_same_rows_draw_the_same_bytes(rec):
    rows = series.series([rec, on(rec, "2026-10-22", ctd=other(rec)), on(rec, "2026-10-23", drop=other(rec))])
    png = charts.dv01_series_chart("ZBZ6", rows)
    assert png.startswith(PNG) and png == charts.dv01_series_chart("ZBZ6", rows)


def _series_dates(html: str) -> list[str] | None:
    """Chart 3's dates as the page embeds them, or None without chart 3."""
    m = re.search(r"<script type='application/json' id='data'>(.*?)</script>", html, re.S)
    c = json.loads(m[1].replace("<\\/", "</"))["contracts"][0]
    return c["series"]["dates"] if "series" in c else None


def test_the_page_shows_chart_3_only_with_two_dates(rec):
    one = {"ZBZ6": series.series([rec])}
    assert _series_dates(page.render(ASOF, [rec], one)) is None
    two = {"ZBZ6": series.series([on(rec, "2026-10-20"), rec])}
    html = page.render(ASOF, [rec], two)
    assert _series_dates(html) == ["20 Oct 2026", "21 Oct 2026"] and "class='chart3'" in html


def test_report_command_draws_chart_3_from_results_up_to_the_date(tmp_path, rec):
    for day in ("2026-10-20", ASOF.isoformat(), "2026-10-22"):
        results.write_light(tmp_path, on(rec, day))
    out = tmp_path / "out"
    args = ["--data-root", str(tmp_path), "report", "--out", str(out), "--asof"]
    assert main([*args, "2026-10-20"]) == 0
    assert _series_dates((out / "2026-10-20.html").read_text(encoding="utf-8")) is None
    assert not (out / "2026-10-20" / "png" / "ZBZ6-dv01-series.png").exists()
    assert main([*args, ASOF.isoformat()]) == 0
    html = (out / f"{ASOF}.html").read_text(encoding="utf-8")
    assert _series_dates(html) == ["20 Oct 2026", "21 Oct 2026"]  # 10-22 is after the date
    expected = charts.dv01_series_chart("ZBZ6", series.series([on(rec, "2026-10-20"), rec]))
    assert (out / f"{ASOF}" / "png" / "ZBZ6-dv01-series.png").read_bytes() == expected


def test_report_refuses_an_old_result_in_the_history(tmp_path, rec):
    results.write_light(tmp_path, {**on(rec, "2026-10-20"), "schema": 7})
    results.write_light(tmp_path, rec)
    assert main(["--data-root", str(tmp_path), "report", "--asof", ASOF.isoformat(), "--out", str(tmp_path)]) == 1
