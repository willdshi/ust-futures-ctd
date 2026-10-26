"""Charts 1 to 3 of the report (outputs.md Tier 1; phase 1c item 5), as PNG bytes.

Drawn from a saved result (``report.results``), so the same file always draws the same chart:
the PNGs carry no timestamp or version metadata. matplotlib's object API (no pyplot), so no
global figure state; style through ``rc_context``.

- Chart 1: region-weighted futures DV01 against the shift (vol ±10% band, the CTD-based staircase,
  the ±1σ and ±2σ states as points), percentiles of the move to implied delivery on the top axis; below
  on the same x-axis, a heatmap of each key-rate bucket's share of the DV01 (one row per bucket,
  positive shares in the blue ramp, negative ones in gray, on one scale for every contract).
- Chart 2: the change in each key-rate DV01 from today at −2σ, −1σ, +1σ and +2σ, with the
  CTD-based change as a marker on each bar.
- Chart 3: one contract's series (``report.series``) by trading day: the model DV01 with its ±1σ
  states, the CTD-based staircase (each switch named) and the constant-CTD DV01; below, effective
  maturity for the same three. A guide through both panels at each event-flagged date.
"""

import io

import matplotlib
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator, FuncFormatter
from scipy.special import ndtr, ndtri

from ctd.report.series import CTD, Row
from ctd.risk.dv01 import dollars

# reference palette (dataviz skill, light surface): chrome, slot-1 blue, blue ↔ red for rally ↔ sell-off.
# Chart 1's bucket shares are a heatmap, so the row names the bucket and color only has to carry the
# share: the sequential blue ramp up from the neutral gray for positive shares, gray down for negative
# ones (blue ↔ red would clash with chart 2's rally ↔ sell-off). Eight buckets as stacked bands needed
# eight distinguishable steps of one hue, more than the ramp holds (decisions.md, Chart rendering).
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
SERIES = "#2a78d6"
NEUTRAL = "#f0efec"
# % of DV01, the same scale for every contract. Shares run from about −25% (the short buckets of
# low-coupon bonds) to about 140% (UBZ6's 25y), so gray is full at −50% and blue at +100%; beyond
# either, the end color. Shared with the interactive page (report.interactive).
SHARE_STOPS = ((-50, INK2), (0, NEUTRAL), (20, "#cde2fb"), (40, "#86b6ef"), (60, "#3987e5"), (80, "#1c5cab"),
               (100, "#0d366b"))
SHARE_NORM = TwoSlopeNorm(vcenter=0, vmin=SHARE_STOPS[0][0], vmax=SHARE_STOPS[-1][0])
SHARE_CMAP = LinearSegmentedColormap.from_list("share", [(float(SHARE_NORM(v)), c) for v, c in SHARE_STOPS])
STATES = {-2: "#1c5cab", -1: "#86b6ef", 1: "#f0a09f", 2: "#e34948"}
SIGMA = {-2: "−2σ", -1: "−1σ", 0: "today", 1: "+1σ", 2: "+2σ"}

STYLE = {
    "font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 9, "text.color": INK,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "axes.facecolor": SURFACE, "axes.grid": True,
    "axes.axisbelow": True, "axes.spines.top": False, "axes.spines.right": False,
    "grid.color": GRID, "grid.linewidth": 0.6, "xtick.color": MUTED, "ytick.color": MUTED,
    "xtick.labelcolor": INK2, "ytick.labelcolor": INK2, "figure.facecolor": SURFACE,
    "legend.frameon": False, "legend.fontsize": 8, "axes.unicode_minus": True,
    "text.parse_math": False,  # the "$" in "$k" is a dollar
}
DPI = 144
PERCENTILES = (1, 5, 10, 25, 50, 75, 90, 95, 99)
# Light model (phase 1c, β = 1): becomes the reference yield ("20y yield change (bp)") when the betas arrive
# in phase 2 (decisions.md, Probabilities in the published charts); so does page.LIGHT_MODEL_LEDE.
LIGHT_MODEL_SHIFT_AXIS = "parallel shift in basket forward yields (bp)"
EMPTY_BUCKET = 0.005  # chart 2 leaves out end buckets below this share of today's DV01 in every state


