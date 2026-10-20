"""CME settlements via cmegroup.com's settlement web services: Treasury futures, options on them,
and SOFR / fed funds futures.

Only used when the CME switch is on (check CME's terms of use first). The endpoints and the
shape of the option-expiry response are unverified until the first live run; every response
body is stored as received either way. CME shows 5 trailing business days.
"""

import json
from collections.abc import Iterator
from datetime import date

from ctd.data import refdata
from ctd.data.http import FetchError, Http
from ctd.data.sources import Kind, RawFile, SourceSpec, mmddyyyy

BASE = "https://www.cmegroup.com/CmeWS/mvc/Settlements"
HEADERS = {"Accept": "application/json, text/plain, */*", "Referer": "https://www.cmegroup.com/"}
WINDOW = 4  # 5 trailing business days, including the as-of date


def _products(group: str) -> dict[str, dict]:
    return {p["code"]: p for p in refdata.cme_products()[group]}


def _product_id(group: str, code: str) -> int:
    pid = _products(group)[code].get("product_id")
    if pid is None:
        raise FetchError(f"no CME product_id configured for {code} (reference/data/cme_products.toml)")
    return pid


def _get_json(http: Http, url: str, params: dict) -> RawFile:
    r = http.get(url, params=params, headers=HEADERS).ensure_ok()
    try:
        json.loads(r.content)
    except ValueError as e:
        raise FetchError(f"CME returned non-JSON from {r.url} (blocked?)") from e
    return RawFile("", r.content, r.url, r.status, r.content_type, params=params)


def _futures(group: str):
    def fetch(asof: date, unit: str, http: Http) -> Iterator[RawFile]:
        pid = _product_id(group, unit)
        params = {"strategy": "DEFAULT", "tradeDate": mmddyyyy(asof), "pageSize": "500"}
        f = _get_json(http, f"{BASE}/Futures/Settlements/{pid}/FUT", params)
        yield RawFile(f"{unit}_FUT_{asof.isoformat()}.json", f.content, f.url, f.status, f.content_type,
                      params=params)
    return fetch


def option_series(doc) -> list[tuple[int, str]]:
    """(option product id, expiry code) pairs from CME's TradeDateAndExpirations response.

    Assumed shape: a list of option products, each with ``productId`` and ``expirations``,
    each expiration carrying its code as ``code`` or under ``expiration.code``.
    """
    out = []
    for product in doc if isinstance(doc, list) else []:
        pid = product.get("productId")
        for exp in product.get("expirations") or []:
            code = exp.get("code") or (exp.get("expiration") or {}).get("code")
            if pid is not None and code:
                out.append((int(pid), str(code)))
    return out


def fetch_options(asof: date, unit: str, http: Http) -> Iterator[RawFile]:
    fut_id = _product_id("treasury", unit)
    exp = _get_json(http, f"{BASE}/Options/TradeDateAndExpirations/{fut_id}", {})
    yield RawFile(f"{unit}_expirations_{asof.isoformat()}.json", exp.content, exp.url, exp.status,
                  exp.content_type)
    series = option_series(json.loads(exp.content))
    if not series:
        raise FetchError(f"no option series found in CME expirations for {unit}; check the response shape")
    for opt_id, code in series:
        params = {"optionProductId": str(opt_id), "monthYear": code, "strategy": "DEFAULT",
                  "tradeDate": mmddyyyy(asof), "pageSize": "1000"}
        f = _get_json(http, f"{BASE}/Options/Settlements/{fut_id}/OOF", params)
        yield RawFile(f"{unit}_OOF_{opt_id}_{code}_{asof.isoformat()}.json", f.content, f.url, f.status,
                      f.content_type, params=params)


SPECS = [
    SourceSpec("cme_fut", "CME Treasury futures settlements, all six contracts, all months", Kind.DATED,
               "cme", units=lambda asof, cal: list(_products("treasury")), fetch=_futures("treasury"),
               window=WINDOW, cme=True),
    SourceSpec("cme_opt", "CME options on Treasury futures, every expiry and strike", Kind.DATED, "cme",
               units=lambda asof, cal: list(_products("treasury")), fetch=fetch_options,
               window=WINDOW, cme=True),
    SourceSpec("cme_stir", "CME 1M SOFR, 3M SOFR and 30-day fed funds futures settlements", Kind.DATED,
               "cme", units=lambda asof, cal: list(_products("stir")), fetch=_futures("stir"),
               window=WINDOW, cme=True),
]
