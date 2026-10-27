"""The single-date report: one self-contained HTML page per as-of date (phase 1c item 5).

    output/2026-10-21.html

Built from the saved results of every contract run on that date (``report.results``), never from a
model run, so the page can be redrawn from the files alone. Charts 1 and 2 (``report.charts``) as
base64 PNGs, as small multiples across contracts; chart 3 from each contract's results up to that
date (``report.series``), so a past date's page never sees later runs; then, per contract, the tables: the shifted
states (DV01 against CTD-based DV01), the key-rate changes behind chart 2, CTD probabilities from
both models, and the distance to each switch. Plain string formatting, no template engine
(decisions.md, Chart rendering).
"""

import base64
from datetime import date
from html import escape
from pathlib import Path

import numpy as np

from ctd.reference.grades import Grade, grade_for
from ctd.report import charts, results, series
from ctd.report.light import money, prob, traded
from ctd.report.names import bond_name
from ctd.risk.dv01 import dollars

MIN_SCHEMA = 8  # the profile (6), the repo record (7), the delivery window (8)
SHOWN = 5e-4  # bonds listed in the probability table: either model gives at least this


def _k(v) -> str:
    return f"{dollars(v) / 1000:,.1f}".replace("-", "−")


def _signed(v: float, fmt: str) -> str:
    return format(v, "+" + fmt).replace("-", "−")


def _table(header: list[str], rows: list[list[str]], caption: str = "", cls: str = "") -> str:
    head = "".join(f"<th>{h}</th>" for h in header)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    cap = f"<caption>{caption}</caption>" if caption else ""
    return f'<table class="{cls}">{cap}<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def _img(png: bytes, alt: str) -> str:
    return f'<img alt="{escape(alt)}" src="data:image/png;base64,{base64.b64encode(png).decode()}">'


def nearest(rec: dict) -> dict[str, dict | None]:
    """The first switch on each side, as ``LightResult.nearest`` (None if none in range)."""
    xs = rec["crossovers"]
    return {"rally": max((c for c in xs if c["z_bp"] < 0), key=lambda c: c["z_bp"], default=None),
            "selloff": min((c for c in xs if c["z_bp"] > 0), key=lambda c: c["z_bp"], default=None)}


def _distance(c: dict | None) -> str:
    if c is None:
        return "none in range"
    flag = ' <span class="flag">below 1σ</span>' if abs(c["sigmas"]) < 1 else ""
    return f"{_signed(c['z_bp'], '.1f')}bp ({abs(c['sigmas']):.2f}σ){flag}"


def _names(rec: dict) -> dict[str, str]:
    return {b["cusip"]: bond_name(b["coupon"], b["maturity"]) for b in rec["basket"]}


def _day(d: str) -> str:
    """``31 Dec 2026``."""
    x = date.fromisoformat(d)
    return f"{x.day} {x:%b %Y}"


def duration(dv01: float, f: float) -> float:
    """Futures modified duration in years: DV01 per 100 face over the futures price."""
    return dv01 / f * 1e4


def _dv01_duration(dv01: float, f: float) -> str:
    return f"{money(*[dollars(dv01)] * 2)} ({duration(dv01, f):.2f}y)"


def _term(months: int) -> str:
    """``6y 6m``, ``25y``."""
    y, m = divmod(months, 12)
    return f"{y}y" + (f" {m}m" if m else "")


def grade_text(g: Grade) -> str:
    """A deliverable-grade record in words, e.g. ``6y 6m to 8y remaining; original term at most 10y``."""
    if g.max_remaining_months is None:
        text = f"{_term(g.min_remaining_months)} and over remaining"
    else:
        text = (f"{_term(g.min_remaining_months)} to {'under ' if g.max_remaining_exclusive else ''}"
                f"{_term(g.max_remaining_months)} remaining")
        if g.max_remaining_from == "last":
            text += " (maximum from the last day of the delivery month)"
    if g.max_original_months is not None:
        text += f"; original term at most {_term(g.max_original_months)}"
    return text