def _k(v) -> np.ndarray:
    """DV01s per 100 face of futures as $k per $100mm."""
    return dollars(np.asarray(v, dtype=float)) / 1000


def _png(fig: Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, metadata={"Software": None})
    return buf.getvalue()


def _bp(v, _=None) -> str:
    return f"{v:+.0f}".replace("-", "−") if v else "0"


def _percentile_axis(ax, width: float, horizon: str) -> None:
    def to_pct(x):
        return 100 * ndtr(np.asarray(x, dtype=float) / width)

    def to_bp(p):
        return width * ndtri(np.clip(np.asarray(p, dtype=float), 1e-9, 100 - 1e-9) / 100)

    top = ax.secondary_xaxis("top", functions=(to_pct, to_bp))
    top.xaxis.set_major_locator(FixedLocator(PERCENTILES))
    top.xaxis.set_major_formatter(FuncFormatter(lambda p, _: f"{p:g}"))
    top.set_xlabel(f"percentile of the move to implied delivery ({horizon})", color=INK2)
    top.spines["top"].set_color(AXIS)


def profile_chart(rec: dict) -> bytes:
    """Chart 1 for one result."""
    pr = rec["profile"]
    curve, pts, width = pr["curve"], pr["points"], pr["width"]
    x = np.array(curve["centres"])
    with matplotlib.rc_context(STYLE):
        fig = Figure(figsize=(6.6, 6.4), layout="constrained")
        top, bottom = fig.subplots(2, 1, sharex=True, height_ratios=(3, 2))

        top.fill_between(x, _k(pr["band_dv01"]["vol_down"]), _k(pr["band_dv01"]["vol_up"]), color=SERIES,
                         alpha=0.14, linewidth=0, label="vol ±10%")
        top.plot(x, _k(curve["label_dv01"]), color=MUTED, linewidth=1, drawstyle="steps-mid",
                 label="CTD-based")
        top.plot(x, _k(curve["dv01"]), color=SERIES, linewidth=2, label="probability-weighted")
        px, py = np.array(pts["centres"]), _k(pts["dv01"])
        top.scatter(px, py, s=40, color=SERIES, edgecolor=SURFACE, linewidth=1.5, zorder=3)
        lo, hi = top.get_ylim()
        top.set_ylim(lo - 0.08 * (hi - lo), hi + 0.08 * (hi - lo))  # room for the state labels and the legend
        for s, cx in zip(pr["points_sigma"], px):  # a guide through both panels at each state, named below
            for ax in (top, bottom):
                ax.axvline(cx, color=AXIS, linewidth=0.8, zorder=1.5)
            top.annotate(SIGMA[s], (cx, 0), xycoords=("data", "axes fraction"), xytext=(0, 4),
                         textcoords="offset points", ha="center", va="bottom", fontsize=7.5, color=INK2)
        top.set_ylabel("futures DV01 ($k per bp per $100mm)")
        top.legend(loc="upper left", ncol=3)
        _percentile_axis(top, width, rec["horizon"])
        top.set_title(f"{rec['contract']} DV01 profile, {rec['asof']}", loc="left", fontsize=10.5,
                      color=INK, pad=8)

        dv01 = np.array(curve["dv01"])
        shares = 100 * np.array(curve["krd"]) / dv01[:, None]
        keep = share_rows(shares)
        nodes = rec["krd"]["nodes"][keep]
        xe = np.r_[x[0], (x[1:] + x[:-1]) / 2, x[-1]]  # cell edges around each centre
        mesh = bottom.pcolormesh(xe, np.arange(len(nodes) + 1) - 0.5, shares[:, keep].T, cmap=SHARE_CMAP,
                                 norm=SHARE_NORM, shading="flat")
        bottom.grid(False)
        for y in np.arange(1, len(nodes)) - 0.5:  # a surface gap between rows
            bottom.axhline(y, color=SURFACE, linewidth=1)
        bottom.set_yticks(np.arange(len(nodes)), [f"{n:g}y" for n in nodes])
        bottom.tick_params(axis="y", length=0)
        bottom.set_ylabel("key rate")
        bottom.set_xlabel(LIGHT_MODEL_SHIFT_AXIS)
        bottom.set_xlim(x[0], x[-1])
        bottom.xaxis.set_major_formatter(FuncFormatter(_bp))
        bar = fig.colorbar(mesh, ax=[top, bottom], location="right", shrink=0.38, anchor=(0.0, 0.0), aspect=14,
                           extend="both")
        bar.set_label("share of DV01 (%)", color=INK2)
        bar.outline.set_visible(False)
        bar.set_ticks([-50, -25, 0, 50, 100])
        bar.ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:+.0f}".replace("-", "−") if v else "0"))
        return _png(fig)


