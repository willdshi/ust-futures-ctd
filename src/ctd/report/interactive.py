"""The report pages' charts, drawn in the browser with plotly.js: charts 1 and 2 linked, and chart 3.

``report.page`` puts each contract's profile and series into its pages as JSON (``chart_data``),
one block of chart containers per contract (``section``), and the script that draws them
(``SCRIPT``, with plotly.js from a CDN, pinned), so each page is one static file that needs no
server (GitHub Pages). Only model outputs go in: DV01s, key-rate DV01s, shares, effective
maturities and probabilities, no market prices. The same charts as PNGs (``report.charts``) are
written beside the pages, for the README, the writeup and print.

- Chart 1: the DV01 profile; hovering names the CTD at the shift and the likeliest CTDs at
  delivery from that state, and the heatmap gives each bucket's share.
- Chart 2: the change in each key-rate DV01 from today at the shift selected on chart 1 (hover to
  move it, click to pin it, or the slider), with the CTD-based change as a marker; the PNG shows
  only ±1σ and ±2σ.
- Chart 3: DV01 and effective maturity through time (``report.series``), up to the page's date.
  A CTD change is a marker and the hover names the CTD. ±1σ is a band (outputs.md), guides mark
  basket changes only, and dragging zooms the dates with the y-axes refitted to the window.
"""

import json
from html import escape

import numpy as np
from scipy.special import ndtri

from ctd.report import charts, series
from ctd.report.names import bond_name
from ctd.risk.dv01 import dollars

PLOTLY = "https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"
SHOWN = 0.01  # bonds named in the hover: probability at least this at the shift
TOP = 4  # at most this many


def _k(v) -> np.ndarray:
    return dollars(np.asarray(v, dtype=float)) / 1000


def _r(a, n: int) -> list:
    """Rounded, with NaN as None (JSON has no NaN)."""
    a = np.asarray(a, dtype=float)
    out = np.round(a, n).astype(object)
    out[np.isnan(a)] = None
    return out.tolist()


def series_payload(rows: list[series.Row]) -> dict:
    """One contract's chart 3 series, in $k per bp per $100mm and years."""
    def k(f):
        return _r(_k([f(r) for r in rows]), 2)

    return {
        "dates": [f"{r.asof.day} {r.asof:%b %Y}" for r in rows], "ticks": [f"{r.asof.day} {r.asof:%b}" for r in rows],
        "dv01": k(lambda r: r.dv01), "plus1": k(lambda r: r.states[1]), "minus1": k(lambda r: r.states[-1]),
        "ctd_dv01": k(lambda r: r.ctd_dv01), "constant_dv01": k(lambda r: r.constant_dv01),
        "em": _r([r.em for r in rows], 2), "ctd_em": _r([r.ctd_em for r in rows], 2),
        "constant_em": _r([r.constant_em for r in rows], 2),
        "ctd": [r.ctd_name for r in rows], "p_ctd": _r([r.p_ctd for r in rows], 3),
        "nearest": _r([r.nearest_sigmas for r in rows], 2), "constant_name": rows[0].constant_name,
        "ctd_change": [series.CTD in r.events for r in rows],
        "events": [", ".join(e for e in r.events if e != series.CTD) for r in rows],
    }


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

