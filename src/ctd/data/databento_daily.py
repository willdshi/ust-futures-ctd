"""Daily Databento pull (paid): CME futures and option statistics for one trading date (design §3.2;
data.md 5.14; roadmap 1e.1).

One source, ``databento_daily``, with a unit per product:

- futures ``ZT``, ``ZF``, ``ZN``, ``TN``, ``ZB``, ``UB`` (front two contracts) and ``SR1`` (front
  seven months), requested as ``<P>.c.k`` (continuous). SR3 and ZQ aren't collected.
- options ``OZT``, ``OZF``, ``OZN``, ``OTN``, ``OZB``, ``OUB``: every standard option, requested by
  parent (``O<P>.OPT``); weeklies are separate Globex products and aren't requested.

Each unit stores the statistics for a fixed window, 00:00 Chicago time on the date to 00:00 on the
next ``cme`` business day, so every record lands in exactly one file (Friday's runs to Monday and
catches the Sunday finals; the revised open interest, sent the next morning, lands in the next
date's file), and the free instrument id -> raw symbol lookup for the date. Option units also store
definitions: the whole window's on the unit's first stored date, then only for (id, raw symbol)
pairs no stored definitions file has (ids are reused), so new strikes are defined.

Without a CME licence the historical API stops about 8 hours behind real time, so a window is
queryable from about 09:00 Eastern the next business day. Nothing is pulled until the dataset range
passes the window's end and Databento's condition for each date in it is out of ``pending`` or
``missing`` (a ``degraded`` date is stored, with a note in the manifest); once a date passes, the
other units of the run don't ask again. A pull without a final
settlement and open interest on every futures contract, or with no option finals, isn't stored.
Each case raises ``NoData``: a gap the next run retries. Files are the DBN streams exactly as
received (zstd) and the lookup as the client's parsed response; each file's meta records the
request and its quoted cost. Each unit prints one line with the time each call took.
"""

import json
import re
import tempfile
import time
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from ctd.data import databento, refdata
from ctd.data.http import Http, NoData
from ctd.data.sources import Kind, RawFile, SourceSpec

SOURCE = "databento_daily"
DATASET = "GLBX.MDP3"
FUT_MONTHS = {"ZT": 2, "ZF": 2, "ZN": 2, "TN": 2, "ZB": 2, "UB": 2, "SR1": 7}
OPT_UNITS = ["OZT", "OZF", "OZN", "OTN", "OZB", "OUB"]
FIRST_DATE = date(2026, 10, 26)  # earlier dates have the CME pages and bulletin; buying them back is roadmap 1e.8
CHICAGO = ZoneInfo("America/Chicago")
OPTION_SYMBOL = re.compile(r"O[A-Z]{2}[FGHJKMNQUVXZ]\d [CP]\d+")  # a standard call or put, not a spread
NOT_READY = ("pending", "missing")
_READY: dict[date, str | None] = {}  # as-of date -> check_ready's note, once it has passed in this process


def window(asof: date) -> tuple[datetime, datetime]:
    """[00:00 Chicago on ``asof``, 00:00 Chicago on the next ``cme`` business day)."""
    nxt = refdata.calendar("cme").add_business_days(asof, 1)
    return datetime.combine(asof, datetime.min.time(), CHICAGO), datetime.combine(nxt, datetime.min.time(), CHICAGO)


def _client():
    import databento as db

    return db.Historical()  # key from DATABENTO_API_KEY


def _array(content: bytes) -> np.ndarray:
    import databento as db

    return db.DBNStore.from_bytes(content).to_ndarray()


def _known_pairs(asof: date, unit: str) -> set[tuple[int, str]] | None:
    """(instrument id, raw symbol) of every option defined in ``unit``'s stored definitions files from
    dates before ``asof``, or None if there are none (the unit's first date)."""
    from ctd import cli
    from ctd.data.store import RawStore

    store, pairs, found = RawStore(cli.data_root()), set(), False
    for d in (d for d in store.asofs() if d < asof):
        for name in store.names(d, SOURCE, unit):
            if "_definition_" in name:
                found = True
                a = _array(store.read(d, SOURCE, unit, name))
                pairs |= {(int(i), s.decode() if isinstance(s, bytes) else str(s))
                          for i, s in zip(a["instrument_id"], a["raw_symbol"])}
    return pairs if found else None


def check_ready(client, asof: date) -> str | None:
    """Raise ``NoData`` until the window is queryable; return a note if a date in it is degraded."""
    start, end = window(asof)
    available = pd.Timestamp(client.metadata.get_dataset_range(dataset=DATASET)["end"])
    if available < pd.Timestamp(end):
        raise NoData(f"{DATASET} queryable to {available}, the {asof} window ends {end.isoformat()}")
    # the window's own dates (Friday's: to Sunday); the next day's few hours are covered by the range
    dates = [(start.date() + timedelta(days=k)).isoformat() for k in range((end.date() - start.date()).days)]
    found = {c["date"]: c["condition"] for c in client.metadata.get_dataset_condition(
        dataset=DATASET, start_date=dates[0], end_date=dates[-1])}
    if waiting := [f"{d} {found.get(d, 'not listed')}" for d in dates if found.get(d, "missing") in NOT_READY]:
        raise NoData(f"{DATASET} not ready: {', '.join(waiting)}")
    degraded = [d for d in dates if found[d] == "degraded"]
    return f"{DATASET} degraded on {', '.join(degraded)}" if degraded else None


def _ready(client, asof: date) -> str | None:
    """``check_ready`` once per date: every unit asks the same question. A date not ready is asked again."""
    if asof not in _READY:
        _READY[asof] = check_ready(client, asof)
    return _READY[asof]