def share_rows(shares: np.ndarray) -> slice:
    """The key-rate buckets chart 1 shows: all but the end ones the contract never loads on at any
    shift (under ``EMPTY_BUCKET`` of the DV01, as in chart 2), so ZN's chart has no 15y to 30y rows."""
    used = np.flatnonzero(np.abs(shares).max(axis=0) >= 100 * EMPTY_BUCKET)
    return slice(int(used.min()), int(used.max()) + 1)


def used_buckets(pts: dict, today: int) -> slice:
    """The key-rate buckets chart 2 shows: all but the end ones the contract never loads on (ZN's
    15y to 30y), under ``EMPTY_BUCKET`` of today's DV01 in every state, model and CTD-based."""
    k = np.abs(np.r_[np.array(pts["krd"]), np.array(pts["label_krd"])]).max(axis=0)
    used = np.flatnonzero(k >= EMPTY_BUCKET * abs(pts["dv01"][today]))
    return slice(int(used.min()), int(used.max()) + 1)


def krd_change_chart(rec: dict) -> bytes:
    """Chart 2 for one result: the change in each key-rate DV01 from today at the shifted states."""
    pts = rec["profile"]["points"]
    sig = rec["profile"]["points_sigma"]
    today = sig.index(0)
    keep = used_buckets(pts, today)
    krd, label = np.array(pts["krd"])[:, keep], np.array(pts["label_krd"])[:, keep]
    nodes = rec["krd"]["nodes"][keep]
    states = [s for s in sig if s]
    w = 0.8 / len(states)
    with matplotlib.rc_context(STYLE):
        fig = Figure(figsize=(6.6, 3.9), layout="constrained")
        ax = fig.subplots()
        ax.grid(axis="x", visible=False)
        ix = np.arange(len(nodes))
        for k, s in enumerate(states):
            j = sig.index(s)
            off = ix + (k - (len(states) - 1) / 2) * w
            ax.bar(off, _k(krd[j] - krd[today]), width=w * 0.85, color=STATES[s],
                   label=f"{SIGMA[s]} ({_bp(pts['centres'][j])}bp)")
            ax.scatter(off, _k(label[j] - label[today]), marker="_", s=70, linewidth=1.4, color=INK2, zorder=3)
        ax.axhline(0, color=AXIS, linewidth=0.8)
        ax.set_xticks(ix, [f"{n:g}y" for n in nodes])
        ax.set_xlabel("key rate")
        ax.set_ylabel("change from today ($k per bp per $100mm)")
        handles, names = ax.get_legend_handles_labels()
        handles.append(Line2D([], [], marker="_", linestyle="none", markersize=9, markeredgewidth=1.4, color=INK2))
        names.append("CTD-based change")
        ax.legend(handles, names, loc="upper left", ncol=3)
        lo, hi = ax.get_ylim()
        ax.set_ylim(lo, hi + 0.2 * (hi - lo))  # room for the legend
        ax.set_title(f"{rec['contract']} key-rate DV01 change at shifted states, {rec['asof']}", loc="left",
                     fontsize=10.5, color=INK, pad=8)
        return _png(fig)


