"""Derived curve and rate tables (design 4): the Treasury par curve, and the overnight reference rates.

    derived/par_curve/curve=par/year=2026/part.parquet   one row per date, a column per tenor
    derived/rates/rate=sofr/year=2026/part.parquet       one row per date and rate

Both come from history-type sources, where each pull holds the whole series (Treasury's year
files, FRED) or overlapping windows of it (NY Fed). Values are taken from the latest pull. Nothing
has been revised between pulls so far (175,990 repeated FRED values, 5,684 par-curve values; the
NY Fed's own revision flag is empty on every record since 2018), and each build notes any value a
newer pull changes, so a revision would show rather than slip in.

- ``par_curve``: Treasury's daily par yield curve (``par_curve``, the year files from 1990), as
  decimals. FRED's CMT series are a second source that never wins: the build compares them with
  Treasury on every date (they are the same numbers, republished).
- ``rates``: SOFR, TGCR, BGCR and EFFR from the NY Fed (``nyfed_rates``, 2018 on): the rate, its
  1st, 25th, 75th and 99th percentiles and volume, and for EFFR the Fed's target range. FRED's
  SOFR and effective fed funds (``DFF``) are the cross-check; DFF has every calendar day, and its
  weekend values never enter the table (the NY Fed wins every date, and its gaps aren't filled).
"""

import csv
import io
import json
from datetime import date

import pyarrow as pa

from ctd.data import par_curve
from ctd.data.derived.store import Source, Table, file_ref

# --- Par curve ---------------------------------------------------------------------------------

TENORS = {  # Treasury's column -> table column
    "1 Mo": "y_1m", "1.5 Month": "y_1_5m", "2 Mo": "y_2m", "3 Mo": "y_3m", "4 Mo": "y_4m", "6 Mo": "y_6m",
    "1 Yr": "y_1y", "2 Yr": "y_2y", "3 Yr": "y_3y", "5 Yr": "y_5y", "7 Yr": "y_7y", "10 Yr": "y_10y",
    "20 Yr": "y_20y", "30 Yr": "y_30y"}
BY_YEARS = {round(par_curve._tenor_years(k), 6): v for k, v in TENORS.items()}
FRED_TENORS = {"DGS1MO": "y_1m", "DGS3MO": "y_3m", "DGS6MO": "y_6m", "DGS1": "y_1y", "DGS2": "y_2y",
               "DGS3": "y_3y", "DGS5": "y_5y", "DGS7": "y_7y", "DGS10": "y_10y", "DGS20": "y_20y",
               "DGS30": "y_30y"}
CURVE = "par"
YIELD_CURVE = "daily_treasury_yield_curve"
FROM = date(2016, 1, 1)  # the holiday calendar's start: missing days aren't checked before it

PAR_SCHEMA = pa.schema([("asof", pa.date32()), ("curve", pa.string())]
                       + [(c, pa.float64()) for c in TENORS.values()] + [("source", pa.string())])


def par_rows(curves: dict[date, dict[float, float]]) -> list[dict]:
    """Table rows from ``par_curve.parse`` output (date -> {tenor in years: yield})."""
    return [{"asof": d, "curve": CURVE, **{BY_YEARS[round(t, 6)]: y for t, y in c.items()}}
            for d, c in sorted(curves.items())]


def _revised(old: dict, new: dict) -> int:
    """How many values present in both differ."""
    return sum(1 for k, v in old.items() if k in new and new[k] != v)


def _pulls(store, sources: tuple[str, ...], unit: str, name: str) -> list[dict]:
    """Every stored pull of a history file, newest first."""
    refs = [file_ref(store, d, src, unit, name) for d in store.asofs() for src in sources
            if name in store.names(d, src, unit)]
    return sorted(refs, key=lambda r: r["asof"], reverse=True)


def _read(store, ref: dict) -> bytes:
    return store.read(date.fromisoformat(ref["asof"]), ref["source"], ref["unit"], ref["name"])


def _treasury_units(store) -> dict[str, list[dict]]:
    """Per year file, its latest pull and the one before (to note revisions)."""
    names = {n for d in store.asofs() for src in ("par_curve", "par_curve_backfill")
             for n in store.names(d, src, YIELD_CURVE)}
    out = {}
    for name in sorted(names):
        pulls = _pulls(store, ("par_curve", "par_curve_backfill"), YIELD_CURVE, name)
        out[name.rsplit("_", 1)[1][:4]] = pulls[:2]
    return out


def _treasury_read(store, key: str) -> tuple[list[dict], list[str]]:
    refs = _treasury_units(store)[key]
    latest = par_curve.parse(_read(store, refs[0]))
    notes = []
    if len(refs) > 1:
        before = par_curve.parse(_read(store, refs[1]))
        flat = lambda cs: {(d, t): y for d, c in cs.items() for t, y in c.items()}  # noqa: E731
        if n := _revised(flat(before), flat(latest)):
            notes.append(f"{n} value(s) revised since the {refs[1]['asof']} pull")
    return par_rows(latest), notes


