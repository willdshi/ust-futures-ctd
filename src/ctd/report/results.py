"""Saved model results: one JSON file per contract and as-of date (design 10, phase 1b D).

    data/results/light/ZBZ6/2026-10-21.json

A result is derived from the raw store, so re-running a date overwrites it; it records the raw
files it was read from (with their sha256) and the code version, so two runs can be told apart.
A series is the files of one contract read in date order (``read_light``).
"""

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

from ctd.curve.par import NODES
from ctd.model.light import LightResult

SCHEMA = 9  # 2: futures DV01; 3: key-rate DV01s; 4: clusters; 5: ATM vol and distance to switch; 6: profile;
# 7: repo from the SR1 strip; 8: the delivery window and the carry behind the horizon; 9: inputs read
# through a derived table are its raw files, each marked with the ``table``


def light_path(root: Path, contract: str, asof: date) -> Path:
    return Path(root) / "results" / "light" / contract / f"{asof.isoformat()}.json"


def _states(s) -> dict:
    return {"centres": s.centres.tolist(), "percentiles": s.percentiles.tolist(),
            "probs": {c: v.tolist() for c, v in s.probs.items() if v.max() >= 1e-4},
            "dv01": s.dv01.tolist(), "krd": s.krd.tolist(), "effective_maturity": s.effective_maturity.tolist(),
            "label": list(s.label), "label_dv01": s.label_dv01.tolist(), "label_krd": s.label_krd.tolist(),
            "label_effective_maturity": s.label_effective_maturity.tolist()}


def light_record(r: LightResult, inputs: list[dict], code: str | None) -> dict:
    """The saved form of a light-model run; ``inputs`` lists the raw files read (source, unit, name, sha256)."""
    p = r.probabilities
    by_bond = p.by_bond()
    region = {id(reg.switch): reg for reg in p.regions if reg.switch is not None}
    [kept] = [reg for reg in p.regions if reg.side == "ctd"]
    return {
        "model": "light", "schema": SCHEMA, "contract": r.contract, "asof": r.asof.isoformat(),
        "settle": r.settle.isoformat(), "horizon": r.horizon.isoformat(), "horizon_reason": r.horizon_reason,
        "delivery": {"first": r.delivery.first.isoformat(), "last": r.delivery.last.isoformat(),
                     "ctd": r.delivery.ctd, "fwd_first": r.delivery.fwd_first, "fwd_last": r.delivery.fwd_last,
                     "units": "forward clean prices of the cheapest bond at the last delivery day, per 100 face"},
        "sofr": r.sofr, "sofr_date": r.sofr_date.isoformat(),
        "repo": {"path": r.repo.path, "term": r.repo.term,
                 "months": {m.isoformat(): v for m, v in r.repo.months.items()}, "why_flat": r.repo.why_flat,
                 "units": "decimals; term actual/360 simple from settlement to the horizon; months are the "
                          "strip's overnight rate on each month's unknown days"},
        "f_market": r.f_market, "e0": r.e0, "gap": r.gap,
        "options": {"product": r.expiry.product, "label": r.expiry.label, "expiry": r.expiry.expiry.isoformat(),
                    "df": r.df},
        "ctd": p.ctd, "ctd_keeps": [kept.lo, kept.hi],
        "dv01": {"weighted": list(r.dv01), "ctd_label": r.ctd_dv01, "face": r.face,
                 "units": "price points per bp per 100 face of futures; x 1e6 for $ per $100mm"},
        "krd": {"nodes": list(NODES), "weighted": r.krd.tolist(), "ctd_label": r.ctd_krd.tolist(),
                "effective_maturity": r.effective_maturity, "ctd_effective_maturity": r.ctd_effective_maturity,
                "par_date": r.par_date.isoformat(), "units": "as dv01"},
        "clusters": [{"node": cl.node, "members": list(cl.members), "prob": list(cl.prob), "krd": cl.krd.tolist()}
                     for cl in r.clusters],
        "vol": {"label": r.vol.label, "t_expiry": r.vol.t, "t_horizon": r.t_horizon,
                "strikes": list(r.vol.strikes), "vols": list(r.vol.vols), "price_vol": r.vol.price_vol,
                "yield_vol": r.yield_vol, "width": r.width, "expiry_width": r.expiry_width,
                "flags": list(r.vol.flags),
                "units": "price vols in points per √year, yield vol in bp per √year, widths in bp; "
                         "t in calendar days / 365"},
        "profile": {"width": r.profile.curve.width, "points_sigma": list(r.profile.POINTS),
                    "points": _states(r.profile.points), "curve": _states(r.profile.curve),
                    "band_dv01": {"vol_down": r.profile.band_dv01[0].tolist(),
                                  "vol_up": r.profile.band_dv01[1].tolist()},
                    "units": "shifts in bp of every forward yield (β = 1); DV01 and KRDs as dv01; probs of bonds "
                             "reaching 1e-4; bands at width × 0.9 and × 1.1 on the curve's centres"},
        "basket": [{"cusip": b.cusip, "coupon": b.coupon, "maturity": b.maturity.isoformat(), "cf": b.cf,
                    "price": b.price, "price_from": b.price_from, "fwd": b.fwd, "fwd_yield": b.fwd_yield,
                    "carry": b.carry, "converted": b.converted, "dv01_cf": b.dv01_cf,
                    "krd_shares": list(b.krd_shares),
                    "p_ctd": list(by_bond.get(b.cusip, (0.0, 0.0)))}
                   for b in r.basket],
        "crossovers": [{"z_bp": c.switch.z_bp, "from": c.switch.from_cusip, "to": c.switch.to_cusip,
                        "envelope": c.switch.envelope, "strike": c.strike, "side": region[id(c.switch)].side,
                        "sigmas": c.sigmas, "normal": c.normal,
                        "digital": {"side": c.digital.side, "prob": c.digital.prob,
                                    "upper_bound": c.digital.upper_bound,
                                    "strikes_used": list(c.digital.strikes_used), "flags": list(c.digital.flags)},
                        "beyond": {"cusip": region[id(c.switch)].cusip, "lo": region[id(c.switch)].lo,
                                   "hi": region[id(c.switch)].hi}}
                       for c in r.crossovers],
        "warnings": list(r.warnings),
        "inputs": inputs,
        "code": code,
        "run_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def write_light(root: Path, record: dict) -> Path:
    """Write (or overwrite) ``record``'s file, atomically."""
    path = light_path(root, record["contract"], date.fromisoformat(record["asof"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def read_light(root: Path, contract: str) -> list[dict]:
    """Every saved light-model result for ``contract``, in date order."""
    d = Path(root) / "results" / "light" / contract
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))] if d.is_dir() else []