CSS = """
figure.plot { padding: 4px 8px 8px; }
.chart1 { height: 600px; } .chart2 { height: 360px; } .chart3 { height: 560px; }
figure.wide { flex-basis: 100%; max-width: none; }
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

function chart3(el, c) {
  const s = c.series, n = s.dates.length, markers = n <= 60 ? "lines+markers" : "lines";
  const step = Math.max(1, Math.ceil(n / 10)), ticks = s.dates.map((_, i) => i).filter(i => i % step === 0);
  const nearest = s.nearest.map(v => v === null ? "none in range" : v.toFixed(1) + "σ");
  const events = s.events.map(e => e ? "<br>" + e : "");
  const changes = s.dates.map((_, i) => i).filter(i => s.ctd_change[i]);
  const traces = [
    { x: s.dates, y: s.dv01, mode: markers, line: { color: S.series, width: 2.5 }, marker: { size: 5 },
      name: "probability-weighted", customdata: s.dates.map((_, i) => [s.plus1[i], s.minus1[i], nearest[i], events[i]]),
      hovertemplate: "<b>%{y:.1f}k</b> probability-weighted (−1σ %{customdata[1]:.1f}k, +1σ %{customdata[0]:.1f}k)" +
        "<br>nearest switch %{customdata[2]}%{customdata[3]}<extra></extra>" },
    { x: s.dates, y: s.plus1, line: { width: 0 }, hoverinfo: "skip", showlegend: false },
    { x: s.dates, y: s.minus1, fill: "tonexty", fillcolor: "rgba(134,182,239,0.25)", line: { width: 0 },
      name: "−1σ to +1σ", hoverinfo: "skip" },
    { x: s.dates, y: s.ctd_dv01, line: { color: S.muted, width: 1, shape: "hvh" }, name: "CTD-based",
      customdata: s.dates.map((_, i) => [s.ctd[i], s.p_ctd[i]]),
      hovertemplate: "%{y:.1f}k CTD-based: %{customdata[0]}, P(remains CTD) %{customdata[1]:.0%}<extra></extra>" },
    { x: s.dates, y: s.constant_dv01, line: { color: S.ink2, width: 1, dash: "dash" },
      name: `constant CTD (${s.constant_name})`, hovertemplate: "%{y:.1f}k constant CTD<extra></extra>" },
    { x: changes.map(i => s.dates[i]), y: changes.map(i => s.ctd_dv01[i]), mode: "markers", name: "CTD change",
      marker: { symbol: "circle-open", size: 8, color: S.ink2, line: { width: 1.5 } }, hoverinfo: "skip" },
    { x: s.dates, y: s.em, yaxis: "y2", mode: markers, line: { color: S.series, width: 2.5 }, marker: { size: 5 },
      showlegend: false, hovertemplate: "<b>%{y:.1f}y</b> probability-weighted<extra></extra>" },
    { x: s.dates, y: s.ctd_em, yaxis: "y2", line: { color: S.muted, width: 1, shape: "hvh" }, showlegend: false,
      hovertemplate: "%{y:.1f}y CTD-based<extra></extra>" },
    { x: s.dates, y: s.constant_em, yaxis: "y2", line: { color: S.ink2, width: 1, dash: "dash" }, showlegend: false,
      hovertemplate: "%{y:.1f}y constant CTD<extra></extra>" },
  ];
  const basket = s.dates.map((d, i) => [d, s.events[i]]).filter(([, e]) => e);
  const layout = {
    font, paper_bgcolor: S.surface, plot_bgcolor: S.surface, margin: { l: 64, r: 16, t: 96, b: 48 },
    title: { text: `${c.contract} DV01 through time, ${s.dates[0]} to ${s.dates[n - 1]}`, x: 0.01, xanchor: "left",
             y: 0.985, yref: "container", yanchor: "top", font: { size: 15, color: S.ink } },
    hovermode: "x unified", hoverlabel: { bgcolor: S.surface, bordercolor: S.axis, font: { color: S.ink } },
    dragmode: "zoom", showlegend: true,
    legend: { orientation: "h", x: 0, y: 0.92, yref: "container", yanchor: "top", font: { size: 11 },
              traceorder: "normal" },
    xaxis: { ...axis, fixedrange: false, type: "category", anchor: "y2", tickvals: ticks.map(i => s.dates[i]),
             ticktext: ticks.map(i => s.ticks[i]), showspikes: true, spikemode: "across", spikesnap: "cursor",
             spikecolor: S.ink2, spikethickness: 1, spikedash: "solid" },
    yaxis: { ...axis, domain: [0.4, 1], title: { text: "futures DV01 ($k per bp per $100mm)" } },
    yaxis2: { ...axis, domain: [0, 0.32], title: { text: "effective maturity (years)" } },
    shapes: basket.map(([d]) => ({ type: "line", xref: "x", yref: "paper", x0: d, x1: d, y0: 0, y1: 1,
                                   line: { color: S.axis, width: 1, dash: "dot" } })),
    annotations: basket.map(([d, e]) => ({ x: d, y: 1, xref: "x", yref: "paper", yanchor: "bottom", text: e,
                                           showarrow: false, font: { size: 10, color: S.ink2 } })),
  };
  return Plotly.newPlot(el, traces, layout, config).then(() => fitOnZoom(el, s));
}

// a date zoom refits both y-axes to the dates in view; double-click resets
function fitOnZoom(el, s) {
  const top = [s.dv01, s.plus1, s.minus1, s.ctd_dv01, s.constant_dv01], bottom = [s.em, s.ctd_em, s.constant_em];
  const fit = (series, i0, i1) => {
    const v = series.flatMap(a => a.slice(i0, i1 + 1)).filter(x => x !== null);
    const lo = Math.min(...v), hi = Math.max(...v), pad = 0.06 * (hi - lo || 1);
    return [lo - pad, hi + pad];
  };
  el.on("plotly_relayout", e => {
    if (e["xaxis.autorange"]) {
      Plotly.relayout(el, { "yaxis.autorange": true, "yaxis2.autorange": true });
    } else if ("xaxis.range[0]" in e) {
      const n = s.dates.length;
      const i0 = Math.max(0, Math.ceil(e["xaxis.range[0]"])), i1 = Math.min(n - 1, Math.floor(e["xaxis.range[1]"]));
      if (i1 > i0) Plotly.relayout(el, { "yaxis.range": fit(top, i0, i1), "yaxis2.range": fit(bottom, i0, i1) });
    }
  });
}

for (const c of D.contracts) {
  const section = document.getElementById(c.contract);
  Promise.all([chart1(section.querySelector(".chart1"), c), chart2(section.querySelector(".chart2"), c)])
    .then(() => link(section, c));
  if (c.series) chart3(section.querySelector(".chart3"), c);
}
"""


