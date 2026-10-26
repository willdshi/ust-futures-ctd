"""NY Fed reference rates (SOFR, TGCR, BGCR, EFFR).

A rate for day D is published the next business morning, so the daily pull asks for the
two weeks ending on the as-of date: the file then holds every rate known by that evening. A run
for D still uses D's own rate, from a later file (``read_known``).
"""

import json
from collections.abc import Iterator
from datetime import date, timedelta

from ctd.data.http import FetchError, Http
from ctd.data.sources import Kind, RawFile, SourceSpec

URL = "https://markets.newyorkfed.org/api/rates/{group}/{rate}/search.json"
RATES = {"sofr": "secured", "tgcr": "secured", "bgcr": "secured", "effr": "unsecured"}
LOOKBACK_DAYS = 14
HISTORY_START = date(2018, 4, 2)  # first SOFR publication


def _range_file(rate: str, start: date, end: date, http: Http) -> RawFile:
    params = {"startDate": start.isoformat(), "endDate": end.isoformat()}
    r = http.get(URL.format(group=RATES[rate], rate=rate), params=params).ensure_ok()
    try:
        json.loads(r.content)["refRates"]
    except (ValueError, KeyError, TypeError) as e:
        raise FetchError(f"NY Fed {rate}: unexpected response: {e!r}") from e
    return RawFile(f"{rate}_{start.isoformat()}_{end.isoformat()}.json", r.content, r.url, r.status,
                   r.content_type, params=params)


def fetch(asof: date, unit: str, http: Http) -> Iterator[RawFile]:
    yield _range_file(unit, asof - timedelta(days=LOOKBACK_DAYS), asof, http)


def fetch_history(asof: date, unit: str, http: Http) -> Iterator[RawFile]:
    yield _range_file(unit, HISTORY_START, asof, http)


def parse(content: bytes) -> dict[date, float]:
    """Effective date -> rate as a decimal (3.88% -> 0.0388)."""
    return {date.fromisoformat(r["effectiveDate"]): r["percentRate"] / 100 for r in json.loads(content)["refRates"]}


def read_known(store, asof: date, since: date, rate: str = "sofr") -> tuple[dict[date, float], list[tuple]]:
    """Every ``rate`` fixing dated ``since`` to ``asof``, from any stored file, and the files read as
    (as-of date, source, name).

    Data dated on or before the as-of date counts, whenever it was pulled (docs/decisions.md, Which
    data a run uses): the fixing for ``asof`` itself is published the next morning, so it comes from
    a later as-of date's file, and a daily file holds two weeks, so the month to date needs earlier
    ones. Where files overlap, the newest pull wins."""
    lo, hi = since - timedelta(days=LOOKBACK_DAYS), asof + timedelta(days=LOOKBACK_DAYS)
    rates, files = {}, []
    for d in sorted((d for d in store.asofs() if lo <= d <= hi), reverse=True):
        for source in ("nyfed_rates", "nyfed_rates_backfill"):
            for name in store.names(d, source, rate):
                rates.update({k: v for k, v in parse(store.read(d, source, rate, name)).items()
                              if k not in rates and since <= k <= asof})
                files.append((d, source, name))
    return rates, files


def read_latest(store, asof: date, rate: str = "sofr") -> tuple[date, float]:
    """The latest ``rate`` dated on or before ``asof`` (``read_known``): ``asof``'s own once the next
    morning's file is stored, else the previous business day's."""
    rates, _ = read_known(store, asof, asof - timedelta(days=LOOKBACK_DAYS), rate)
    if not rates:
        raise ValueError(f"no {rate} stored for {asof}")
    return max(rates), rates[max(rates)]


SPECS = [
    SourceSpec("nyfed_rates", "NY Fed SOFR, TGCR, BGCR, EFFR (trailing two weeks)", Kind.DATED, "cme",
               units=lambda asof, cal: list(RATES), fetch=fetch),
    SourceSpec("nyfed_rates_backfill", "NY Fed rates since April 2018 (one-off)", Kind.DATED, "cme",
               units=lambda asof, cal: list(RATES), fetch=fetch_history, schedule="backfill"),
]
