"""Collect every source for one as-of date into the raw store, and record the result in its manifest."""

from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path

from ctd.data import manifest as mf
from ctd.data import refdata, registry
from ctd.data.http import Http, NoData
from ctd.data.inbox import MANUAL_UNIT
from ctd.data.sources import SourceSpec
from ctd.data.store import RawStore, utc_now

# A source with nothing for a date this many business days later never will have (holiday, no
# publication). Before that, nothing may just mean not published yet: a failure, retried next run.
NO_DATA_SETTLED_AFTER = 5


def _unit_entry(status: str, files: list[str], origin: str | None = None, error: str | None = None,
                provisional: list[str] | None = None, notes: list[str] | None = None) -> dict:
    entry = {"status": status, "origin": origin, "files": files, "attempted_at": utc_now(), "error": error}
    if provisional:
        entry["provisional"] = provisional
    if notes:
        entry["notes"] = notes
    return entry


def _provisional(spec: SourceSpec, store: RawStore, asof: date, unit: str, names: list[str]) -> list[str]:
    """Stored files still waiting to be completed (the replaceable exception, ``SourceSpec.provisional``)."""
    if spec.provisional is None:
        return []
    return [n for n in names if spec.provisional(store.read(asof, spec.id, unit, n))]


def _run_unit(spec: SourceSpec, asof: date, unit: str, store: RawStore, http: Http | None, lag: int,
              prev: dict | None, has_manual: bool) -> dict:
    names = store.names(asof, spec.id, unit)
    pending = _provisional(spec, store, asof, unit, names)
    if prev and prev["status"] == mf.OK and set(prev["files"]) <= set(names) and not pending:
        return prev
    if prev and prev["status"] == mf.NOT_EXPECTED and not names:
        return prev
    if names and any(store.meta(asof, spec.id, unit, n).get("origin") == "manual" for n in names):
        return _unit_entry(mf.OK, names, origin="manual")
    if spec.fetch is None:
        return _unit_entry(mf.MANUAL if has_manual else mf.MANUAL_NEEDED, names)
    if http is None:  # offline refresh: report, don't fetch
        if prev and prev["status"] in (mf.FAILED, mf.OK):
            return prev
        return _unit_entry(mf.MISSING, names)
    stored, notes = [], []
    try:
        for f in spec.fetch(asof, unit, http):
            if f.note and f.note not in notes:
                notes.append(f.note)
            meta = {"origin": "auto", "url": f.url, "http_status": f.status, "content_type": f.content_type,
                    "method": f.method, "params": f.params, "downloaded_at": utc_now()}
            if not store.write(asof, spec.id, unit, f.name, f.content, meta) and f.name in pending \
                    and not spec.provisional(f.content):
                store.replace(asof, spec.id, unit, f.name, f.content, meta)  # the one exception
            stored.append(f.name)
    except NoData as e:
        if lag > NO_DATA_SETTLED_AFTER and not stored:
            return _unit_entry(mf.NOT_EXPECTED, [], error=f"no data published: {e}")
        return _unit_entry(mf.FAILED, store.names(asof, spec.id, unit), error=f"{type(e).__name__}: {e}")
    except Exception as e:  # one failing source must not stop the others
        return _unit_entry(mf.FAILED, store.names(asof, spec.id, unit), error=f"{type(e).__name__}: {e}")
    return _unit_entry(mf.OK, stored, origin="auto", provisional=_provisional(spec, store, asof, unit, stored),
                       notes=notes)


def _run_source(spec: SourceSpec, asof: date, store: RawStore, http: Http | None, today: date,
                prev: dict | None) -> dict:
    cal = refdata.calendar(spec.calendar)
    entry = {"description": spec.description, "kind": str(spec.kind), "calendar": spec.calendar,
             "schedule": spec.schedule, "status": mf.NOT_EXPECTED, "reason": None, "units": {}}
    if not cal.is_business_day(asof):
        entry["reason"] = f"not a {spec.calendar} business day"
        return entry
    units = spec.units(asof, cal)
    if not units:
        entry["reason"] = "source not published on this date"
        return entry
    lag = cal.business_days_after(asof, today)
    has_manual = bool(store.names(asof, spec.id, MANUAL_UNIT))
    prev_units = (prev or {}).get("units") or {}
    for unit in units:
        entry["units"][unit] = _run_unit(spec, asof, unit, store, http, lag, prev_units.get(unit), has_manual)
    entry["status"] = mf.worst(u["status"] for u in entry["units"].values())
    return entry


def fetch_date(asof: date, store: RawStore, http: Http | None, *, sources: Iterable[SourceSpec] | None = None,
               today: date | None = None, fill_missing: bool = True,
               log: Callable[[str], None] = print) -> list[mf.Gap]:
    """Fetch what's missing for ``asof``, update its manifest and return its gaps.

    With ``http=None`` nothing is downloaded; the manifest is refreshed from what's in the store.
    Daily sources not run this time keep their previous entry, or are recorded as missing unless
    ``fill_missing`` is False (backfilling dates from before collection started).
    """
    today = today or date.today()
    man = mf.load(store, asof)
    specs = list(sources) if sources is not None else registry.daily()
    entries = {}
    for spec in specs:
        log(f"{asof} {spec.id} ...")
        entries[spec.id] = _run_source(spec, asof, store, http, today, man["sources"].get(spec.id))
        log(f"{asof} {spec.id}: {entries[spec.id]['status']}")

    def merge(man: dict) -> None:  # into the stored manifest, under its lock: other runs' entries stay
        man["sources"].update(entries)
        for spec in registry.daily() if fill_missing else []:
            if spec.id not in man["sources"]:
                man["sources"][spec.id] = {"description": spec.description, "kind": str(spec.kind),
                                           "calendar": spec.calendar, "schedule": spec.schedule,
                                           "status": mf.MISSING, "reason": "not run yet", "units": {}}

    man = mf.update(store, asof, merge)
    gaps = mf.gaps(man, registry.occasional())
    if gaps:
        log_gaps(store.root, gaps)
    return gaps


def log_gaps(root: Path, gaps: list[mf.Gap]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with open(root / "gaps.log", "a", encoding="utf-8") as f:
        for g in gaps:
            f.write(f"{utc_now()} {g}\n")