def contracts_table(recs: list[dict]) -> str:
    """What each contract is: name and month, size, the grade in force for its month (reference data),
    its delivery days, basket and the options read for vol (the result)."""
    from ctd.data import refdata
    from ctd.reference.contracts import parse_contract

    products = {p["code"]: p for p in refdata.cme_products()["treasury"]}
    grades = refdata.grades()
    rows = []
    for r in recs:
        code, month = parse_contract(r["contract"], date.fromisoformat(r["asof"]))
        p, d = products[code], r["delivery"]
        rows.append([f"<b>{r['contract']}</b>", f"{p['name']} futures, {month:%B %Y}", f"${p['face']:,} face",
                     grade_text(grade_for(grades, code, month)), f"{_day(d['first'])} to {_day(d['last'])}",
                     f"{len(r['basket'])} issues",
                     f"{r['options']['label']}, expiry {_day(r['options']['expiry'])}"])
    return "<div class='scroll'>" + _table(["ticker", "contract", "size", "deliverable grade (from the first day of "
                                            "the delivery month)", "delivery days", "basket", "options for vol"],
                                           rows, cls="text") + "</div>"


def summary(recs: list[dict]) -> str:
    rows = []
    for r in recs:
        pts, names = r["profile"]["points"], _names(r)
        i = r["profile"]["points_sigma"].index(0)
        em = np.array(pts["effective_maturity"])[i]
        near = nearest(r)
        normal = pts["probs"].get(r["ctd"], [0.0] * len(pts["centres"]))[i]
        rows.append([f"<b>{r['contract']}</b>",
                     f"{names[r['ctd']]} (O {prob(*r['ctd_keeps'])}, N {normal:.1%})", _day(r["horizon"]),
                     f"{r['f_market']:.4f}", _dv01_duration(pts["dv01"][i], r["f_market"]),
                     _dv01_duration(pts["label_dv01"][i], r["f_market"]),
                     f"{em:.1f}y / {pts['label_effective_maturity'][i]:.1f}y",
                     f"{r['vol']['width']:.1f}bp", _distance(near["rally"]), _distance(near["selloff"])])
    table = _table(["contract", "CTD today, P(RCaD)<sup>1</sup>", "implied delivery<sup>2</sup>", "futures settle",
                    "DV01 per $100mm (duration)", "CTD-based DV01 (duration)",
                    "eff. maturity / CTD-based", "width (1σ)", "nearest switch, rally", "nearest switch, sell-off"],
                   rows, cls="summary")
    expiries = ", ".join(sorted({_day(r["options"]["expiry"]) for r in recs}))
    note = ("<p class='note'><sup>1</sup> P(RCaD): the probability that today's CTD remains CTD at the implied "
            f"delivery date. <b>O</b>: from the option digitals, which can only measure it at option expiry "
            f"({expiries}); <b>N</b>: the ATM normal factor to the implied delivery date, as in the charts.</p>"
            "<p class='note'><sup>2</sup> Implied delivery: the last delivery day if carry against term repo is "
            "positive, the first if negative.</p>"
            "<p class='note'>Duration: the DV01 over the futures settlement price, in years (the futures' modified "
            "duration).</p>")
    return f"<div class='scroll'>{table}</div>{note}"


def states_table(rec: dict) -> str:
    pts, names = rec["profile"]["points"], _names(rec)
    rows = [[charts.SIGMA[s], _signed(pts["centres"][j], ".1f") if s else "0", f"{pts['percentiles'][j]:.1%}",
             names[pts["label"][j]], _k(pts["dv01"][j]), _k(pts["label_dv01"][j]),
             _k(pts["label_dv01"][j] - pts["dv01"][j]), f"{pts['effective_maturity'][j]:.1f}y",
             f"{pts['label_effective_maturity'][j]:.1f}y"]
            for j, s in enumerate(rec["profile"]["points_sigma"])]
    return _table(["state", "shift bp", "percentile", "CTD at the shift", "DV01", "CTD-based DV01",
                   "CTD-based − DV01", "eff. maturity", "CTD-based eff. maturity"], rows,
                  "Probability-weighted against CTD-based DV01 at the shifted states ($k per bp per $100mm)")


