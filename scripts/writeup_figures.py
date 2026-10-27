"""Render the figures in docs/writeup.md from saved light-model results (``data/results/light``).

- ``zbz6-envelope-<asof>.png``: each bond that is CTD somewhere within ±100bp, its converted forward
  price in 32nds above the cheapest bond, against a parallel shift in forward yields. The CTD sits on
  the zero line; a switch point is where another bond comes down to meet it. Labels name the CTD in
  each region wider than 6bp; the shaded band is ±1σ of the move to the horizon. Not a report chart.
- ``<contract>-dv01-profile-<asof>.png`` (ZBZ6, ZNZ6, TNZ6) and ``zbz6-krd-change-<asof>.png``: the
  report's charts 1 and 2 (``ctd.report.charts``), unchanged.

Run ``ctd run`` for each contract and date first. Then rebuild the PDF:

    python scripts/writeup_figures.py                  # 2026-10-23, the write-up's date
    python scripts/writeup_figures.py --asof 2026-10-23 --data data --out docs/images
    pandoc docs/writeup.md -o docs/writeup.pdf --pdf-engine=xelatex --resource-path=docs
"""

import argparse
import json
from datetime import date
from io import BytesIO
from pathlib import Path

import matplotlib
import numpy as np
from matplotlib.figure import Figure

from ctd.model.envelope import BasketBond, converted
from ctd.report.charts import AXIS, DPI, GRID, INK2, MUTED, SERIES, STYLE, krd_change_chart, profile_chart
from ctd.report.names import bond_name
from ctd.report.results import light_path

PROFILES = ("ZBZ6", "ZNZ6", "TNZ6")
SHIFT_BP = 100
MIN_LABEL_BP = 6  # regions narrower than this go unlabelled
Y_MAX_32NDS = 16


def envelope_chart(rec: dict) -> bytes:
    horizon = date.fromisoformat(rec["horizon"])
    bonds = [BasketBond(b["cusip"], b["coupon"], date.fromisoformat(b["maturity"]), b["cf"], b["fwd_yield"])
             for b in rec["basket"]]
    z = np.arange(-SHIFT_BP, SHIFT_BP + 0.25, 0.25)
    c = converted(bonds, horizon, z)
    rel = (c - c.min(axis=0)) * 32
    stair = []  # the CTDs in shift order
    for i in c.argmin(axis=0):
        if not stair or stair[-1] != i:
            stair.append(int(i))
    env = c.min(axis=0)
    sw = [s["z_bp"] for s in rec["crossovers"] if -SHIFT_BP <= s["z_bp"] <= SHIFT_BP]
    width = rec["vol"]["width"]
    with matplotlib.rc_context(STYLE):
        fig = Figure(figsize=(6.6, 8.0), layout="constrained")
        top, ax = fig.subplots(2, 1, sharex=True)
        # the textbook picture: converted prices in points, the futures price their lower envelope
        for i in stair:
            top.plot(z, c[i], color=MUTED, lw=1.1, zorder=2)
        top.plot(z, env, color=SERIES, lw=2.2, zorder=3, label="envelope (futures price): the cheapest bond")
        for s in sw:
            top.axvline(s, color=AXIS, lw=0.6, ls=(0, (2, 2)), zorder=0)
        top.axvline(0, color=MUTED, lw=0.8, zorder=0)
        top.plot([], [], color=MUTED, lw=1.1, label="converted forward price of each bond")
        top.legend(loc="upper right")
        top.set_ylim(env.min() - 1, env.max() + 1)
        top.set_ylabel("converted forward price (points)")
        top.set_title(f"{rec['contract']} converted forward prices and their envelope, {rec['asof']}",
                      loc="left", fontsize=10)
        ax.axvspan(-width, width, color=GRID, alpha=0.45, lw=0, zorder=0)
        ax.annotate("−1σ", (-width + 1.5, Y_MAX_32NDS - 0.4), ha="left", va="top", fontsize=7.5, color=MUTED)
        ax.annotate("+1σ", (width - 1.5, Y_MAX_32NDS - 0.4), ha="right", va="top", fontsize=7.5, color=MUTED)
        for i in stair:
            ax.plot(z, rel[i], color=MUTED, lw=1.1, zorder=2)
        ax.axhline(0, color=SERIES, lw=2.2, zorder=3)
        ax.annotate("envelope: the cheapest bond", (SHIFT_BP - 1.5, 0), xytext=(0, -4), textcoords="offset points",
                    ha="right", va="top", fontsize=7.5, color=INK2)
        for s in sw:
            ax.axvline(s, color=AXIS, lw=0.6, ls=(0, (2, 2)), zorder=0)
        ax.axvline(0, color=MUTED, lw=0.8, zorder=0)
        edges = [-SHIFT_BP, *sw, SHIFT_BP]
        for k, i in enumerate(stair):
            if edges[k + 1] - edges[k] < MIN_LABEL_BP:
                continue
            b = bonds[i]
            ax.annotate(bond_name(b.coupon, b.maturity.isoformat()), ((edges[k] + edges[k + 1]) / 2, 0),
                        xytext=(0, 6), textcoords="offset points", rotation=90, ha="center", va="bottom",
                        fontsize=7.5, color=INK2)
        ax.set_ylim(-1.6, Y_MAX_32NDS)
        ax.set_xlim(-SHIFT_BP, SHIFT_BP)
        ax.set_xlabel("parallel shift in basket forward yields (bp)")
        ax.set_ylabel("converted forward price above the cheapest (32nds)")
        ax.set_title("the same prices relative to the cheapest", loc="left", fontsize=10)
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=DPI, metadata={"Software": None})
        return buf.getvalue()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--asof", type=date.fromisoformat, default=date(2026, 10, 23))
    p.add_argument("--data", type=Path, default=Path("data"))
    p.add_argument("--out", type=Path, default=Path("docs/images"))
    a = p.parse_args()
    recs = {c: json.loads(light_path(a.data, c, a.asof).read_text()) for c in PROFILES}
    out = {"zbz6-envelope": envelope_chart(recs["ZBZ6"]), "zbz6-krd-change": krd_change_chart(recs["ZBZ6"])}
    out |= {f"{c.lower()}-dv01-profile": profile_chart(recs[c]) for c in PROFILES}
    for name, png in out.items():
        path = a.out / f"{name}-{a.asof.isoformat()}.png"
        path.write_bytes(png)
        print(path)


if __name__ == "__main__":
    main()
