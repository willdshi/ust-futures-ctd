"""Derived tables: one schema per kind of data, whatever the source, built from the raw store (design 4).

Layout under the data root::

    derived/staging/<table>/<source>/product=ZN/year=2026/part.parquet   one source's rows, as read
    derived/<table>/product=ZN/year=2026/part.parquet                    merged: precedence applied
    derived/<table>/_build.json                                          what each partition was built from

A derived table is a cache: rebuilt from the raw store, never edited by hand, never holding data the
raw store lacks. ``build`` is incremental and must give the same tables as ``build(full=True)``:

- A source splits its raw files into units (one date's file, or one product's backfill), each with
  the raw files it's read from. A unit whose files (by sha256) differ from the last build is dirty,
  and only dirty units are read again; their rows replace the old ones in the staging partitions
  they can fall in (``Source.scope``).
- A source whose ``version`` changes is rebuilt from scratch; so is every source of a table whose
  ``version`` (the schema) changes. Bump them by hand when a reader's output or a schema changes.
- Merged partitions are rebuilt from staging wherever staging changed. On each date the table's
  precedence rule picks one source; the others are compared with it on the overlap (``overlap`` in
  ``_build.json``) and never fill its gaps.
- A unit that fails to read is left out (its old rows dropped), reported, and retried next build.
- Trading days (on the table's calendar, ``reference/data/holidays.csv``) with no rows for a
  product, between its first date (or the table's ``calendar_from``) and its last, are listed in
  ``_build.json`` as ``missing_days``.

Partition columns (``product`` by default, or the table's ``partition``, and ``year``) live in
the path, not in the files.
"""

import json
import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

PART = "part.parquet"
BUILD = "_build.json"
UNIT = "unit"  # staging column: the unit a row was read from


def partitioning(key: str = "product") -> ds.Partitioning:
    return ds.partitioning(pa.schema([(key, pa.string()), ("year", pa.int16())]), flavor="hive")



def file_ref(store, asof: date, source: str, unit: str, name: str) -> dict:
    """A raw file as a build input: where it is and its sha256 (from the meta sidecar)."""
    return {"asof": asof.isoformat(), "source": source, "unit": unit, "name": name,
            "sha256": store.meta(asof, source, unit, name)["sha256"]}


@dataclass(frozen=True)
class Source:
    name: str  # the raw source id, also the rows' ``source`` value
    version: int  # bump when the reader's output changes: this source's staging is rebuilt
    units: Callable  # (raw store) -> {unit key: [file_ref, ...]}
    read: Callable  # (raw store, unit key) -> (rows as dicts with the table's columns, notes)
    scope: Callable  # (unit key) -> (partition value or None, year or None): staging partitions its rows can be in


@dataclass(frozen=True)
class Table:
    name: str
    version: int  # schema version: bump when the columns change, and everything is rebuilt
    schema: pa.Schema  # every column, the partition column and ``source`` included
    key: tuple[str, ...]  # identifies a row on a date (with ``asof``)
    compare: tuple[str, ...]  # columns cross-checked where sources overlap
    sources: tuple[Source, ...]
    winner: Callable  # (asof, product) -> the source whose rows the table keeps
    calendar: str | None = "cme"  # business calendar whose days every product should have
    partition: str = "product"  # the column partitioned on, with the year
    calendar_from: date | None = None  # missing days aren't checked before this (the calendar's start)


def _without(schema: pa.Schema, *names: str) -> pa.Schema:
    return pa.schema([f for f in schema if f.name not in names])


def _part_dir(base: Path, value: str, year: int, key: str = "product") -> Path:
    return base / f"{key}={value}" / f"year={year}"


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, path)


class DerivedStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    def table_dir(self, table: str) -> Path:
        return self.root / "derived" / table

    def staging_dir(self, table: str, source: str) -> Path:
        return self.root / "derived" / "staging" / table / source

    def partitions(self, base: Path) -> list[tuple[str, int]]:
        """(partition value, year) of every partition file under ``base``."""
        out = []
        for p in base.glob(f"*=*/year=*/{PART}"):
            out.append((p.parent.parent.name.split("=", 1)[1], int(p.parent.name.split("=", 1)[1])))
        return sorted(out)

    def partition_key(self, base: Path) -> str:
        """The partition column of the table under ``base`` (from its directory names)."""
        first = next(base.glob(f"*=*/year=*/{PART}"), None)
        return first.parent.parent.name.split("=", 1)[0] if first else "product"

    def read_part(self, base: Path, value: str, year: int, key: str = "product") -> pa.Table | None:
        path = _part_dir(base, value, year, key) / PART
        return pq.read_table(path) if path.exists() else None

    def write_part(self, base: Path, value: str, year: int, table: pa.Table, key: str = "product") -> None:
        """Write (or, for an empty table, remove) one partition, atomically."""
        d = _part_dir(base, value, year, key)
        if table.num_rows == 0:
            shutil.rmtree(d, ignore_errors=True)
            return
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f".{PART}.{uuid.uuid4().hex}.tmp"
        pq.write_table(table, tmp, compression="zstd")
        os.replace(tmp, d / PART)

    def state(self, table: str) -> dict:
        path = self.table_dir(table) / BUILD
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def save_state(self, table: str, state: dict) -> None:
        _write_atomic(self.table_dir(table) / BUILD,
                      (json.dumps(state, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))

    def read(self, table: str, products: list[str] | None = None, start: date | None = None,
             end: date | None = None) -> pd.DataFrame:
        """A merged table as a DataFrame (dates as ``date``, nullable integers as ``Int64``), filtered
        on its partition column (``products``: product, or a bond table's ``type``) and on ``asof`` from
        ``start`` to ``end`` inclusive. Partitions not needed aren't read. A table with no dates (one
        file, ``securities``) is read whole."""
        base = self.table_dir(table)
        if (base / PART).exists():
            return pq.read_table(base / PART).to_pandas(types_mapper={pa.int64(): pd.Int64Dtype()}.get)
        if not self.partitions(base):
            raise FileNotFoundError(f"no derived {table} table under {base}; run `ctd derive --table {table}`")
        key = self.partition_key(base)
        dataset = ds.dataset(base, format="parquet", partitioning=partitioning(key))
        cond = None
        for c in ([pc.field(key).isin(products)] if products else []) + \
                 ([pc.field("year") >= start.year, pc.field("asof") >= start] if start else []) + \
                 ([pc.field("year") <= end.year, pc.field("asof") <= end] if end else []):
            cond = c if cond is None else cond & c
        t = dataset.to_table(filter=cond).drop_columns(["year"])
        return t.to_pandas(types_mapper={pa.int64(): pd.Int64Dtype()}.get)


    def raw_files(self, table: str, value: str, start: date, end: date, sources: list[str]) -> list[dict]:
        """The raw files (``file_ref`` dicts) behind ``sources``' rows of ``table`` for one partition
        value (``product``, ``rate``, ...) from ``start`` to ``end``: the units the rows were read
        from (staging), and each unit's files as last built (``_build.json``)."""
        state, key = self.state(table), self.partition_key(self.table_dir(table))
        lo, hi = pa.scalar(start, pa.date32()), pa.scalar(end, pa.date32())
        refs = {}
        for src in sources:
            units = set()
            for year in range(start.year, end.year + 1):
                part = self.read_part(self.staging_dir(table, src), value, year, key)
                if part is not None:
                    within = pc.and_(pc.greater_equal(part["asof"], lo), pc.less_equal(part["asof"], hi))
                    units |= set(part.filter(within)[UNIT].to_pylist())
            for u in sorted(units):
                for r in state["sources"][src]["units"][u]:
                    refs[(r["asof"], r["source"], r["unit"], r["name"])] = r
        return list(refs.values())


@dataclass
class Report:
    table: str
    read: dict  # source -> number of units read this build
    errors: dict  # source -> {unit: message}
    notes: dict  # source -> {unit: [note, ...]}
    disagreements: list  # overlap summaries with differences
    partitions: int  # merged partitions rewritten
    missing_days: dict | None = None  # product -> trading days with no rows (ISO dates)


def _build_source(dstore: DerivedStore, store, table: Table, src: Source, rec: dict,
                  log: Callable) -> tuple[set, dict, dict, int]:
    """Bring one source's staging up to date. Returns (partitions rewritten, errors, notes, units read)."""
    base = dstore.staging_dir(table.name, src.name)
    pk = table.partition
    staging = _without(table.schema, pk).append(pa.field(UNIT, pa.string()))
    current = src.units(store)
    done = rec["units"]
    dirty = sorted(k for k in current if current[k] != done.get(k)) + sorted(k for k in done if k not in current)
    if not dirty:
        return set(), {}, {}, 0
    log(f"{table.name}/{src.name}: reading {len([k for k in dirty if k in current])} unit(s)")
    columns = _without(table.schema, "source")
    got_tables, errors, notes = [], {}, {}
    for k in dirty:
        done.pop(k, None)
        if k not in current:
            continue
        try:
            got, note = src.read(store, k)
        except (ValueError, KeyError, FileNotFoundError) as e:
            errors[k] = f"{type(e).__name__}: {e}"
            continue
        t = got if isinstance(got, pa.Table) else pa.Table.from_pylist(got, schema=columns)
        t = t.select(columns.names).cast(columns)
        got_tables.append(t.append_column("source", pa.repeat(pa.scalar(src.name), t.num_rows))
                           .append_column(UNIT, pa.repeat(pa.scalar(k), t.num_rows)))
        if note:
            notes[k] = list(note)
        done[k] = current[k]
    new = pa.concat_tables(got_tables) if got_tables else \
        columns.append(pa.field("source", pa.string())).append(pa.field(UNIT, pa.string())).empty_table()
    scopes = [src.scope(k) for k in dirty]
    touched = {(p, y) for p, y in dstore.partitions(base)
               if any((sp is None or sp == p) and (sy is None or sy == y) for sp, sy in scopes)}
    years = pc.year(new["asof"])
    pairs = pa.table({"p": new[pk], "y": years}).group_by(["p", "y"]).aggregate([])
    touched |= set(zip(pairs["p"].to_pylist(), pairs["y"].to_pylist()))
    dirty_keys = pa.array(dirty, pa.string())
    for product, year in sorted(touched):
        old = dstore.read_part(base, product, year, pk)
        keep = [] if old is None else [old.filter(pc.invert(pc.is_in(old[UNIT], dirty_keys)))]
        mask = pc.and_(pc.equal(new[pk], product), pc.equal(years, year))
        add = [new.filter(mask).drop_columns([pk]).select(staging.names)] if new.num_rows else []
        part = pa.concat_tables([t.cast(staging) for t in keep + add]) if keep + add else staging.empty_table()
        dstore.write_part(base, product, year, part.sort_by([("asof", "ascending")] + [(c, "ascending") for c in
                                                            table.key if c not in ("asof", pk)]), pk)
    return touched, errors, notes, len([k for k in dirty if k in current and k not in errors])


def _jsonable(v):
    if v is None or v is pd.NA or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, date):
        return v.isoformat()
    return v.item() if hasattr(v, "item") else v


