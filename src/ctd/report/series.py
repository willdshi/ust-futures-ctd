"""Chart 3's time series (outputs.md, Tier 1): one row per saved result of a contract (pure).

Read from the saved results (``results.read_light``), never from a model run. Per date: the model
DV01 at today and at the shifted states (``profile.points``), the CTD-based DV01, the option-implied
DV01 (the light model's cross-check), the constant-CTD DV01, effective maturity for all three,
and the event flags any step in the series should be attributed to.

The constant-CTD bond is the CTD on the series' first date (decisions.md, Which bond the
constant-CTD DV01 holds), so it moves when the series is extended back. A date whose basket no
longer holds it gets NaN. Effective maturity of a single bond is ``Σ share_k · T_k``: its shares
sum to 1.

Event flags so far: a CTD change and a basket change against the previous date. The contract
roll needs a series across contracts and comes with it.
"""

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from ctd.report.names import bond_name

CTD = "CTD change"
BASKET = "basket change"


@dataclass(frozen=True)
class Row:
    asof: date
    ctd: str
    ctd_name: str
    constant_name: str  # the constant-CTD bond
    dv01: float  # model DV01 today, per 100 face of futures
    states: dict[int, float]  # model DV01 at each shifted state, keyed by σ (−2 to +2)
    ctd_dv01: float  # CTD-based: the CTD at the forward
    option_dv01: tuple[float, float]  # option-implied (light model at z = 0), as a range
    constant_dv01: float  # the constant-CTD bond's DV01/CF; NaN once it leaves the basket
    em: float  # effective maturities in years: model, CTD-based, constant-CTD
    ctd_em: float
    constant_em: float
    p_ctd: float  # normal-factor probability that today's CTD is CTD at implied delivery
    nearest_sigmas: float  # distance to the nearest switch on either side, in σ; NaN if none in range
    events: tuple[str, ...] = field(default=())


def anchor_ctd(recs: list[dict]) -> tuple[str, str]:
    """The constant-CTD bond, CUSIP and name: the CTD on the first date."""
    first = recs[0]
    b = next(b for b in first["basket"] if b["cusip"] == first["ctd"])
    return b["cusip"], bond_name(b["coupon"], b["maturity"])


def _row(rec: dict, anchor: str, anchor_name: str, prev: dict | None) -> Row:
    pr = rec["profile"]
    pts, sig = pr["points"], pr["points_sigma"]
    i = sig.index(0)
    names = {b["cusip"]: bond_name(b["coupon"], b["maturity"]) for b in rec["basket"]}
    bond = next((b for b in rec["basket"] if b["cusip"] == anchor), None)
    if bond is None:
        constant_dv01 = constant_em = float("nan")
    else:
        constant_dv01 = bond["dv01_cf"]
        constant_em = float(np.dot(bond["krd_shares"], rec["krd"]["nodes"]))
    sigmas = [abs(c["sigmas"]) for c in rec["crossovers"]]
    events = []
    if prev is not None:
        if rec["ctd"] != prev["ctd"]:
            events.append(CTD)
        if {b["cusip"] for b in rec["basket"]} != {b["cusip"] for b in prev["basket"]}:
            events.append(BASKET)
    return Row(asof=date.fromisoformat(rec["asof"]), ctd=rec["ctd"], ctd_name=names[rec["ctd"]],
               constant_name=anchor_name, dv01=pts["dv01"][i],
               states={s: pts["dv01"][j] for j, s in enumerate(sig) if s},
               ctd_dv01=pts["label_dv01"][i], option_dv01=tuple(rec["dv01"]["weighted"]),
               constant_dv01=constant_dv01, em=pts["effective_maturity"][i],
               ctd_em=pts["label_effective_maturity"][i], constant_em=constant_em,
               p_ctd=pts["probs"].get(rec["ctd"], [0.0] * len(sig))[i],
               nearest_sigmas=min(sigmas, default=float("nan")), events=tuple(events))


def series(recs: list[dict], until: date | None = None) -> list[Row]:
    """The rows of one contract's results in date order, up to ``until`` if given."""
    recs = sorted((r for r in recs if until is None or date.fromisoformat(r["asof"]) <= until),
                  key=lambda r: r["asof"])
    if not recs:
        return []
    anchor, name = anchor_ctd(recs)
    return [_row(r, anchor, name, recs[k - 1] if k else None) for k, r in enumerate(recs)]
