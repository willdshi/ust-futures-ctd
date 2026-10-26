"""The interactive single-date page: charts 1 and 2 linked, drawn in the browser with plotly.js.

A companion to the static page (``report.page``), from the same saved results: each contract's
profile goes into the page as JSON and plotly.js (from a CDN, pinned) draws it, so the page is one
static file that needs no server (GitHub Pages). Only model outputs go in: DV01s, key-rate DV01s,
shares and probabilities by shift, no market prices.

- Chart 1: the DV01 profile as on the static page; hovering names the CTD at the shift and the
  likeliest CTDs at delivery from that state, and the heatmap gives each bucket's share.
- Chart 2: the change in each key-rate DV01 from today at the shift selected on chart 1 (hover to
  move it, click to pin it, or the slider), with the CTD-based change as a marker; the static
  page shows only ±1σ and ±2σ.
"""

import json
from datetime import date
from html import escape
from pathlib import Path

import numpy as np
from scipy.special import ndtri

from ctd.report import charts, page, results
from ctd.report.names import bond_name
from ctd.risk.dv01 import dollars

PLOTLY = "https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"
SHOWN = 0.01  # bonds named in the hover: probability at least this at the shift
TOP = 4  # at most this many


def _k(v) -> np.ndarray:
    return dollars(np.asarray(v, dtype=float)) / 1000


def _r(a, n: int) -> list:
    return np.round(np.asarray(a, dtype=float), n).tolist()


def payload(rec: dict) -> dict:
    """One contract's numbers for the page, in $k per bp per $100mm and % of DV01."""
    pr = rec["profile"]
    cu, pts = pr["curve"], pr["points"]
    x = np.array(cu["centres"])
    i0 = int(np.argmin(np.abs(x)))
    names = {b["cusip"]: bond_name(b["coupon"], b["maturity"]) for b in rec["basket"]}
    nodes = np.array(rec["krd"]["nodes"])

    dv01 = np.array(cu["dv01"])
    shares = 100 * np.array(cu["krd"]) / dv01[:, None]
    rows = charts.share_rows(shares)
    keep = charts.used_buckets(cu, i0)
    krd, label = _k(cu["krd"])[:, keep], _k(cu["label_krd"])[:, keep]
    change, label_change = krd - krd[i0], label - label[i0]

    probs = {c: np.array(p) for c, p in cu["probs"].items()}
    likeliest = []
    for i in range(len(x)):
        top = sorted(((p[i], c) for c, p in probs.items() if p[i] >= SHOWN), reverse=True)[:TOP]
        likeliest.append(", ".join(f"{names[c]} {100 * p:.0f}%" for p, c in top))

    pct_ticks = [(float(pr["width"] * ndtri(p / 100)), p) for p in charts.PERCENTILES]
    pct_ticks = [(bp, p) for bp, p in pct_ticks if x[0] <= bp <= x[-1]]
    states = [(s, c, d) for s, c, d in zip(pr["points_sigma"], pts["centres"], pts["dv01"]) if x[0] <= c <= x[-1]]
    plus_1 = next((c for s, c, _ in states if s == 1), x[-1])
    span = np.r_[change.ravel(), label_change.ravel()]
    return {
        "contract": rec["contract"], "asof": rec["asof"], "horizon": rec["horizon"],
        "x": _r(x, 2), "today": i0, "percentile": _r(100 * np.array(cu["percentiles"]), 1),
        "dv01": _r(_k(dv01), 2), "label_dv01": _r(_k(cu["label_dv01"]), 2),
        "band": [_r(_k(pr["band_dv01"]["vol_down"]), 2), _r(_k(pr["band_dv01"]["vol_up"]), 2)],
        "ctd": [names[c] for c in cu["label"]], "likeliest": likeliest,
        "states": [{"label": charts.SIGMA[s], "x": round(c, 2), "dv01": round(float(_k(d)), 2)} for s, c, d in states],
        "pct_ticks": [[round(bp, 2), f"{p:g}"] for bp, p in pct_ticks],
        "share_nodes": [f"{n:g}y" for n in nodes[rows]], "shares": _r(shares[:, rows].T, 1),
        "krd_nodes": [f"{n:g}y" for n in nodes[keep]], "change": _r(change, 2), "label_change": _r(label_change, 2),
        "change_range": [round(float(span.min()), 1), round(float(span.max()), 1)],
        "default": int(np.argmin(np.abs(x - plus_1))),  # chart 2 opens at +1σ
    }


