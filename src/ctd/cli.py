"""Command-line entry point.

    ctd fetch [--asof 2026-10-16] [--source cme_fut ...] [--cme-auto] [--catch-up] [--notify]
    ctd ingest
    ctd check [--from 2026-10-01] [--to 2026-10-16]
    ctd backfill
    ctd bookmarklet [--print]
    ctd run --contract ZBZ6 [--asof 2026-10-16]
    ctd derive [--table options] [--full] [--notify]
    ctd history --contract ZB --from ... --to ...  (not implemented yet)

``fetch`` and ``check`` exit 1 when there are gaps; ``derive`` when a raw file fails to read. ``fetch --notify`` also shows a desktop alert.
"""

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

CATCH_UP_DAYS = 5  # CME settlement pages show 5 trailing business days


def data_root() -> Path:
    if env := os.environ.get("CTD_DATA_ROOT"):
        return Path(env)
    repo = Path(__file__).resolve().parents[2]
    return repo / "data" if (repo / "pyproject.toml").exists() else Path.cwd() / "data"


def downloads_dir() -> Path:
    return Path(os.environ.get("CTD_DOWNLOADS", Path.home() / "Downloads"))


def default_asof(now: datetime, cutoff_hour: int) -> date:
    """Today if it's a CME business day and past the cutoff (local time), else the latest business day before."""
    from ctd.data import refdata

    cal = refdata.calendar("cme")
    today = now.date()
    if cal.is_business_day(today) and now.hour < cutoff_hour:
        return cal.prev_business_day(today)
    return cal.latest_business_day(today)


def _ingest(store, root: Path) -> list:
    """Ingest the manual-drop folder and refresh the manifests it touched. Returns the files refused."""
    from ctd.data import registry
    from ctd.data.fetch import fetch_date
    from ctd.data.inbox import collect_downloads, ingest

    for msg in collect_downloads(downloads_dir(), root / "inbox", set(registry.SOURCES)):
        print("downloads:", msg)
    results = ingest(store, root / "inbox", registry.units_for, registry.validate_manual)
    for r in results:
        print(f"ingest {r.asof} {r.source}/{r.unit}/{r.name}: {r.status}")
    touched = {(r.asof, r.source) for r in results if not r.problem}
    for asof in sorted({a for a, _ in touched}):
        specs = [registry.SOURCES[s] for a, s in touched if a == asof]
        fetch_date(asof, store, None, sources=specs, log=lambda _: None)
    return [r for r in results if r.problem]


def _alert(gaps, problems, newest: date) -> None:
    """Desktop alert for gaps that survived a retry and for refused manual files (see ctd.data.alert)."""
    from ctd.data import alert

    lines = alert.message(alert.actionable(gaps, newest), problems)
    if not lines:
        return
    for line in lines:
        print("ALERT", line)
    alert.notify(f"ctd fetch: {len(lines)} problem(s)", "\n".join(lines[:3]) + "\nSee data\\fetch.log")


def cmd_fetch(args) -> int:
    from ctd.data import refdata, registry
    from ctd.data.fetch import fetch_date
    from ctd.data.http import RequestsHttp
    from ctd.data.store import RawStore

    root = Path(args.data_root)
    store = RawStore(root)
    problems = _ingest(store, root)
    asof = args.asof or default_asof(datetime.now(), args.cutoff_hour)
    dates = refdata.calendar("cme").trailing_business_days(asof, CATCH_UP_DAYS) if args.catch_up else [asof]
    specs = [registry.SOURCES[s] for s in args.source] if args.source else None
    cme_auto = args.cme_auto or os.environ.get("CTD_CME_AUTO") == "1"
    http = RequestsHttp()
    gaps = []
    for d in dates:
        gaps += fetch_date(d, store, http, sources=specs, cme_auto=cme_auto)
    if args.notify:
        _alert(gaps, problems, max(dates))
    return _report(gaps)


