"""The interactive page: charts 1 and 2 linked in the browser, from saved results."""

import json
import re

import numpy as np
import pytest
from test_light import ASOF, inputs

from ctd.cli import main
from ctd.model.light import run
from ctd.report import charts, interactive, results


@pytest.fixture(scope="module")
def rec():
    return results.light_record(run(inputs()), [], "abc1234")


def _data(html: str) -> dict:
    m = re.search(r"<script type='application/json' id='data'>(.*?)</script>", html, re.S)
    return json.loads(m[1].replace("<\\/", "</"))


def test_payload_is_one_value_per_shift_and_changes_are_from_today(rec):
    c = interactive.payload(rec)
    n = len(c["x"])
    for key in ("percentile", "dv01", "label_dv01", "ctd", "likeliest", "change", "label_change"):
        assert len(c[key]) == n, key
    assert len(c["shares"]) == len(c["share_nodes"]) and all(len(r) == n for r in c["shares"])
    assert all(len(r) == len(c["krd_nodes"]) for r in c["change"])
    assert c["x"][c["today"]] == 0 and not any(c["change"][c["today"]]) and not any(c["label_change"][c["today"]])
    plus_1 = next(s["x"] for s in c["states"] if s["label"] == "+1σ")
    assert abs(c["x"][c["default"]] - plus_1) <= 1  # chart 2 opens at +1σ


def test_payload_matches_the_saved_result(rec):
    c = interactive.payload(rec)
    cu = rec["profile"]["curve"]
    assert c["dv01"][c["today"]] == pytest.approx(float(interactive._k(cu["dv01"][c["today"]])), abs=0.01)
    shares = 100 * np.array(cu["krd"]) / np.array(cu["dv01"])[:, None]
    assert c["share_nodes"] == [f"{n:g}y" for n in np.array(rec["krd"]["nodes"])[charts.share_rows(shares)]]


def test_share_colors_sit_at_their_linear_positions():
    # plotly maps z linearly from zmin to zmax: 0% sits a third of the way up a −50% to +100% scale
    scale = dict((c, p) for p, c in interactive.STYLE["share_scale"])
    assert scale[charts.NEUTRAL] == pytest.approx(1 / 3)
    assert interactive.STYLE["share_scale"][0][0] == 0 and interactive.STYLE["share_scale"][-1][0] == 1


def test_page_embeds_the_data_and_the_pinned_library(rec):
    html = interactive.render(ASOF, [rec])
    assert interactive.PLOTLY in html and "plotly.js-dist-min@2.35.2" in interactive.PLOTLY
    data = _data(html)
    assert [c["contract"] for c in data["contracts"]] == [rec["contract"]]
    assert f"id='{rec['contract']}'" in html
    assert html == interactive.render(ASOF, [rec])  # the same result writes the same page


def test_report_command_writes_the_interactive_page_on_request(tmp_path, rec, capsys):
    results.write_light(tmp_path, rec)
    out = tmp_path / "out"
    args = ["--data-root", str(tmp_path), "report", "--asof", ASOF.isoformat(), "--out", str(out)]
    assert main(args) == 0
    assert not (out / "interactive").exists()
    assert main([*args, "--interactive"]) == 0
    assert (out / "interactive" / f"{ASOF.isoformat()}.html").exists()