_LO, _HI = charts.SHARE_STOPS[0][0], charts.SHARE_STOPS[-1][0]
STYLE = {
    "surface": charts.SURFACE, "ink": charts.INK, "ink2": charts.INK2, "muted": charts.MUTED, "grid": charts.GRID,
    "axis": charts.AXIS, "series": charts.SERIES, "rally": charts.STATES[-2], "selloff": charts.STATES[2],
    "shift_axis": charts.LIGHT_MODEL_SHIFT_AXIS,
    # plotly maps z linearly from zmin to zmax, so the stops go in at their linear positions
    "share_scale": [[(v - _LO) / (_HI - _LO), c] for v, c in charts.SHARE_STOPS],
    "share_range": [_LO, _HI],
}

CSS = page.CSS + """
figure.plot { padding: 4px 8px 8px; }
.chart1 { height: 600px; } .chart2 { height: 360px; }
.control { display: flex; align-items: center; gap: 12px; margin: 4px 8px 0; color: var(--ink2); font-size: 13px; }
.control input { flex: 1; }
.readout { font-variant-numeric: tabular-nums; min-width: 26ch; }
"""

SCRIPT = r"""
const D = JSON.parse(document.getElementById("data").textContent);
const S = D.style;
const bp = v => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(0) + "bp";
const font = { family: 'system-ui, -apple-system, "Segoe UI", sans-serif', size: 12, color: S.ink2 };
const axis = { gridcolor: S.grid, linecolor: S.axis, zeroline: false, tickfont: { color: S.ink2 }, fixedrange: true };
const config = { responsive: true, displayModeBar: false };

function chart1(el, c) {
  const n = c.x.length, cd = c.x.map((_, i) => [c.percentile[i], c.ctd[i], c.likeliest[i]]);
  const traces = [
    { x: c.x, y: c.band[1], line: { width: 0 }, hoverinfo: "skip", showlegend: false },
    { x: c.x, y: c.band[0], fill: "tonexty", fillcolor: "rgba(42,120,214,0.14)", line: { width: 0 },
      name: "vol ±10%", hoverinfo: "skip" },
    { x: c.x, y: c.label_dv01, line: { color: S.muted, width: 1, shape: "hvh" }, name: "CTD-based",
      hovertemplate: "CTD-based %{y:.1f}k<extra></extra>" },
    { x: c.x, y: c.dv01, line: { color: S.series, width: 2.5 }, name: "probability-weighted", customdata: cd,
      hovertemplate: "<b>%{x:+.0f}bp</b> (%{customdata[0]:.0f}th percentile)<br>DV01 %{y:.1f}k" +
        "<br>CTD at this shift: %{customdata[1]}<br>likeliest CTDs at delivery: %{customdata[2]}<extra></extra>" },
    { x: c.states.map(s => s.x), y: c.states.map(s => s.dv01), mode: "markers", hoverinfo: "skip", showlegend: false,
      marker: { size: 9, color: S.series, line: { color: S.surface, width: 1.5 } } },
    { x: c.x, y: c.share_nodes, z: c.shares, type: "heatmap", xaxis: "x", yaxis: "y2", ygap: 2,
      colorscale: S.share_scale, zmin: S.share_range[0], zmax: S.share_range[1],
      colorbar: { title: { text: "share of<br>DV01 (%)", font: { size: 11 } }, y: 0, yanchor: "bottom", len: 0.36,
                  thickness: 12, outlinewidth: 0, tickfont: { size: 11 } },
      hovertemplate: "%{x:+.0f}bp, %{y}: %{z:.0f}% of DV01<extra></extra>" },
  ];
  const guides = c.states.map(s => ({ type: "line", xref: "x", yref: "paper", x0: s.x, x1: s.x, y0: 0, y1: 1,
                                      line: { color: S.axis, width: 1 } }));
  const layout = {
    // top to bottom: title, legend, then the percentile axis on the plot
    font, paper_bgcolor: S.surface, plot_bgcolor: S.surface, margin: { l: 64, r: 16, t: 124, b: 52 },
    title: { text: `${c.contract} DV01 profile, ${c.asof}`, x: 0.01, xanchor: "left", y: 0.985, yref: "container",
             yanchor: "top", font: { size: 15, color: S.ink } },
    hovermode: "x", hoverlabel: { bgcolor: S.surface, bordercolor: S.axis, font: { color: S.ink } },
    showlegend: true, legend: { orientation: "h", x: 0, y: 0.935, yref: "container", yanchor: "top", font: { size: 11 } },
    xaxis: { ...axis, anchor: "y2", range: [c.x[0], c.x[n - 1]], title: { text: S.shift_axis },
             showspikes: true, spikemode: "across", spikesnap: "cursor", spikecolor: S.ink2, spikethickness: 1,
             spikedash: "solid" },
    xaxis2: { ...axis, overlaying: "x", side: "top", anchor: "y", range: [c.x[0], c.x[n - 1]], showgrid: false,
              tickvals: c.pct_ticks.map(t => t[0]), ticktext: c.pct_ticks.map(t => t[1]),
              title: { text: `percentile of the move to implied delivery (${c.horizon})`, font: { size: 11 } } },
    yaxis: { ...axis, domain: [0.44, 1], title: { text: "futures DV01 ($k per bp per $100mm)" } },
    yaxis2: { ...axis, domain: [0, 0.36], title: { text: "key rate" }, showgrid: false },
    shapes: guides.concat([{ type: "line", xref: "x", yref: "paper", x0: c.x[c.default], x1: c.x[c.default],
                             y0: 0, y1: 1, line: { color: S.ink, width: 1.5, dash: "dot" } }]),
    annotations: c.states.map(s => ({ x: s.x, y: 0.44, xref: "x", yref: "paper", yanchor: "bottom", text: s.label,
                                      showarrow: false, font: { size: 11, color: S.ink2 } })),
  };
  // the percentile axis needs a trace on it to be drawn
  traces.push({ x: [c.x[0], c.x[n - 1]], y: [null, null], xaxis: "x2", yaxis: "y", hoverinfo: "skip", showlegend: false });
  return Plotly.newPlot(el, traces, layout, config);
}

function chart2(el, c) {
  const layout = {
    font, paper_bgcolor: S.surface, plot_bgcolor: S.surface, margin: { l: 64, r: 16, t: 56, b: 44 },
    title: { text: "", x: 0, xanchor: "left", font: { size: 15, color: S.ink } }, bargap: 0.35,
    showlegend: true, legend: { orientation: "h", x: 0, y: 1, yanchor: "bottom", font: { size: 11 } },
    hoverlabel: { bgcolor: S.surface, bordercolor: S.axis, font: { color: S.ink } },
    xaxis: { ...axis, title: { text: "key rate" }, showgrid: false },
    yaxis: { ...axis, title: { text: "change from today ($k per bp per $100mm)" },
             range: [c.change_range[0] * 1.1 - 2, c.change_range[1] * 1.1 + 2], zeroline: true, zerolinecolor: S.axis },
  };
  const traces = [
    { x: c.krd_nodes, y: c.change[c.default], type: "bar", name: "probability-weighted", marker: { color: S.selloff },
      hovertemplate: "%{x}: %{y:+.1f}k<extra></extra>" },
    { x: c.krd_nodes, y: c.label_change[c.default], mode: "markers", name: "CTD-based",
      marker: { symbol: "line-ew-open", size: 22, color: S.ink2, line: { width: 2, color: S.ink2 } },
      hovertemplate: "%{x}, CTD-based: %{y:+.1f}k<extra></extra>" },
  ];
  return Plotly.newPlot(el, traces, layout, config);
}

// index of the shift nearest x (shifts are increasing)
function nearest(c, x) {
  let lo = 0, hi = c.x.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (c.x[m] <= x) lo = m; else hi = m; }
  return x - c.x[lo] <= c.x[hi] - x ? lo : hi;
}

function link(section, c) {
  const [el1, el2] = section.querySelectorAll(".chart1, .chart2");
  const slider = section.querySelector("input"), readout = section.querySelector(".readout");
  let pinned = false, shown = -1;
  const show = i => {
    if (i === shown) return;
    shown = i;
    const x = c.x[i], color = x < 0 ? S.rally : S.selloff;
    Plotly.restyle(el2, { y: [c.change[i], c.label_change[i]], "marker.color": [color, S.ink2] }, [0, 1]);
    Plotly.relayout(el2, { "title.text": `${c.contract} key-rate DV01 change at ${bp(x)} ` +
                                         `(${c.percentile[i].toFixed(0)}th percentile)` });
    Plotly.relayout(el1, { [`shapes[${c.states.length}].x0`]: x, [`shapes[${c.states.length}].x1`]: x });
    slider.value = i;
    readout.textContent = `${bp(x)}, CTD ${c.ctd[i]}` + (pinned ? " (pinned)" : "");
  };
  el1.on("plotly_hover", e => { if (!pinned) show(nearest(c, e.points[0].x)); });
  el1.on("plotly_click", e => { pinned = !pinned; shown = -1; show(nearest(c, e.points[0].x)); });
  slider.addEventListener("input", () => { pinned = true; shown = -1; show(+slider.value); });
  show(c.default);
}

for (const c of D.contracts) {
  const section = document.getElementById(c.contract);
  Promise.all([chart1(section.querySelector(".chart1"), c), chart2(section.querySelector(".chart2"), c)])
    .then(() => link(section, c));
}
"""


