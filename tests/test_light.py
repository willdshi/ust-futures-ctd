"""The light model end to end on a synthetic basket and option chain (design 5.11)."""

import math
from dataclasses import replace
from datetime import date

import pytest

from ctd.bonds.conversionfactor import conversion_factor
from ctd.bonds.pricing import clean_price
from ctd.curve.par import ParCurve
from ctd.data import refdata
from ctd.data.cme_bulletin import OptionSettle
from ctd.data.td_prices import BondPrice
from ctd.model.light import LightInputs, run
from ctd.reference.options import OptionExpiry
from ctd.report.light import format_run, prob

ASOF, SETTLE = date(2026, 10, 21), date(2026, 10, 22)
F, SIGMA, DF = 105.0, 4.0, 0.997
TERMS = {"A": (0.03125, date(2042, 2, 15)), "B": (0.045, date(2044, 2, 15)), "C": (0.0475, date(2045, 5, 15)),
         "D": (0.02, date(2050, 2, 15))}


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def normal_chain():
    rows = []
    for k in range(85, 126):
        d = (k - F) / SIGMA
        put = DF * ((k - F) * phi(d) + SIGMA * math.exp(-d * d / 2) / math.sqrt(2 * math.pi))
        rows += [OptionSettle("ZB", "DEC26", "P", float(k), put, None, 0, 100),
                 OptionSettle("ZB", "DEC26", "C", float(k), put + DF * (F - k), None, 0, 100)]
    return rows


def inputs(**kw):
    # a flat 5.5% curve below the CF formula's 6%: the short bond is CTD, longer ones take over in a sell-off
    month = date(2026, 12, 1)
    prices = {c: BondPrice(c, cpn, m, clean_price(cpn, m, SETTLE, 0.055), "eod") for c, (cpn, m) in TERMS.items()}
    x = LightInputs("ZBZ6", ASOF, SETTLE, date(2026, 12, 1), date(2026, 12, 31),
                    {c: conversion_factor(cpn, m, month, 3) for c, (cpn, m) in TERMS.items()}, prices, F, 0.0388,
                    date(2026, 10, 20), OptionExpiry("ZB", "DEC26", date(2026, 11, 20), "ZBZ6", True),
                    normal_chain(), refdata.calendar("sifma"), 100_000, ParCurve((0.5, 30.0), (0.055, 0.055)),
                    date(2026, 10, 21))
    return replace(x, **kw)


def test_run_on_a_synthetic_basket():
    r = run(inputs())
    assert r.horizon == date(2026, 12, 31)  # 5.5% yields over 3.88% SOFR: positive carry
    assert [b.cusip for b in r.basket] == ["A", "B", "C", "D"]  # by maturity
    assert r.crossovers, "a sell-off makes the longer bonds cheapest"
    for c in r.crossovers:
        assert c.strike == pytest.approx(F + c.switch.envelope - r.e0)
        assert c.digital.prob is not None
    p = r.probabilities
    assert p.ctd == min(r.basket, key=lambda b: b.converted).cusip
    lo, hi = (sum(v[i] for v in p.by_bond().values()) for i in (0, 1))
    assert lo - 1e-9 <= 1 <= hi + 1e-9
    assert r.gap == pytest.approx(F - r.e0)
    assert r.df == pytest.approx(1 / (1 + 0.0388 / 360) ** 29, rel=1e-4)  # 22 Oct → 20 Nov

    out = format_run(r)
    assert "Basket" in out and "Crossovers" in out and f"{p.ctd} *" in out
    assert f"{p.ctd} (CTD) keeps" in out


def test_missing_price_and_provisional_prices_are_warned():
    x = inputs()
    prices = {c: (replace(p, price_from="mid") if c == "B" else p) for c, p in x.prices.items() if c != "D"}
    r = run(replace(x, prices=prices))
    assert [b.cusip for b in r.basket] == ["A", "B", "C"]
    assert any("no TreasuryDirect price for D" in w for w in r.warnings)
    assert any("provisional prices (no end of day) for B" in w for w in r.warnings)


def test_stops_at_option_expiry():
    with pytest.raises(ValueError, match="options expired"):
        run(inputs(asof=date(2026, 11, 20)))


def test_probability_formatting():
    assert prob(0.194, 0.194) == "19.4%"
    assert prob(0.0, 0.031) == "≤ 3.1%"
    assert prob(0.088, 0.104) == "8.8–10.4%"