def _overlap(table: Table, product: str, frame: pd.DataFrame) -> list[dict]:
    """Per date with several sources: how each other source compares with the winner."""
    out = []
    keys = [c for c in table.key if c not in ("asof", table.partition)]
    for asof, day in frame.groupby("asof"):
        sources = set(day["source"])
        if len(sources) < 2:
            continue
        win = table.winner(asof, product)
        a = day[day["source"] == win]
        for other in sorted(sources - {win}):
            b = day[day["source"] == other]
            on = keys or ["_one"]  # a table with one row per date and partition value
            m = a.assign(_one=0).merge(b.assign(_one=0), on=on, how="outer", suffixes=("", "_o"), indicator=True)
            both = m[m["_merge"] == "both"]
            differ = pd.Series(False, index=both.index)
            for c in table.compare:
                x, y = both[c], both[f"{c}_o"]
                known = x.notna() & y.notna()
                if pd.api.types.is_float_dtype(x):
                    bad = known & ((x.astype(float) - y.astype(float)).abs() > 1e-9)
                else:
                    bad = known & (x.astype(object) != y.astype(object))
                differ |= bad
            cols = keys + [x for c in table.compare for x in (c, f"{c}_o")]
            examples = [{k: _jsonable(v) for k, v in row.items()}
                        for row in both[differ][cols].head(3).astype(object).to_dict("records")]
            out.append({"asof": asof.isoformat(), "product": product, "winner": win, "other": other,
                        "both": len(both), "differ": int(differ.sum()),
                        f"only_{win}": int((m["_merge"] == "left_only").sum()),
                        f"only_{other}": int((m["_merge"] == "right_only").sum()), "examples": examples})
    return out


def _calendar_hash() -> str:
    """sha256 of the holiday list, so missing days are recomputed when it changes."""
    import hashlib

    from ctd.data import refdata

    return hashlib.sha256(refdata._ref_file("holidays.csv").read_bytes()).hexdigest()


def missing_days(dstore: DerivedStore, table: Table) -> dict[str, list[str]]:
    """Per product, the business days on ``table.calendar`` from its first to its last date with no rows."""
    from ctd.data import refdata

    base = dstore.table_dir(table.name)
    if table.calendar is None or not dstore.partitions(base):
        return {}
    cal = refdata.calendar(table.calendar)
    pk = table.partition
    pairs = ds.dataset(base, format="parquet", partitioning=partitioning(pk)).to_table(columns=[pk, "asof"])
    pairs = pairs.group_by([pk, "asof"]).aggregate([])
    dates: dict[str, set] = {}
    for product, d in zip(pairs[pk].to_pylist(), pairs["asof"].to_pylist()):
        dates.setdefault(product, set()).add(d)
    out = {}
    for product, have in sorted(dates.items()):
        d, last, miss = max(min(have), table.calendar_from or min(have)), max(have), []
        while d <= last:
            if cal.is_business_day(d) and d not in have:
                miss.append(d.isoformat())
            d += timedelta(days=1)
        out[product] = miss
    return out