def _section(c: dict) -> str:
    n = len(c["x"]) - 1
    return (f"<section id='{escape(c['contract'])}'><h2>{escape(c['contract'])}</h2><div class='grid'>"
            f"<figure class='plot'><div class='chart1'></div></figure>"
            f"<figure class='plot'><div class='chart2'></div><div class='control'>"
            f"<label for='s-{escape(c['contract'])}'>shift</label>"
            f"<input type='range' id='s-{escape(c['contract'])}' min='0' max='{n}' step='1' value='{c['default']}'>"
            f"<span class='readout'></span></div></figure></div></section>")


def render(asof: date, recs: list[dict]) -> str:
    """The interactive page for ``asof`` from that date's results, in contract order."""
    page.check_schema(recs)
    payloads = [payload(r) for r in recs]
    data = json.dumps({"style": STYLE, "contracts": payloads}, ensure_ascii=False,
                      separators=(",", ":")).replace("</", "<\\/")
    contracts = ", ".join(r["contract"] for r in recs)
    body = "\n".join([
        f"<h1>Treasury futures duration profile, {asof}</h1>",
        f"<p class='lede'>{contracts}. {page.LIGHT_MODEL_LEDE}</p>",
        "<p class='note'><b>Left:</b> futures DV01 at each shift, with the vol ±10% band and the CTD-based staircase; "
        "below, each key rate's share of that DV01. Hover to read the CTD at a shift and the likeliest CTDs at "
        "delivery from there. <b>Right:</b> the change in each key-rate DV01 from today at the shift selected on the "
        "left: hover to move it, click to pin it, or use the slider. Markers are the CTD-based change, which "
        "jumps at each switch.</p>",
        *(_section(c) for c in payloads),
    ])
    return (f"<!doctype html>\n<html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>CTD profile {asof}</title><style>{CSS}</style>"
            f"<script src='{PLOTLY}'></script></head>\n<body><main>\n{body}\n</main>\n"
            f"<script type='application/json' id='data'>{data}</script>\n<script>{SCRIPT}</script>\n"
            f"</body></html>\n")


def write(root: Path, out_dir: Path, asof: date, contracts: list[str] | None = None) -> Path:
    """Write ``out_dir/interactive/<asof>.html`` from the results saved under ``root``."""
    contracts = contracts or page.contracts_on(root, asof)
    if not contracts:
        raise FileNotFoundError(f"no saved results for {asof}; run ctd run first")
    recs = []
    for c in contracts:
        path = results.light_path(root, c, asof)
        if not path.exists():
            raise FileNotFoundError(f"no saved result for {c} on {asof} ({path})")
        recs.append(json.loads(path.read_text(encoding="utf-8")))
    out = Path(out_dir) / "interactive" / f"{asof.isoformat()}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(asof, recs), encoding="utf-8")
    return out