def test_basket_table_lists_the_contenders_unless_asked_for_all(monkeypatch):
    from ctd.report import light as report

    monkeypatch.setattr(report, "NEXT_CHEAPEST", 0)
    r = run(inputs())
    short, full = format_run(r), format_run(r, all_bonds=True)
    listed = lambda out: {c for c in TERMS if f"\n{c} " in out}  # noqa: E731
    assert listed(full) == set(TERMS)
    contenders = set(r.probabilities.by_bond())
    assert listed(short) == contenders != set(TERMS)
    assert f"{len(TERMS) - len(contenders)} more with --all-bonds" in short


def test_results_round_trip_and_overwrite(tmp_path):
    from ctd.report import results

    r = run(inputs())
    files = [{"source": "cme_fut", "unit": "ZB", "name": "ZB.json", "sha256": "ab"}]
    rec = results.light_record(r, files, "45683f7")
    path = results.write_light(tmp_path, rec)
    assert path == tmp_path / "results" / "light" / "ZBZ6" / "2026-10-21.json"
    [back] = results.read_light(tmp_path, "ZBZ6")
    assert back["inputs"] == files and back["code"] == "45683f7" and back["ctd"] == r.probabilities.ctd
    assert len(back["crossovers"]) == len(r.crossovers) and len(back["basket"]) == len(r.basket)
    lo = sum(b["p_ctd"][0] for b in back["basket"])
    assert lo == pytest.approx(sum(v[0] for v in r.probabilities.by_bond().values()))

    results.write_light(tmp_path, {**rec, "code": "later"})  # a re-run replaces the file
    assert [x["code"] for x in results.read_light(tmp_path, "ZBZ6")] == ["later"]
    assert results.read_light(tmp_path, "ZNZ6") == []


def test_futures_dv01_is_the_probability_weighted_dv01_over_cf():
    r = run(inputs())
    per = {b.cusip: b.dv01_cf for b in r.basket}
    probs = r.probabilities.by_bond()
    assert all(lo == hi for lo, hi in probs.values())  # normal chain, no bounds: a point
    assert r.dv01[0] == pytest.approx(sum(lo * per[c] for c, (lo, _) in probs.items()))
    assert r.ctd_dv01 == per[r.probabilities.ctd]
    assert r.krd.sum() == pytest.approx(r.dv01[0], rel=1e-12)  # KRDs add up to the DV01
    assert r.ctd_krd.sum() == pytest.approx(r.ctd_dv01, rel=1e-12)
    assert min(b.maturity for b in r.basket).year - 2026 < r.effective_maturity < 24
    assert "Key-rate DV01" in format_run(r)
    assert "probability-weighted; CTD-label" in format_run(r)


def test_atm_vol_width_and_distance_to_switch():
    r = run(inputs())
    t_e = (date(2026, 11, 20) - ASOF).days / 365
    # the chain's vol to expiry; not exact because the chain is priced at DF 0.997 and the model discounts at SOFR
    assert r.vol.price_vol * math.sqrt(t_e) == pytest.approx(SIGMA, rel=1e-3)
    assert r.yield_vol == pytest.approx(r.vol.price_vol / r.ctd_dv01)
    assert r.width == pytest.approx(r.yield_vol * math.sqrt(71 / 365))  # 21 Oct → 31 Dec horizon
    assert r.expiry_width < r.width
    near = r.nearest()
    first = near["selloff"]
    assert first is r.crossovers[0] and near["rally"] is None  # the short bond is CTD: switches lie above
    assert first.sigmas == pytest.approx(first.switch.z_bp / r.width)
    # the chain is normal in the futures price, so the normal tail in yield is close to the digital
    # (not exact: the envelope bends at each switch)
    assert first.normal == pytest.approx(first.digital.prob, abs=0.03)
    out = format_run(r)
    assert "ATM vol:" in out and "distance to switch: rally none in range; selloff" in out


def test_clusters_and_a_stale_par_curve():
    r = run(inputs())
    assert {c for cl in r.clusters for c in cl.members} == set(r.probabilities.by_bond())
    assert sum(cl.prob[0] for cl in r.clusters) == pytest.approx(1)
    assert not any("par curve is from" in w for w in r.warnings)
    stale = run(inputs(par_date=date(2026, 10, 20)))
    assert "par curve is from 2026-10-20, not 2026-10-21 (none published for 2026-10-21)" in stale.warnings