def _day_ticks(ax, days: list) -> None:
    """Trading days at even spacing, named ``16 Oct``; at most about ten names."""
    step = max(1, -(-len(days) // 10))
    ix = range(0, len(days), step)
    ax.set_xticks(list(ix), [f"{days[i].day} {days[i]:%b}" for i in ix])
    ax.set_xlim(-0.5, len(days) - 0.5)


def dv01_series_chart(contract: str, rows: list[Row]) -> bytes:
    """Chart 3 for one contract: DV01 and effective maturity by date."""
    x = np.arange(len(rows))
    days = [r.asof for r in rows]
    marker = {"marker": "o", "markersize": 3.5} if len(rows) <= 60 else {}
    with matplotlib.rc_context(STYLE):
        fig = Figure(figsize=(6.6, 5.6), layout="constrained")
        top, bottom = fig.subplots(2, 1, sharex=True, height_ratios=(3, 2))

        for s, m in ((1, "^"), (-1, "v")):  # one colour, told apart by the marker: up for +1σ, down for −1σ
            top.plot(x, _k([r.states[s] for r in rows]), color=STATES[-1], linewidth=1, marker=m, markersize=4,
                     label=SIGMA[s])
        top.plot(x, _k([r.ctd_dv01 for r in rows]), color=MUTED, linewidth=1, drawstyle="steps-mid",
                 label="CTD-based")
        top.plot(x, _k([r.constant_dv01 for r in rows]), color=INK2, linewidth=1, linestyle=(0, (4, 2)),
                 label=f"constant CTD ({rows[0].constant_name})")
        top.plot(x, _k([r.dv01 for r in rows]), color=SERIES, linewidth=2, label="probability-weighted", **marker)
        for i, r in enumerate(rows):
            if r.events:
                for ax in (top, bottom):
                    ax.axvline(i, color=AXIS, linewidth=0.8, zorder=1.5)
            if CTD in r.events:  # name the new CTD where the staircase steps
                top.annotate(r.ctd_name, (i, float(_k(r.ctd_dv01))), xytext=(-3, 4), textcoords="offset points",
                             ha="right", fontsize=7, color=INK2)
            other = [e for e in r.events if e != CTD]
            if other:
                top.annotate(", ".join(other), (i, 1), xycoords=("data", "axes fraction"), xytext=(3, -2),
                             textcoords="offset points", va="top", fontsize=7, color=INK2)
        lo, hi = top.get_ylim()
        top.set_ylim(lo - 0.06 * (hi - lo), hi + 0.06 * (hi - lo))
        top.set_ylabel("futures DV01 ($k per bp per $100mm)")
        top.set_title(f"{contract} DV01 through time, {days[0]} to {days[-1]}", loc="left", fontsize=10.5,
                      color=INK, pad=8)

        bottom.plot(x, [r.ctd_em for r in rows], color=MUTED, linewidth=1, drawstyle="steps-mid")
        bottom.plot(x, [r.constant_em for r in rows], color=INK2, linewidth=1, linestyle=(0, (4, 2)))
        bottom.plot(x, [r.em for r in rows], color=SERIES, linewidth=2, **marker)
        bottom.set_ylabel("effective maturity (years)")
        _day_ticks(bottom, days)

        handles, names = top.get_legend_handles_labels()
        order = [4, 0, 1, 2, 3]  # probability-weighted first, then +1σ, −1σ, CTD-based, constant
        fig.legend([handles[i] for i in order], [names[i] for i in order], loc="outside lower center", ncol=3)
        return _png(fig)
