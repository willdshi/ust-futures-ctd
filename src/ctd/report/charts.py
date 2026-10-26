"""Charts 1 and 2 of the single-date report (outputs.md Tier 1; phase 1c item 5), as PNG bytes.

Drawn from a saved result (``report.results``), so the same file always draws the same chart:
the PNGs carry no timestamp or version metadata. matplotlib's object API (no pyplot), so no
global figure state; style through ``rc_context``.

- Chart 1: region-weighted futures DV01 against the shift (vol ±10% band, the CTD-based staircase,
  the ±1σ and ±2σ states as points), percentiles of the move to implied delivery on the top axis; below
  on the same x-axis, each key-rate bucket's share of the DV01, positives stacked up and negatives
  down.
- Chart 2: the change in each key-rate DV01 from today at −2σ, −1σ, +1σ and +2σ, with the
  CTD-based change as a marker on each bar.
"""

import io

import matplotlib
import numpy as np
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator, FuncFormatter
from scipy.special import ndtr, ndtri

from ctd.risk.dv01 import dollars

# reference palette (dataviz skill, light surface): chrome, slot-1 blue, the blue ordinal ramp from
# step 250 for the eight buckets (short tenors light, long dark), blue ↔ red for rally ↔ sell-off
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
SERIES = "#2a78d6"
BUCKETS = ("#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#104281")
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
        nodes = rec["krd"]["nodes"]
        labels = [f"{n:g}y" for n in nodes]
        up = bottom.stackplot(x, np.clip(shares, 0, None).T, colors=BUCKETS, edgecolor=SURFACE, linewidth=0.5,
                              labels=labels)
        bottom.stackplot(x, np.clip(shares, None, 0).T, colors=BUCKETS, edgecolor=SURFACE, linewidth=0.5)
        bottom.axhline(0, color=AXIS, linewidth=0.8)
        _label_bands(bottom, x, np.clip(shares, 0, None), labels)
        bottom.set_ylabel("share of DV01 by key rate (%)")
        bottom.set_xlabel(LIGHT_MODEL_SHIFT_AXIS)
        bottom.set_xlim(x[0], x[-1])
        bottom.xaxis.set_major_formatter(FuncFormatter(_bp))
        bottom.legend(up[::-1], labels[::-1], loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=7.5,
                      handlelength=1.0)
        return _png(fig)


def _label_bands(ax, x: np.ndarray, pos: np.ndarray, labels: list[str]) -> None:
    """Name each positive band where it is thickest, if it is thick enough to hold the label."""
    base = np.cumsum(pos, axis=1) - pos
    for i, label in enumerate(labels):
        j = int(pos[:, i].argmax())
        if pos[j, i] < 9:
            continue
        j = min(max(j, 8), len(x) - 9)  # keep the label off the edges
        ax.text(x[j], base[j, i] + pos[j, i] / 2, label, ha="center", va="center", fontsize=7.5,
                color=INK if i < 3 else SURFACE)


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