def _timed(times: list[str], label: str, call):
    """``call()``, appending how long it took to ``times`` (the fetch's log line)."""
    t0 = time.perf_counter()
    try:
        return call()
    finally:
        times.append(f"{label} {time.perf_counter() - t0:.1f}s")


def _get(client, asof: date, schema: str, symbols: list, stype_in: str, name: str, note: str | None,
         times: list[str]) -> RawFile:
    """One ``timeseries.get_range`` over the date's window, as received, with the request and its quoted cost."""
    import databento as db

    start, end = window(asof)
    cost = _timed(times, f"{schema} cost", lambda: client.metadata.get_cost(
        dataset=DATASET, start=start, end=end, symbols=symbols, schema=schema, stype_in=stype_in))
    params = {"dataset": DATASET, "schema": schema, "symbols": symbols, "stype_in": stype_in,
              "stype_out": "instrument_id", "start": start.isoformat(), "end": end.isoformat(),
              "client": db.__version__, "cost_usd": cost}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pull.dbn.zst"
        _timed(times, schema, lambda: client.timeseries.get_range(
            dataset=DATASET, start=start, end=end, symbols=symbols, schema=schema, stype_in=stype_in,
            stype_out="instrument_id", path=path))
        content = path.read_bytes()
    return RawFile(name, content, f"databento:{DATASET}/timeseries.get_range", method="API", params=params, note=note)


def _lookup(client, asof: date, ids: list[int], unit: str) -> tuple[dict, RawFile]:
    params = {"dataset": DATASET, "symbols": ids, "stype_in": "instrument_id", "stype_out": "raw_symbol",
              "start_date": asof.isoformat(), "end_date": (asof + timedelta(days=1)).isoformat()}
    lookup = client.symbology.resolve(**params)
    return lookup, RawFile(f"{unit}_symbology_raw_symbol_{asof}.json", json.dumps(lookup).encode(),
                           f"databento:{DATASET}/symbology.resolve", content_type="application/json",
                           method="API", params=params)


def futures_complete(stats: pd.DataFrame, asof: date, contracts: int) -> str | None:
    """Why a futures pull (``databento.stats_frame``) isn't complete for ``asof``, or None: every one
    of the ``contracts`` requested needs a final settlement and open interest dated ``asof``."""
    day = stats[stats["d"] == np.datetime64(asof)]
    final = day[(day["stat_type"] == databento.SETTLE) & ((day["stat_flags"] & 1) == 1)]["instrument_id"].nunique()
    oi = day[day["stat_type"] == databento.OPEN_INTEREST]["instrument_id"].nunique()
    if final < contracts or oi < contracts:
        return f"{final} of {contracts} contracts with a final settlement, {oi} with open interest"
    return None


def options_complete(stats: pd.DataFrame, asof: date) -> str | None:
    """Why an option pull isn't complete for ``asof``, or None: it needs final settlements dated
    ``asof`` (options without trades or open interest have no other statistics, so no count is fixed)."""
    day = stats[stats["d"] == np.datetime64(asof)]
    if not ((day["stat_type"] == databento.SETTLE) & ((day["stat_flags"] & 1) == 1)).any():
        return "no final settlements"
    return None


def new_options(lookup: dict, asof: date, known: set[tuple[int, str]]) -> list[int]:
    """Ids of the calls and puts in ``lookup`` whose (id, raw symbol) on ``asof`` isn't in ``known``."""
    out = []
    for iid, intervals in lookup["result"].items():
        sym = databento.symbol_on(intervals, asof)
        if sym and OPTION_SYMBOL.fullmatch(sym) and (int(iid), sym) not in known:
            out.append(int(iid))
    return sorted(out)


def fetch(asof: date, unit: str, http: Http) -> Iterator[RawFile]:
    times = []
    try:
        files = _fetch(asof, unit, times)
    finally:
        print(f"  {asof} {unit}: {', '.join(times)}", flush=True)  # where a slow pull spends its time
    yield from files


def _fetch(asof: date, unit: str, times: list[str]) -> list[RawFile]:
    client = _timed(times, "client", _client)
    note = _timed(times, "ready", lambda: _ready(client, asof))
    option = unit in OPT_UNITS
    if option:
        symbols, stype_in = [f"{unit}.OPT"], "parent"
    else:
        symbols, stype_in = [f"{unit}.c.{k}" for k in range(FUT_MONTHS[unit])], "continuous"
    stats_file = _get(client, asof, "statistics", symbols, stype_in, f"{unit}_statistics_{asof}.dbn.zst", note,
                      times)
    stats = databento.stats_frame(_array(stats_file.content))
    if why := (options_complete(stats, asof) if option else futures_complete(stats, asof, len(symbols))):
        raise NoData(f"{unit} {asof} not complete: {why}")
    ids = sorted(int(i) for i in stats["instrument_id"].unique())
    lookup, lookup_file = _timed(times, "symbology", lambda: _lookup(client, asof, ids, unit))
    files = [stats_file, lookup_file]
    if option:
        name = f"{unit}_definition_{asof}.dbn.zst"
        known = _timed(times, "known", lambda: _known_pairs(asof, unit))
        if known is None:
            files.append(_get(client, asof, "definition", symbols, "parent", name, note, times))
        elif new := new_options(lookup, asof, known):
            files.append(_get(client, asof, "definition", new, "instrument_id", name, note, times))
    return files


SPECS = [
    SourceSpec(SOURCE, "Databento CME statistics: Treasury futures front two, SR1 front seven, standard Treasury "
               "options (paid)", Kind.DATED, "cme",
               units=lambda asof, cal: [*FUT_MONTHS, *OPT_UNITS] if asof >= FIRST_DATE else [], fetch=fetch),
]