def krd_table(rec: dict) -> str:
    pts, sig = rec["profile"]["points"], rec["profile"]["points_sigma"]
    i = sig.index(0)
    krd, label = np.array(pts["krd"]), np.array(pts["label_krd"])
    rows = [["today", *(_k(v) for v in krd[i]), _k(krd[i].sum())],
            ["today, CTD-based", *(_k(v) for v in label[i]), _k(label[i].sum())]]
    for s in (x for x in sig if x):
        j = sig.index(s)
        rows += [[charts.SIGMA[s], *(_k(v) for v in krd[j] - krd[i]), _k((krd[j] - krd[i]).sum())],
                 [f"{charts.SIGMA[s]}, CTD-based", *(_k(v) for v in label[j] - label[i]),
                  _k((label[j] - label[i]).sum())]]
    return _table(["", *(f"{n:g}y" for n in rec["krd"]["nodes"]), "total"], rows,
                  "Key-rate DV01 today, and its change from today at each state (chart 2; $k per bp per $100mm)")


def probability_table(rec: dict) -> str:
    pts = rec["profile"]["points"]
    i = rec["profile"]["points_sigma"].index(0)
    normal = {c: v[i] for c, v in pts["probs"].items()}
    rows = []
    for b in rec["basket"]:
        lo, hi = b["p_ctd"]
        n = normal.get(b["cusip"], 0.0)
        if max(hi, n) < SHOWN:
            continue
        rows.append([b["cusip"] + (" *" if b["cusip"] == rec["ctd"] else ""), bond_name(b["coupon"], b["maturity"]),
                     f"{b['cf']:.4f}", _k(b["dv01_cf"]), prob(lo, hi) if hi >= SHOWN else "", f"{n:.1%}"])
    return _table(["cusip", "bond", "CF", "DV01/CF $k", "option-implied", "normal (ATM)"], rows,
                  "CTD probabilities: option digitals at option expiry (the light model) against the ATM normal "
                  "factor to implied delivery, which drives the charts; * the CTD today. Both are read from CME "
                  "settlement prices, which CME sets from its implied-vol skew for the expiry whether or not a "
                  "strike traded, so they are option-implied rather than traded prices; see the switch table for "
                  "which strikes traded")


def switch_table(rec: dict) -> str:
    names = _names(rec)
    rows = []
    for c in rec["crossovers"]:
        d = c["digital"]
        digital = "–" if d["prob"] is None else ("≤ " if d["upper_bound"] else "") + f"{d['prob']:.1%}"
        flag = ' <span class="flag">below 1σ</span>' if abs(c["sigmas"]) < 1 else ""
        rows.append([f"{names[c['from']]} → {names[c['to']]}", _signed(c["z_bp"], ".1f"),
                     _signed(c["sigmas"], ".2f") + flag, f"{c['strike']:.4f}", _signed(c["strike"] - rec["f_market"], ".4f"),
                     ("P(F < K) " if d["side"] == "below" else "P(F > K) ") + digital,
                     "n/a" if "traded" not in d else traded(d["strikes_used"], d["traded"]), f"{c['normal']:.1%}"])
    if not rows:
        return "<p>No switches within the profile's range.</p>"
    return _table(["switch, as yields rise", "shift bp", "σ", "futures price K", "K − F", "digital",
                   "strikes traded", "normal tail"], rows,
                  "Distance to each switch: σ over the width to implied delivery; the digital and the normal tail are "
                  "both at option expiry. Strikes traded: which of the option strikes behind the digital traded that "
                  "day. A digital whose strikes didn't trade rests on CME's settlement skew, interpolated from other "
                  "strikes; treat it, and any digital beyond about 1.5σ, as indicative")