def cmd_backfill(args) -> int:
    from dataclasses import replace

    from ctd.data import cme_tcf, refdata, registry
    from ctd.data.fetch import fetch_date
    from ctd.data.http import RequestsHttp
    from ctd.data.store import RawStore

    asof = args.asof or default_asof(datetime.now(), args.cutoff_hour)
    store, http = RawStore(args.data_root), RequestsHttp()
    ids = {s.id for s in registry.backfill()}
    gaps = [g for g in fetch_date(asof, store, http, sources=registry.backfill()) if g.source in ids]

    # Every dated TCF file on CME's FTP server, each stored under its own date.
    spec, cal = registry.SOURCES["cme_tcf"], refdata.calendar("cme")
    odd = []
    for d, formats in cme_tcf.listing(http).items():
        if d > asof:
            continue
        if not cal.is_business_day(d):
            odd.append(d.isoformat())
            continue
        one = replace(spec, units=lambda a, c, f=tuple(formats): list(f))
        got = fetch_date(d, store, http, sources=[one], fill_missing=False, log=lambda _: None)
        gaps += [g for g in got if g.source == spec.id]
        print(f"{d} cme_tcf: {_source_status(store, d, spec.id)}")
    if odd:
        print(f"cme_tcf: skipped files dated on non-business days: {', '.join(odd)}")

    # TreasuryDirect prices by date (available from 30 May 2008), each under its own date.
    if args.prices_from:
        spec, cal = registry.SOURCES["td_prices"], refdata.calendar("sifma")
        d = args.prices_from
        while d <= asof:
            if cal.is_business_day(d):
                got = fetch_date(d, store, http, sources=[spec], fill_missing=False, log=lambda _: None)
                gaps += [g for g in got if g.source == spec.id]
                print(f"{d} td_prices: {_source_status(store, d, spec.id)}")
            d += timedelta(days=1)
    return _report(gaps)


def _source_status(store, asof: date, source: str) -> str:
    from ctd.data import manifest as mf

    return mf.load(store, asof)["sources"][source]["status"]


def cmd_bookmarklet(args) -> int:
    from ctd.data import bookmarklet

    if args.print:
        print(bookmarklet.url())
        return 0
    page = Path(args.data_root) / "cme_bookmarklet.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(bookmarklet.install_page(), encoding="utf-8")
    print(f"wrote {page}: open it in Chrome and drag the link onto the bookmarks bar")
    return 0


def cmd_ingest(args) -> int:
    from ctd.data.store import RawStore

    root = Path(args.data_root)
    return 1 if _ingest(RawStore(root), root) else 0


def cmd_check(args) -> int:
    from ctd.data import manifest as mf
    from ctd.data.store import RawStore

    store = RawStore(args.data_root)
    gaps, warnings = [], []
    for asof in store.asofs():
        if (args.date_from and asof < args.date_from) or (args.date_to and asof > args.date_to):
            continue
        man = mf.load(store, asof)
        gaps += mf.gaps(man)
        warnings += [f"asof={asof} source={s} status=manual (coverage not verified)"
                     for s, e in man["sources"].items() if e["status"] == mf.MANUAL]
    for w in warnings:
        print("warning:", w)
    return _report(gaps)


def _report(gaps) -> int:
    for g in gaps:
        print("GAP", g)
    print(f"{len(gaps)} gap(s)")
    return 1 if gaps else 0


