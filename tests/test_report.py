"""The single-date report (phase 1c item 5): the charts as PNGs and the HTML pages, from saved results."""

import json
import re
from datetime import date

import numpy as np
import pytest
from test_light import ASOF, inputs

from ctd.cli import main
from ctd.model.light import run
from ctd.report import charts, interactive, page, results

PNG = b"\x89PNG\r\n\x1a\n"


def _contracts(html: str) -> list[str]:
    """The contracts whose charts the page draws, from its embedded data."""
    m = re.search(r"<script type='application/json' id='data'>(.*?)</script>", html, re.S)
    return [c["contract"] for c in json.loads(m[1].replace("<\\/", "</"))["contracts"]]


def _urls(html: str) -> list[str]:
    return re.findall(r"https?://[^'\"\s<>]+", html)


@pytest.fixture(scope="module")
def rec():
    return results.light_record(run(inputs()), [], "abc1234")


def test_bond_names():
    assert page.bond_name(0.0475, "2045-05-15") == "4¾% May-45"
    assert page.bond_name(0.05, "2045-05-15") == "5% May-45"
    assert page.bond_name(0.04125, "2032-11-15") == "4⅛% Nov-32"
    assert page.bond_name(0.00125, "2030-01-31") == "⅛% Jan-30"
    assert page.bond_name(0.04333, "2030-01-31") == "4.333% Jan-30"


def test_charts_are_pngs_and_the_same_result_draws_the_same_bytes(rec):
    for draw in (charts.profile_chart, charts.krd_change_chart):
        png = draw(rec)
        assert png.startswith(PNG) and png == draw(rec)
        assert b"Software" not in png  # no version stamp, so a redraw doesn't differ


def test_chart_2_drops_only_the_end_buckets_nothing_loads_on():
    # today loads on 5y to 10y; a CTD-based state reaches 15y; 20y is empty but inside the range
    krd = [[0.0, 0.01, 0.03, 0.02, 0.0, 0.0, 0.0, 0.0], [0.0, 0.012, 0.03, 0.018, 0.0, 0.0, 0.0, 0.0]]
    label = [[0.0, 0.0, 0.03, 0.03, 0.0, 0.0, 0.0, 0.0], [1e-4, 0.0, 0.0, 0.02, 0.0, 0.0, 0.01, 0.0]]
    pts = {"krd": krd, "label_krd": label, "dv01": [0.06, 0.06]}
    assert charts.used_buckets(pts, 0) == slice(1, 7)  # 2y's 1e-4 is under 0.5% of the DV01; 30y is empty


def test_chart_1_rows_drop_only_the_end_buckets_nothing_loads_on():
    # % shares at three shifts: 2y and 25y under 0.5%, 5y loaded only negatively, 15y empty but inside the range
    shares = np.array([[0.1, -3.0, 60.0, 43.0, 0.0, 0.0, 0.0, 0.0],
                       [0.2, -1.0, 40.0, 50.0, 0.0, 11.0, 0.0, 0.0],
                       [0.0, 0.0, 20.0, 60.0, 0.0, 20.0, 0.4, 0.0]])
    assert charts.share_rows(shares) == slice(1, 6)


def test_chart_2_keeps_a_bucket_loaded_only_negatively(rec):
    # the 2% 2050 bond's short buckets are negative but still a load: kept
    pts = rec["profile"]["points"]
    keep = charts.used_buckets(pts, rec["profile"]["points_sigma"].index(0))
    assert keep.start == 0 and min(np.array(pts["krd"])[:, 0]) < 0


def test_nearest_switch_matches_the_model():
    r = run(inputs())
    want = {side: c and c.switch.z_bp for side, c in r.nearest().items()}
    got = page.nearest(results.light_record(r, [], None))
    assert {side: c and c["z_bp"] for side, c in got.items()} == want


TABLES = ("Probability-weighted against CTD-based DV01", "Key-rate DV01 today", "CTD probabilities",
          "Distance to each switch", "Inputs and diagnostics")


def test_summary_page_holds_the_charts_and_links_each_contract_but_no_tables(rec):
    zn = {**rec, "contract": "ZNZ6"}
    html = page.render(ASOF, [zn, rec])
    assert html.startswith("<!doctype html>") and "<title>CTD report 2026-10-21</title>" in html
    assert _contracts(html) == ["ZNZ6", "ZBZ6"] and "<section id='ZNZ6'>" in html and "<section id='ZBZ6'>" in html
    assert "<img" not in html  # the charts are drawn in the browser
    assert "<caption>" not in html and "<h3>Inputs and diagnostics" not in html  # the tables are per contract
    assert html.index("<a href='2026-10-21/ZNZ6.html'><b>ZNZ6</b></a>") < html.index("<a href='2026-10-21/ZBZ6.html'>")
    assert "<h3><a href='2026-10-21/ZBZ6.html'>ZBZ6</a></h3>" in html  # each contract's charts link too
    assert "are on its own page</span>: follow the <span class='hl'>ticker links</span>" in html
    assert "ZT (2-year) and ZF (5-year) futures are omitted" in html
    assert html.count("<a href='2026-10-21/ZBZ6.html'><b>ZBZ6</b></a>") == 2  # in both tables
    assert "<th>ticker</th><th>CTD today" in html
    assert html.index("<a href='archive.html'>All report dates</a>") < html.index("<h1>")
    assert _urls(html) == [interactive.PLOTLY]  # nothing else from the network
    assert page.render(ASOF, [zn, rec]) == html


def test_every_page_carries_the_disclaimer(rec):
    for html in (page.render(ASOF, [rec]), page.render_contract(ASOF, rec)):
        assert html.count("not investment advice") == 1 and html.index("<footer>") < html.index("</main>")