def diagnostics(rec: dict) -> str:
    repo = rec["repo"]
    if repo["path"] == "flat":
        rp = f"flat SOFR, {repo['term']:.3%} to implied delivery"
    else:
        months = ", ".join(f"{date.fromisoformat(m):%b} {v:.3%}" for m, v in repo["months"].items())
        rp = f"SR1 strip, {repo['term']:.3%} to implied delivery ({months}); SOFR {rec['sofr']:.3%} on {rec['sofr_date']}"
    v = rec["vol"]
    items = [
        f"Implied delivery {rec['horizon']}: {escape(rec['horizon_reason'])}",
        f"Repo: {rp}",
        f"Vol: {rec['options']['product']} {v['label']} options, expiry {rec['options']['expiry']}; "
        f"{v['price_vol']:.2f} points per √year at the money, {v['yield_vol']:.1f}bp per √year through the CTD's "
        f"DV01/CF; width {v['width']:.1f}bp to implied delivery, {v['expiry_width']:.1f}bp to option expiry"
        + ("" if "traded" not in v else f"; strikes {v['strikes'][0]:g} and {v['strikes'][1]:g}, traded that day: "
           f"{traded(v['strikes'], v['traded'])}"),
        f"Futures settlement {rec['f_market']:.4f}; recentring gap {_signed(rec['gap'], '.4f')} points",
        f"Key rates against the par curve of {rec['krd']['par_date']}",
        f"Run {rec['run_at']}, code {escape(str(rec['code']))}, {len(rec['inputs'])} raw files",
    ]
    items += [f'<span class="flag">warning</span> {escape(w)}' for w in rec["warnings"]]
    return "<ul class='diag'>" + "".join(f"<li>{x}</li>" for x in items) + "</ul>"


# Light model (phase 1c: β = 1, ATM vol). Swap out when the betas arrive in phase 2, where the factor
# becomes a reference yield rather than the CTD's (decisions.md, Probabilities in the published charts);
# so does charts.LIGHT_MODEL_SHIFT_AXIS.
LIGHT_MODEL_LEDE = (
    "Futures DV01 and key-rate DV01s per $100mm notional, probability-weighted over the deliverable basket with a "
    "normal distribution of the CTD's forward yield (at-the-money implied vol), against the CTD-based figures "
    "most systems report. Shifts move every basket forward yield in parallel; percentiles are of the move to the "
    "implied delivery date.")

CSS = """
:root { color-scheme: light; --surface: #fcfcfb; --plane: #f9f9f7; --ink: #0b0b0b; --ink2: #52514e;
  --muted: #898781; --grid: #e1e0d9; --flag: #d03b3b; }
body { margin: 0; background: var(--plane); color: var(--ink);
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1470px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 22px; margin: 0 0 4px; } h2 { font-size: 17px; margin: 32px 0 8px; }
h3 { font-size: 15px; margin: 24px 0 6px; }
p.lede, p.note { color: var(--ink2); max-width: 75ch; }
.grid { display: flex; flex-wrap: wrap; gap: 16px; }
figure { flex: 1 1 560px; min-width: 0; box-sizing: border-box; margin: 0; background: var(--surface);
  border: 1px solid var(--grid); border-radius: 6px; padding: 8px; }
figure img { width: 100%; height: auto; display: block; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; background: var(--surface); margin: 8px 0 16px; font-variant-numeric: tabular-nums; }
caption { text-align: left; color: var(--ink2); padding: 4px 0; caption-side: top; }
th, td { padding: 4px 10px; border-bottom: 1px solid var(--grid); text-align: right; white-space: nowrap; }
th { color: var(--ink2); font-weight: 600; white-space: normal; vertical-align: bottom; }
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
table.text th, table.text td { text-align: left; }
.flag { color: var(--flag); font-weight: 600; }
ul.diag { color: var(--ink2); padding-left: 20px; }
"""


def check_schema(recs: list[dict]) -> None:
    for r in recs:
        if r.get("schema", 0) < MIN_SCHEMA:
            raise ValueError(f"{r['contract']} {r['asof']}: results schema {r.get('schema')}, the report needs "
                             f"{MIN_SCHEMA} or later; re-run ctd run")


def through_time(history: dict[str, list[series.Row]]) -> list[str]:
    """Chart 3's section: contracts with at least two dates."""
    shown = {c: rows for c, rows in history.items() if len(rows) >= 2}
    if not shown:
        return []
    return [
        "<h2>DV01 through time</h2>",
        "<p class='note'><b>Top:</b> futures DV01 on each date with its −1σ and +1σ states, against the CTD-based DV01, "
        "which steps at each switch (circled; the interactive page names the CTD), and the DV01 of the first "
        "date's CTD held throughout. "
        "The gap between that constant-CTD line and the probability-weighted line is the part of the change "
        "caused by the basket. <b>Bottom:</b> effective maturity, where on the curve the DV01 sits (the key rates' "
        "maturities weighted by their DV01); with the CTD unchanged it still lengthens a little as yields rise. "
        "Guides mark basket changes.</p>",
        "<div class='grid'>" + "".join(f"<figure>{_img(charts.dv01_series_chart(c, rows), c + ' DV01 through time')}"
                                       "</figure>" for c, rows in shown.items()) + "</div>",
    ]