def light_inputs(store, contract: str, asof: date):
    """Everything the light model needs for ``contract`` on ``asof``, from the raw store only, and
    the raw files read (source, unit, name, sha256)."""
    from ctd.data import cme_bulletin, cme_settlements, cme_tcf, nyfed, refdata, td_prices
    from ctd.model.light import LightInputs
    from ctd.reference.contracts import MONTH_CODES, parse_contract
    from ctd.reference.delivery import delivery_for
    from ctd.reference.options import LABELS, expiry_for

    product, month = parse_contract(contract, asof)
    sifma = refdata.calendar("sifma")
    cal = delivery_for(refdata.delivery_calendar(), product, month)
    futures = cme_settlements.read_futures(store, asof, product)
    if month not in futures:
        raise ValueError(f"no {contract} settlement on {asof}")
    prices, _ = td_prices.read(store, asof)
    sofr_date, sofr = nyfed.read_latest(store, asof)
    label = f"{LABELS[month.month - 1]}{month.year % 100:02d}"
    expiry = expiry_for(refdata.option_expiries(), product, label)
    assert expiry.underlying[-2] == MONTH_CODES[month.month - 1]
    inputs = LightInputs(
        contract, asof, sifma.add_business_days(asof, 1), cal.first_delivery, cal.last_delivery,
        cme_tcf.read_basket(store, asof, product, month), prices, futures[month].settle, sofr, sofr_date,
        expiry, cme_bulletin.read_options(store, asof), sifma,
        {p["code"]: p["face"] for p in refdata.cme_products()["treasury"]}[product])
    read = [("td_prices", "securityprice", f"securityprice_{asof.isoformat()}.csv"),
            ("cme_tcf", "csv", cme_tcf.file_name(asof, "csv")),
            ("cme_fut", product, store.names(asof, "cme_fut", product)[0]),
            *(("nyfed_rates", "sofr", n) for n in store.names(asof, "nyfed_rates", "sofr")),
            ("cme_bulletin", "Section42", "Section42.pdf")]
    files = [{"source": s, "unit": u, "name": n, "sha256": store.meta(asof, s, u, n)["sha256"]} for s, u, n in read]
    return inputs, files