NOTE = (
    "<p class='note'><b>Left:</b> futures DV01 at each shift, with the vol ±10% band and the CTD-based staircase; "
    "below, each key rate's share of that DV01 (key rates are measured against the Treasury par curve, so "
    "low-coupon bonds load more than 100% at their own maturity and negatively at shorter tenors). Hover to read "
    "the CTD at a shift and the likeliest CTDs at delivery from there. <b>Right:</b> the change in each key-rate "
    "DV01 from today at the shift selected on the left: hover to move it, click to pin it, or use the slider. "
    "Markers are the CTD-based change, which jumps at each switch. <b>Below:</b> DV01 and effective maturity on "
    "each date, against the CTD-based figures and the first date's CTD held throughout; the gap between that "
    "constant-CTD line and the probability-weighted line is the part of the change caused by the basket. Circles "
    "mark a change of CTD, which the hover names. Drag across dates to zoom, double-click to reset.</p>")


def chart_data(recs: list[dict], history: dict[str, list[series.Row]]) -> list[dict]:
    """Each contract's numbers for its charts; chart 3's series from two dates on."""
    out = []
    for r in recs:
        c = payload(r)
        rows = history.get(r["contract"], [])
        if len(rows) >= 2:
            c["series"] = series_payload(rows)
        out.append(c)
    return out


def scripts(data: list[dict]) -> tuple[str, str]:
    """The page's head script (plotly.js) and its closing scripts: the data and the drawing code."""
    blob = json.dumps({"style": STYLE, "contracts": data}, ensure_ascii=False,
                      separators=(",", ":")).replace("</", "<\\/")
    return (f"<script src='{PLOTLY}'></script>",
            f"<script type='application/json' id='data'>{blob}</script>\n<script>{SCRIPT}</script>")


def section(c: dict, heading: str = "") -> str:
    """One contract's chart containers, filled in the browser; ``heading`` above them."""
    n = len(c["x"]) - 1
    return (f"<section id='{escape(c['contract'])}'>{heading}<div class='grid'>"
            f"<figure class='plot'><div class='chart1'></div></figure>"
            f"<figure class='plot'><div class='chart2'></div><div class='control'>"
            f"<label for='s-{escape(c['contract'])}'>shift</label>"
            f"<input type='range' id='s-{escape(c['contract'])}' min='0' max='{n}' step='1' value='{c['default']}'>"
            f"<span class='readout'></span></div></figure>"
            + ("<figure class='plot wide'><div class='chart3'></div></figure>" if "series" in c else "")
            + "</div></section>")