def render(asof: date, recs: list[dict], history: dict[str, list[series.Row]] | None = None) -> str:
    """The page for ``asof`` from that date's results, in contract order; ``history`` holds each
    contract's series up to ``asof`` for chart 3."""
    check_schema(recs)
    contracts = ", ".join(r["contract"] for r in recs)
    parts = [
        f"<h1>Treasury futures duration profile, {asof}</h1>",
        f"<p class='lede'>{contracts}. {LIGHT_MODEL_LEDE}</p>",
        contracts_table(recs),
        summary(recs),
        "<h2>DV01 profile</h2>",
        "<p class='note'><b>Top:</b> futures DV01 at each shift, with the vol ±10% band and the CTD-based staircase. "
        "<b>Bottom:</b> each key rate's share of that DV01. Key rates are measured against the Treasury par curve, so "
        "low-coupon bonds load more than 100% at their own maturity and negatively at shorter tenors.</p>",
        "<div class='grid'>" + "".join(f"<figure>{_img(charts.profile_chart(r), r['contract'] + ' DV01 profile')}"
                                       "</figure>" for r in recs) + "</div>",
        "<h2>Key-rate change at shifted states</h2>",
        "<p class='note'>Bars: the change in each key-rate DV01 from today at −2σ, −1σ, +1σ and +2σ. "
        "Markers: the same change for the CTD-based figures, which jump at each switch.</p>",
        "<div class='grid'>" + "".join(f"<figure>{_img(charts.krd_change_chart(r), r['contract'] + ' key-rate change')}"
                                       "</figure>" for r in recs) + "</div>",
        *through_time(history or {}),
    ]
    for r in recs:
        parts += [f"<h2>{r['contract']}</h2>",
                  *(f"<div class='scroll'>{t}</div>" for t in
                    (states_table(r), krd_table(r), probability_table(r), switch_table(r))),
                  "<h3>Inputs and diagnostics</h3>", diagnostics(r)]
    body = "\n".join(parts)
    return (f"<!doctype html>\n<html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>CTD report {asof}</title><style>{CSS}</style></head>\n<body><main>\n{body}\n</main></body></html>\n")


def contracts_on(root: Path, asof: date) -> list[str]:
    """Contracts with a saved light-model result for ``asof``, ZN before ZB as in cme_products.toml."""
    from ctd.data import refdata
    from ctd.reference.contracts import parse_contract

    order = [p["code"] for p in refdata.cme_products()["treasury"]]
    d = Path(root) / "results" / "light"
    found = [p.name for p in d.iterdir() if (p / f"{asof.isoformat()}.json").exists()] if d.is_dir() else []
    return sorted(found, key=lambda c: (order.index(parse_contract(c, asof)[0]), parse_contract(c, asof)[1]))


def write(root: Path, out_dir: Path, asof: date, contracts: list[str] | None = None) -> Path:
    """Write ``out_dir/<asof>.html`` from the results saved under ``root``."""
    import json

    contracts = contracts or contracts_on(root, asof)
    if not contracts:
        raise FileNotFoundError(f"no saved results for {asof}; run ctd run first")
    recs = []
    for c in contracts:
        path = results.light_path(root, c, asof)
        if not path.exists():
            raise FileNotFoundError(f"no saved result for {c} on {asof} ({path})")
        recs.append(json.loads(path.read_text(encoding="utf-8")))
    out = Path(out_dir) / f"{asof.isoformat()}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    history = {}
    for c in contracts:
        past = [r for r in results.read_light(root, c) if date.fromisoformat(r["asof"]) <= asof]
        check_schema(past)
        history[c] = series.series(past)
    out.write_text(render(asof, recs, history), encoding="utf-8")
    return out