def code_version() -> str | None:
    """``git describe`` of the checkout this code runs from (``-dirty`` with uncommitted changes)."""
    import subprocess

    try:
        out = subprocess.run(["git", "describe", "--always", "--dirty"], cwd=Path(__file__).parent,
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def cmd_run(args) -> int:
    from ctd.data.store import RawStore
    from ctd.model import light
    from ctd.report import results
    from ctd.report.light import format_run

    asof = args.asof or default_asof(datetime.now(), args.cutoff_hour)
    try:
        inputs, files = light_inputs(RawStore(args.data_root), args.contract, asof)
        result = light.run(inputs)
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(f"ctd run {args.contract} {asof}: {e}", file=sys.stderr)
        return 1
    print(format_run(result, all_bonds=args.all_bonds))
    if not args.no_save:
        path = results.write_light(args.data_root, results.light_record(result, files, code_version()))
        print(f"\nsaved {path}")
    return 0


def cmd_derive(args) -> int:
    from ctd.data import alert
    from ctd.data.derived import futures, options, quality
    from ctd.data.derived.store import DerivedStore, build
    from ctd.data.store import RawStore

    tables = {t.name: t for t in (options.TABLE, futures.TABLE)}
    store, dstore = RawStore(args.data_root), DerivedStore(args.data_root)
    problems = []
    for name in args.table or list(tables):
        r = build(dstore, store, tables[name], full=args.full, code=code_version())
        print(f"{name}: {sum(r.read.values())} unit(s) read, {r.partitions} partition(s) rewritten")
        for source, notes in r.notes.items():
            for unit, lines in notes.items():
                for line in lines:
                    print(f"  note {source} {unit}: {line}")
        for source, errors in r.errors.items():
            problems += [f"{name} {source} {unit}: {msg}" for unit, msg in errors.items()]
        for o in r.disagreements:
            print(f"  overlap {o['asof']} {o['product']}: {o['differ']} of {o['both']} rows differ "
                  f"({o['winner']} vs {o['other']})")
        for product, days in (r.missing_days or {}).items():
            if days:
                print(f"  missing {product}: {len(days)} trading day(s) with no rows: {', '.join(days)}")
    if (dstore.table_dir("options") / "_build.json").exists() and (dstore.table_dir("futures") / "_build.json").exists():
        summary = quality.build(dstore, full=args.full, code=code_version())
        if summary is None:
            print(f"{quality.NAME}: up to date")
        for product, s in (summary or {}).items():
            print(f"{quality.NAME} {product}: {s['flagged']} of {s['chains']} chains flagged on {s['flagged_dates']} "
                  f"date(s) {s['by_flag']}")
    for line in problems:
        print("ERROR", line)
    if problems and args.notify:
        alert.notify(f"ctd derive: {len(problems)} problem(s)", "\n".join(problems[:3]) + "\nSee data\\fetch.log")
    return 1 if problems else 0


def cmd_not_implemented(args) -> int:
    print(f"ctd {args.command}: not implemented yet", file=sys.stderr)
    return 2


def build_parser() -> argparse.ArgumentParser:
    from ctd.data import registry

    p = argparse.ArgumentParser(prog="ctd", description=__doc__.splitlines()[0])
    p.add_argument("--data-root", default=data_root(), type=Path,
                   help="raw store root (default: $CTD_DATA_ROOT or <repo>/data)")
    sub = p.add_subparsers(dest="command", required=True)

    def asof_args(sp):
        sp.add_argument("--asof", type=date.fromisoformat, help="as-of date (default: latest settled business day)")
        sp.add_argument("--cutoff-hour", type=int, default=int(os.environ.get("CTD_FETCH_CUTOFF_HOUR", "18")),
                        help="local hour after which today's settlements count as published (default 18)")

    f = sub.add_parser("fetch", help="snapshot every source for an as-of date")
    asof_args(f)
    f.add_argument("--source", action="append", choices=sorted(registry.SOURCES), help="only these sources")
    f.add_argument("--cme-auto", action="store_true", help="fetch CME automatically (or set CTD_CME_AUTO=1)")
    f.add_argument("--catch-up", action="store_true",
                   help=f"also fill gaps in the {CATCH_UP_DAYS} business days ending on --asof")
    f.add_argument("--notify", action="store_true",
                   help="desktop alert for gaps before the newest date and refused manual files")
    f.set_defaults(func=cmd_fetch)

    b = sub.add_parser("backfill", help="one-off histories (par curve years, NY Fed since 2018, CME TCF files)")
    asof_args(b)
    b.add_argument("--prices-from", type=date.fromisoformat,
                   help="also store TreasuryDirect daily prices from this date (earliest 2008-05-30)")
    b.set_defaults(func=cmd_backfill)

    sub.add_parser("ingest", help="move bookmarklet downloads and manual-drop files into the raw store"
                   ).set_defaults(func=cmd_ingest)

    k = sub.add_parser("bookmarklet", help="build the Chrome bookmarklet that downloads CME files")
    k.add_argument("--print", action="store_true", help="print the javascript: URL instead of writing the page")
    k.set_defaults(func=cmd_bookmarklet)

    c = sub.add_parser("check", help="list gaps across stored manifests")
    c.add_argument("--from", dest="date_from", type=date.fromisoformat)
    c.add_argument("--to", dest="date_to", type=date.fromisoformat)
    c.set_defaults(func=cmd_check)

    r = sub.add_parser("run", help="light model (design 5.11) for one contract and date, from the store")
    r.add_argument("--contract", required=True, help="e.g. ZBZ6")
    asof_args(r)
    r.add_argument("--no-save", action="store_true", help="print only; don't write data/results/light/...")
    r.add_argument("--all-bonds", action="store_true", help="list every basket bond, not just the contenders")
    r.set_defaults(func=cmd_run)
    d = sub.add_parser("derive", help="bring the derived Parquet tables up to date with the raw store")
    d.add_argument("--table", action="append", choices=["options", "futures"], help="only these tables")
    d.add_argument("--full", action="store_true", help="rebuild from scratch (must give the same tables)")
    d.add_argument("--notify", action="store_true", help="desktop alert when a raw file fails to read")
    d.set_defaults(func=cmd_derive)
    h = sub.add_parser("history", help="historical mode (not implemented yet)")
    h.add_argument("--contract")
    h.add_argument("--from", dest="date_from", type=date.fromisoformat)
    h.add_argument("--to", dest="date_to", type=date.fromisoformat)
    h.set_defaults(func=cmd_not_implemented)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
