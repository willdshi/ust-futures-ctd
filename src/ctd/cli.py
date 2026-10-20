"""Command-line entry point.

    ctd fetch [--asof 2026-10-16] [--source cme_fut ...] [--cme-auto] [--catch-up]
    ctd ingest
    ctd check [--from 2026-10-01] [--to 2026-10-16]
    ctd backfill
    ctd run --contract ZBZ6 --asof 2026-10-16      (not implemented yet)
    ctd history --contract ZB --from ... --to ...  (not implemented yet)

``fetch`` and ``check`` exit 1 when there are gaps, so a scheduler can alert on the exit code.
"""

import argparse
import os
import sys
from datetime import date, datetime
from pathlib import Path

CATCH_UP_DAYS = 5  # CME settlement pages show 5 trailing business days


def data_root() -> Path:
    if env := os.environ.get("CTD_DATA_ROOT"):
        return Path(env)
    repo = Path(__file__).resolve().parents[2]
    return repo / "data" if (repo / "pyproject.toml").exists() else Path.cwd() / "data"


def default_asof(now: datetime, cutoff_hour: int) -> date:
    """Today if it's a CME business day and past the cutoff (local time), else the latest business day before."""
    from ctd.data import refdata

    cal = refdata.calendar("cme")
    today = now.date()
    if cal.is_business_day(today) and now.hour < cutoff_hour:
        return cal.prev_business_day(today)
    return cal.latest_business_day(today)


def _ingest(store, root: Path) -> bool:
    """Ingest the manual-drop folder and refresh the manifests it touched. True if any conflict."""
    from ctd.data import registry
    from ctd.data.fetch import fetch_date
    from ctd.data.inbox import ingest

    results = ingest(store, root / "inbox", registry.units_for)
    for r in results:
        print(f"ingest {r.asof} {r.source}/{r.unit}/{r.name}: {r.status}")
    touched = {(r.asof, r.source) for r in results if not r.status.startswith("conflict")}
    for asof in sorted({a for a, _ in touched}):
        specs = [registry.SOURCES[s] for a, s in touched if a == asof]
        fetch_date(asof, store, None, sources=specs, log=lambda _: None)
    return any(r.status.startswith("conflict") for r in results)


def cmd_fetch(args) -> int:
    from ctd.data import refdata, registry
    from ctd.data.fetch import fetch_date
    from ctd.data.http import RequestsHttp
    from ctd.data.store import RawStore

    root = Path(args.data_root)
    store = RawStore(root)
    _ingest(store, root)
    asof = args.asof or default_asof(datetime.now(), args.cutoff_hour)
    dates = refdata.calendar("cme").trailing_business_days(asof, CATCH_UP_DAYS) if args.catch_up else [asof]
    specs = [registry.SOURCES[s] for s in args.source] if args.source else None
    cme_auto = args.cme_auto or os.environ.get("CTD_CME_AUTO") == "1"
    http = RequestsHttp()
    gaps = []
    for d in dates:
        gaps += fetch_date(d, store, http, sources=specs, cme_auto=cme_auto)
    return _report(gaps)


def cmd_backfill(args) -> int:
    from ctd.data import registry
    from ctd.data.fetch import fetch_date
    from ctd.data.http import RequestsHttp
    from ctd.data.store import RawStore

    asof = args.asof or default_asof(datetime.now(), args.cutoff_hour)
    gaps = fetch_date(asof, RawStore(args.data_root), RequestsHttp(), sources=registry.backfill())
    return _report([g for g in gaps if g.source in {s.id for s in registry.backfill()}])


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
    f.set_defaults(func=cmd_fetch)

    b = sub.add_parser("backfill", help="one-off full histories (par curve years, NY Fed since 2018)")
    asof_args(b)
    b.set_defaults(func=cmd_backfill)

    sub.add_parser("ingest", help="move manual-drop files into the raw store").set_defaults(func=cmd_ingest)

    c = sub.add_parser("check", help="list gaps across stored manifests")
    c.add_argument("--from", dest="date_from", type=date.fromisoformat)
    c.add_argument("--to", dest="date_to", type=date.fromisoformat)
    c.set_defaults(func=cmd_check)

    r = sub.add_parser("run", help="model one contract for one date (not implemented yet)")
    r.add_argument("--contract")
    r.add_argument("--asof", type=date.fromisoformat)
    r.set_defaults(func=cmd_not_implemented)
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