def test_contract_page_holds_its_charts_and_every_table(rec):
    html = page.render_contract(ASOF, rec)
    assert "<title>ZBZ6 CTD report 2026-10-21</title>" in html and "<a href='../2026-10-21.html'>" in html
    assert _contracts(html) == ["ZBZ6"] and "class='chart3'" not in html  # chart 3 needs two dates
    for t in TABLES:
        assert html.count(t) == 1, t
    assert html.index("class='chart1'") < html.index("<h2>Analytics</h2>")  # the charts first
    assert "<a href='2026-10-21/" not in html  # no links to itself
    assert "code abc1234" in html and _urls(html) == [interactive.PLOTLY]
    assert page.render_contract(ASOF, rec) == html


def test_page_refuses_results_from_before_the_profile(rec):
    with pytest.raises(ValueError, match="re-run ctd run"):
        page.render(ASOF, [{**rec, "schema": 7}])


def test_report_command_writes_the_date_page_in_contract_order(tmp_path, rec, capsys):
    results.write_light(tmp_path, rec)
    results.write_light(tmp_path, {**rec, "contract": "ZNZ6"})
    assert page.contracts_on(tmp_path, ASOF) == ["ZNZ6", "ZBZ6"]
    out = tmp_path / "out"
    args = ["--data-root", str(tmp_path), "report", "--asof", ASOF.isoformat(), "--out", str(out)]
    assert main(args) == 0
    html = (out / "2026-10-21.html").read_text(encoding="utf-8")
    assert html.index("ZNZ6.html") < html.index("ZBZ6.html")
    for c in ("ZNZ6", "ZBZ6"):
        assert "Distance to each switch" in (out / "2026-10-21" / f"{c}.html").read_text(encoding="utf-8")
        for name in ("dv01-profile", "krd-change"):  # chart 3 needs two dates
            assert (out / "2026-10-21" / "png" / f"{c}-{name}.png").read_bytes().startswith(PNG)
    printed = capsys.readouterr().out
    assert printed.count(".html") == 4 and "wrote 4 chart PNGs" in printed  # summary, two contracts, archive
    assert main([*args, "--contract", "ZBZ6"]) == 0
    assert "ZNZ6.html" not in (out / "2026-10-21.html").read_text(encoding="utf-8")


def test_archive_lists_every_summary_page_newest_first(tmp_path, rec):
    results.write_light(tmp_path, rec)
    out = tmp_path / "out"
    out.mkdir()
    for name in ("2026-10-16.html", "index.html", "notes.html"):  # an older summary, and pages that aren't
        (out / name).write_text("", encoding="utf-8")
    page.write(tmp_path, out, ASOF)
    html = (out / "archive.html").read_text(encoding="utf-8")
    assert re.findall(r"<a href='([^']+)'>", html) == ["2026-10-21.html", "2026-10-16.html"]
    assert "2026-10-21</a> (latest)" in html and "not investment advice" in html
    assert "<script" not in html and not _urls(html)


def test_report_command_without_results_says_so(tmp_path, capsys):
    assert main(["--data-root", str(tmp_path), "report", "--asof", "2026-10-21", "--out", str(tmp_path)]) == 1
    assert "no saved results for 2026-10-21" in capsys.readouterr().err


def test_summary_gives_both_probabilities_and_the_carry_behind_implied_delivery(rec):
    html = page.render(ASOF, [rec])
    name = page.bond_name(*next((b["coupon"], b["maturity"]) for b in rec["basket"] if b["cusip"] == rec["ctd"]))
    i = rec["profile"]["points_sigma"].index(0)
    normal = rec["profile"]["points"]["probs"][rec["ctd"]][i]
    # 5.5% yields over 3.88% SOFR: positive carry, delivery on the last day, in the column after the CTD
    assert f"{name} (O {rec['ctd_keeps'][0]:.1%}, N {normal:.1%})</td><td>31 Dec 2026</td>" in html
    assert "CTD today, P(RCaD)<sup>1</sup>" in html and "implied delivery<sup>2</sup>" in html
    assert "<sup>1</sup> P(RCaD): the probability that today's CTD remains CTD at the implied delivery date" in html
    assert ("<sup>2</sup> Implied delivery: the last delivery day if the basket's carry against term repo, weighted by "
            "each bond's option-implied probability of being CTD, is positive") in html
    i0 = rec["profile"]["points"]
    assert f"({page.duration(i0['dv01'][i], rec['f_market']):.2f}y)" in html and f"{rec['f_market']:.4f}" in html


def test_grades_in_words():
    from ctd.data import refdata
    from ctd.reference.grades import grade_for

    g = refdata.grades()
    assert page.grade_text(grade_for(g, "ZN", date(2026, 12, 1))) == "6y 6m to 8y remaining; original term at most 10y"
    assert page.grade_text(grade_for(g, "ZN", date(2023, 6, 1))) == "6y 6m to 10y remaining; original term at most 10y"
    assert page.grade_text(grade_for(g, "ZB", date(2026, 12, 1))) == "15y to under 25y remaining"
    assert page.grade_text(grade_for(g, "UB", date(2026, 12, 1))) == "25y and over remaining"
    assert "maximum from the last day" in page.grade_text(grade_for(g, "ZT", date(2026, 12, 1)))


def test_contract_table_comes_before_the_summary(rec):
    html = page.render(ASOF, [rec])
    assert html.index("U.S. Treasury Bond futures, December 2026") < html.index("CTD today, P(RCaD)")
    assert "15y to under 25y remaining" in html and "1 Dec 2026 to 31 Dec 2026" in html
    assert f"{len(rec['basket'])} issues" in html and "DEC26, expiry 20 Nov 2026" in html