def build(dstore: DerivedStore, store, table: Table, full: bool = False, code: str | None = None,
          log: Callable = print) -> Report:
    """Bring ``table`` up to date with the raw store (``full``: from scratch). ``code`` is the code
    version recorded with a build (``git describe``)."""
    state = dstore.state(table.name)
    if full or state.get("version") != table.version:
        shutil.rmtree(dstore.table_dir(table.name), ignore_errors=True)
        shutil.rmtree(dstore.root / "derived" / "staging" / table.name, ignore_errors=True)
        state = {}
    state = {"table": table.name, "version": table.version, "sources": state.get("sources", {}),
             "partitions": state.get("partitions", {}), "overlap": state.get("overlap", []),
             **{k: state[k] for k in ("missing_days", "calendar") if k in state}}
    touched, report = set(), Report(table.name, {}, {}, {}, [], 0)
    for src in table.sources:
        rec = state["sources"].get(src.name)
        if rec is None or rec["version"] != src.version:
            shutil.rmtree(dstore.staging_dir(table.name, src.name), ignore_errors=True)
            rec = {"version": src.version, "units": {}}
        parts, errors, notes, n = _build_source(dstore, store, table, src, rec, log)
        rec["errors"] = errors
        rec["notes"] = {**{k: v for k, v in rec.get("notes", {}).items() if k in rec["units"]}, **notes}
        state["sources"][src.name] = rec
        touched |= parts
        report.read[src.name], report.errors[src.name], report.notes[src.name] = n, errors, notes
    for name in set(state["sources"]) - {s.name for s in table.sources}:  # a source dropped from the table
        shutil.rmtree(dstore.staging_dir(table.name, name), ignore_errors=True)
        del state["sources"][name]
        touched |= {tuple(k.split("/")) for k in state["partitions"]}
    touched = {(p, int(y)) for p, y in touched}

    base = dstore.table_dir(table.name)
    pk = table.partition
    merged_schema = _without(table.schema, pk)
    overlap = [o for o in state["overlap"] if (o["product"], int(o["asof"][:4])) not in touched]
    for product, year in sorted(touched):
        parts = [t for s in table.sources
                 if (t := dstore.read_part(dstore.staging_dir(table.name, s.name), product, year, pk)) is not None]
        frame = pa.concat_tables([t.drop_columns([UNIT]).cast(merged_schema) for t in parts]) if parts \
            else merged_schema.empty_table()
        dates = frame["asof"].to_pylist()
        win = {d: table.winner(d, product) for d in set(dates)}
        keep = pa.array([win[d] == s for d, s in zip(dates, frame["source"].to_pylist())], pa.bool_())
        merged = frame.filter(keep) if frame.num_rows else frame
        dstore.write_part(base, product, year, merged.sort_by(
            [("asof", "ascending")] + [(c, "ascending") for c in table.key if c not in ("asof", pk)]), pk)
        key = f"{product}/{year}"
        if merged.num_rows:
            counts = pd.Series(merged["source"].to_pylist()).value_counts()
            state["partitions"][key] = {"rows": merged.num_rows, "by_source": counts.to_dict(),
                                        "from": min(merged["asof"].to_pylist()).isoformat(),
                                        "to": max(merged["asof"].to_pylist()).isoformat()}
        else:
            state["partitions"].pop(key, None)
        if len(parts) > 1:
            overlap += _overlap(table, product, frame.to_pandas(types_mapper={pa.int64(): pd.Int64Dtype()}.get))
    state["overlap"] = sorted(overlap, key=lambda o: (o["asof"], o["product"], o["other"]))
    state["partitions"] = dict(sorted(state["partitions"].items()))
    report.partitions = len(touched)
    report.disagreements = [o for o in state["overlap"] if o["differ"]]
    calendar = _calendar_hash()
    fresh = touched or "missing_days" not in state or state.get("calendar") != calendar
    if fresh:
        state["missing_days"] = missing_days(dstore, table)
        state["calendar"] = calendar
    report.missing_days = state["missing_days"]
    if fresh or any(report.errors.values()) or not (dstore.table_dir(table.name) / BUILD).exists():
        state["code"] = code
        state["built_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        dstore.save_state(table.name, state)
    return report