def fred_values(content: bytes) -> dict[date, float]:
    """Date -> value as a decimal from a FRED series file (blank and "." are no value)."""
    out = {}
    for r in list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))[1:]:
        if len(r) > 1 and r[1].strip() not in ("", "."):
            out[date.fromisoformat(r[0])] = float(r[1]) / 100
    return out


def _fred_units(series: tuple[str, ...]):
    def units(store) -> dict[str, list[dict]]:
        out = {}
        for s in series:
            if pulls := _pulls(store, ("fred",), s, f"{s}.csv"):
                out[s] = pulls[:2]
        return out
    return units


def _fred_read(rows):
    """A FRED unit reader: latest pull's values to table rows (``rows(series, values)``), noting revisions."""
    def read(store, key: str) -> tuple[list[dict], list[str]]:
        refs = _fred_units((key,))(store)[key]
        latest = fred_values(_read(store, refs[0]))
        notes = []
        if len(refs) > 1 and (n := _revised(fred_values(_read(store, refs[1])), latest)):
            notes.append(f"{n} value(s) revised since the {refs[1]['asof']} pull")
        return rows(key, latest), notes
    return read


PAR_CURVE = Table(
    "par_curve", 1, PAR_SCHEMA, key=("asof", "curve"), compare=tuple(TENORS.values()),
    sources=(Source("par_curve", 1, _treasury_units, _treasury_read, lambda key: (CURVE, int(key))),
             Source("fred", 1, _fred_units(tuple(FRED_TENORS)),
                    _fred_read(lambda s, v: [{"asof": d, "curve": CURVE, FRED_TENORS[s]: y} for d, y in v.items()]),
                    lambda key: (CURVE, None))),
    winner=lambda asof, curve: "par_curve", calendar="sifma", partition="curve", calendar_from=FROM)

# --- Reference rates ---------------------------------------------------------------------------

RATES = ("sofr", "tgcr", "bgcr", "effr")
FRED_RATES = {"SOFR": "sofr", "DFF": "effr"}

RATES_SCHEMA = pa.schema([
    ("asof", pa.date32()), ("rate", pa.string()), ("value", pa.float64()), ("p1", pa.float64()),
    ("p25", pa.float64()), ("p75", pa.float64()), ("p99", pa.float64()), ("volume_bn", pa.float64()),
    ("target_from", pa.float64()), ("target_to", pa.float64()), ("source", pa.string()),
])


MISSING = (None, "", "NA")  # the NY Fed's ways of leaving a field out


def _pct(x) -> float | None:
    return None if x in MISSING else float(x) / 100


def nyfed_rows(rate: str, files: list[bytes]) -> tuple[list[dict], list[str]]:
    """Table rows for one rate from NY Fed files, oldest pull first: a later file's record for a
    date replaces an earlier one's, and a replacement that changes the rate or volume is noted."""
    by_day: dict[str, dict] = {}
    revised = 0
    for content in files:
        for r in json.loads(content)["refRates"]:
            old = by_day.get(r["effectiveDate"])
            if old and (old.get("percentRate"), old.get("volumeInBillions")) != (r.get("percentRate"),
                                                                                 r.get("volumeInBillions")):
                revised += 1
            by_day[r["effectiveDate"]] = r
    rows = [{"asof": date.fromisoformat(d), "rate": rate, "value": _pct(r.get("percentRate")),
             "p1": _pct(r.get("percentPercentile1")), "p25": _pct(r.get("percentPercentile25")),
             "p75": _pct(r.get("percentPercentile75")), "p99": _pct(r.get("percentPercentile99")),
             "volume_bn": None if r.get("volumeInBillions") in MISSING else float(r["volumeInBillions"]),
             "target_from": _pct(r.get("targetRateFrom")), "target_to": _pct(r.get("targetRateTo"))}
            for d, r in sorted(by_day.items())]
    return rows, [f"{revised} value(s) revised by a later pull"] if revised else []


def _nyfed_units(store) -> dict[str, list[dict]]:
    """Per rate, every stored file (backfill and daily windows), oldest pull first."""
    out = {}
    for rate in RATES:
        refs = [file_ref(store, d, src, rate, n) for d in store.asofs()
                for src in ("nyfed_rates_backfill", "nyfed_rates") for n in store.names(d, src, rate)]
        if refs:
            out[rate] = refs
    return out


def _nyfed_read(store, key: str) -> tuple[list[dict], list[str]]:
    return nyfed_rows(key, [_read(store, r) for r in _nyfed_units(store)[key]])


RATES_TABLE = Table(
    "rates", 1, RATES_SCHEMA, key=("asof", "rate"), compare=("value",),
    sources=(Source("nyfed_rates", 1, _nyfed_units, _nyfed_read, lambda key: (key, None)),
             Source("fred", 1, _fred_units(tuple(FRED_RATES)),
                    _fred_read(lambda s, v: [{"asof": d, "rate": FRED_RATES[s], "value": y} for d, y in v.items()]),
                    lambda key: (FRED_RATES[key], None))),
    winner=lambda asof, rate: "nyfed_rates", calendar="sifma", partition="rate", calendar_from=FROM)
