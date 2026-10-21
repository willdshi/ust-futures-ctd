"""Yahoo Finance daily bars for the Treasury futures (a cross-check on CME settlements).

Calls Yahoo's public chart endpoint, the one the yfinance library uses, with a plain request,
and stores its JSON as received. On the dates checked, a contract's daily close equals CME's
final settlement. Yahoo keeps a contract only while it's listed, and doesn't carry every listed
month, so this complements the CME files rather than replacing them.

- Daily (``yahoo_fut``): per product, the next four quarterly contracts plus the continuous
  front-month series (``ZN=F``), each for the 10 days ending on the as-of date. Overlapping short
  windows keep daily files small and cover a missed day.
- Backfill (``yahoo_fut_backfill``): the full history of the same tickers, once.

The continuous series stays on the expiring contract until its last trading day and isn't
adjusted at the roll, so never splice it into a single price history.
"""

import json
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone

from ctd.data import refdata
from ctd.data.http import FetchError, Http
from ctd.data.sources import Kind, RawFile, SourceSpec

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
MONTH_CODES = {3: "H", 6: "M", 9: "U", 12: "Z"}
CONTRACTS = 4  # quarterly contracts tried per product (CME lists 3)
LOOKBACK_DAYS = 10
HISTORY_START = datetime(2000, 1, 1, tzinfo=timezone.utc)


def products() -> list[str]:
    return [p["code"] for p in refdata.cme_products()["treasury"]]


def contract_tickers(product: str, asof: date) -> list[str]:
    """Quarterly contracts from the as-of month on, e.g. ZNZ26.CBT, ZNH27.CBT, ..."""
    out, y, m = [], asof.year, asof.month
    while len(out) < CONTRACTS:
        if m in MONTH_CODES:
            out.append(f"{product}{MONTH_CODES[m]}{y % 100:02d}.CBT")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _epoch(d: date | datetime) -> str:
    if isinstance(d, date) and not isinstance(d, datetime):
        d = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return str(int(d.timestamp()))


def _chart(http: Http, ticker: str, start: date | datetime, asof: date, name: str) -> RawFile | None:
    """One ticker's bars from ``start`` through the as-of date, or None if Yahoo doesn't carry it."""
    # Daily futures bars are stamped at the session date's midnight in New York; ending at midnight
    # UTC after the as-of date takes the as-of session and never the next one.
    params = {"interval": "1d", "period1": _epoch(start), "period2": _epoch(asof + timedelta(days=1)),
              "events": "history", "includePrePost": "false"}
    r = http.get(URL.format(ticker=ticker), params=params)
    if r.status == 404:
        return None
    r.ensure_ok()
    try:
        result = json.loads(r.content)["chart"]["result"]
    except (ValueError, KeyError, TypeError) as e:
        raise FetchError(f"unexpected Yahoo response for {ticker}: {e!r}") from e
    if not result or not result[0].get("timestamp"):
        return None
    return RawFile(name, r.content, r.url, r.status, r.content_type, params=params)


def _fetch(product: str, asof: date, http: Http, start: date | datetime, label: str) -> Iterator[RawFile]:
    found = 0
    for ticker in [*contract_tickers(product, asof), f"{product}=F"]:
        f = _chart(http, ticker, start, asof, f"{ticker}_{label}.json")
        if f is not None:
            found += 1
            yield f
    if not found:
        raise FetchError(f"Yahoo has none of the {product} tickers tried")


def fetch(asof: date, unit: str, http: Http) -> Iterator[RawFile]:
    start = asof - timedelta(days=LOOKBACK_DAYS)
    yield from _fetch(unit, asof, http, start, f"{start.isoformat()}_{asof.isoformat()}")


def fetch_history(asof: date, unit: str, http: Http) -> Iterator[RawFile]:
    yield from _fetch(unit, asof, http, HISTORY_START, f"history_{asof.isoformat()}")


SPECS = [
    SourceSpec("yahoo_fut", "Yahoo daily bars, Treasury futures contracts and front-month series (10 days)",
               Kind.DATED, "cme", units=lambda asof, cal: products(), fetch=fetch),
    SourceSpec("yahoo_fut_backfill", "Yahoo daily bars, full history of listed Treasury futures (one-off)",
               Kind.HISTORY, "cme", units=lambda asof, cal: products(), fetch=fetch_history, schedule="backfill"),
]
