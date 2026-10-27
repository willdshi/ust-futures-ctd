"""CME Daily Bulletin sections: the daily source of option settlements (design section 3.1).

Section 42 covers options on ZT, ZF, ZN, TN, ZB and UB, every listed expiry and strike, weeklies
included. It's a manual-only source: the bulletin is saved from cmegroup.com in a browser
(``ctd bookmarklet``) and arrives through the inbox. CME's URL always serves the latest bulletin,
so a file downloaded late for an earlier date is the wrong edition: ingest reads the trade date
and FINAL flag printed on page 1 and rejects a bulletin that doesn't match.
"""

import io
import re
from dataclasses import dataclass
from datetime import date, datetime

from ctd.data import refdata
from ctd.reference.options import underlying_month
from ctd.data.sources import Kind, SourceSpec

# Page-1 header, e.g. "PG42 BULLETIN # 201@ 10YR NOTE, ... OPTIONS Mon, Oct 19, 2026 PG42"
_HEADER = re.compile(r"BULLETIN\s*#\s*(\d+).*?((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), [A-Z][a-z]{2} \d{1,2}, \d{4})", re.S)


def _sections() -> dict[str, dict]:
    return {b["name"]: b for b in refdata.cme_products().get("bulletin", [])}


def bulletin_header(content: bytes) -> tuple[int, date, bool]:
    """(bulletin number, trade date, FINAL?) as printed on page 1."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        text = pdf.pages[0].extract_text() or ""
    m = _HEADER.search(text)
    if not m:
        raise ValueError("no bulletin number and trade date on page 1")
    return int(m[1]), datetime.strptime(m[2], "%a, %b %d, %Y").date(), "FINAL" in text


def check(asof: date, name: str, content: bytes) -> str | None:
    """Why ``content`` isn't the final bulletin for ``asof``, or None."""
    if not content.startswith(b"%PDF-"):
        return f"{name} is not a PDF"
    try:
        number, printed, final = bulletin_header(content)
    except Exception as e:
        return f"can't read the trade date in {name}: {e}"
    if printed != asof:
        return (f"{name} is bulletin #{number} for {printed}, not {asof}; CME's link serves only the latest "
                f"bulletin, so this date's bulletin can't be downloaded now. Delete the file from the inbox")
    if not final:
        return f"{name} is bulletin #{number} for {printed} but not FINAL yet; download it again later"
    return None


# --- Reading Section 42: standard option settlements -------------------------------------------
#
# Layout (one block per product, right and expiry; blocks run across page breaks):
#   10Y NOTE CALL                    product line (standard products only)
#   NOV26 10Y NOTE CALL              first expiry label, repeating the product
#   1045 61 103 39A ---- 42 - 12 .896 ---- 8366 65200 - 3156 457B 130A
#   ...                              strike, open, high, low, close, settle, change, delta,
#   TOTAL 85702 1236385 - 11839      exercises, volume, open interest, OI change, contract high/low
#   DEC26                            next expiry of the same product
# Weeklies ("10Y WK1 NOTE C") and the other products in the "ADDITIONAL" section use other
# layouts and are skipped; so is everything after "OPTIONS EOO'S" (blocks and exercises).
#
# TN is in the "ADDITIONAL" section, in one block per expiry with calls and puts mixed:
#   TN OPT
#   NOV26 TN OPT (FUTURES SETT. .00)
#   1060 ---- .54B .25A ---- .27- .13 .704 ---- ---- 819 UNCH .528B .141A
#   1060 ---- .9B .3A ---- .9+ .2 .295 ---- ---- 1847 UNCH .34B .7A
#   DEC26 (FUTURES SETT. .00)
# Premiums are points and 64ths after a dot (".218" = 2 + 18/64), the sign of the change is stuck
# to the settlement (".27-"), deltas are unsigned, and a strike's call and put come in either order
# (NOV26 call first, DEC26 put first on 2026-10-21). ``tn_rights`` works out which is which.

_STANDARD = {"10Y NOTE": "ZN", "5Y NOTE": "ZF", "2Y NOTE": "ZT", "30Y BOND": "ZB", "ULTRA T-BND": "UB"}
_PRODUCT_LINE = re.compile(r"^(10Y NOTE|5Y NOTE|2Y NOTE|30Y BOND|ULTRA T-BND) (CALL|PUT|C|P)$")
_EXPIRY_LINE = re.compile(r"^((?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2})(?: (.+))?$")
_ROW = re.compile(r"^\d{3,4} (?:-{4}|\.?\d)")  # not "2026 DAILY INFORMATION BULLETIN"; TN prices: ".2"
_TOTAL = re.compile(r"^TOTAL (\S+) (\S+)")
_QUARTERS = {"0": 0.0, "2": 0.25, "5": 0.5, "7": 0.75}
_EIGHTHS = {"0": 0, "1": 1, "2": 2, "3": 3, "5": 4, "6": 5, "7": 6, "8": 7}
_HALF_64THS = ("ZT", "ZF")  # premiums in halves of 64ths ("6035" = 6-03.5); others in 64ths ("508" = 5-08)


@dataclass(frozen=True)
class OptionSettle:
    product: str  # futures product: "ZN"
    label: str  # option month: "DEC26"
    right: str  # "C" or "P"
    strike: float
    settle: float | None  # None for a cabinet (below one tick) settlement
    delta: float | None
    volume: int
    open_interest: int

    @property
    def cabinet(self) -> bool:
        return self.settle is None


def _int(token: str) -> int:
    return 0 if token.startswith("-") else int(token.rstrip("ABNPR#*").replace(",", ""))


def decode_strike(product: str, code: str) -> float:
    """``1047`` → 104.75 (ZN, ZF, ZB, UB: last digit 0/2/5/7 is the quarter); ZT ``1013`` → 101.375 (eighths)."""
    if product == "ZT":
        return int(code[:-1]) + _EIGHTHS[code[-1]] / 8
    return int(code[:-1]) + _QUARTERS[code[-1]]


def decode_premium(product: str, code: str) -> float:
    """Points and 64ths: ``508`` → 5 + 8/64; ZT and ZF in halves, ``6035`` → 6 + 3.5/64."""
    digits = code.rstrip("ABNPR#*")
    if product in _HALF_64THS:
        return int(digits[:-3] or 0) + int(digits[-3:]) / 640
    return int(digits[:-2] or 0) + int(digits[-2:]) / 64


def _row(product: str, label: str, right: str, line: str) -> tuple[OptionSettle, bool]:
    """The row's settlement, and False where none is printed ("----": an expiring option that
    settled worthless on its last trading day, the change being its whole prior premium)."""
    t = line.split()
    i = 6 + (2 if t[6] in "+-" else 1)  # change: "- 13", "+ NEW", "UNCH" or "----"
    delta, volume, oi = t[i], t[i + 2], t[i + 3]
    settle = None if t[5] in ("CAB", "----") else decode_premium(product, t[5])
    return (OptionSettle(product, label, right, decode_strike(product, t[0]), settle,
                         None if delta.startswith("-") else float(delta), _int(volume), _int(oi)),
            t[5] != "----")


@dataclass(frozen=True)
class _TNRow:
    strike: float
    settle: float | None  # None for a cabinet
    priced: bool  # False where no settlement is printed at all ("----")
    delta: float | None
    volume: int
    open_interest: int


def _tn_row(line: str) -> _TNRow:
    t = line.split()
    settle = t[5].rstrip("+-")  # "----", or "-----" with the change's sign attached, is no settlement
    delta, volume, oi = t[7], t[9], t[10]
    price = None if settle in ("CAB", "") else decode_premium("TN", settle[1:])
    return _TNRow(decode_strike("TN", t[0]), price, settle != "",
                  None if delta.startswith("-") else float(delta), _int(volume), _int(oi))


TN_MATCH = 2 / 64  # points: how close a strike's call-put gap must put the futures price to the chain's


def tn_forward(rows: list[_TNRow]) -> float | None:
    """The futures price a TN chain implies. At a strike with a call and a put both priced, call
    minus put is futures minus strike, so the futures is the strike plus or minus their gap; one
    value fits every such strike. None without such a strike."""
    by_strike: dict[float, list[_TNRow]] = {}
    for r in rows:
        by_strike.setdefault(r.strike, []).append(r)
    candidates = []
    for k, pair in by_strike.items():
        if len(pair) == 2 and pair[0].settle is not None and pair[1].settle is not None:
            gap = abs(pair[0].settle - pair[1].settle)
            candidates.append((k + gap, k - gap))
    if not candidates:
        return None
    values = [v for c in candidates for v in c]
    best = max(values, key=lambda v: sum(any(abs(v - x) <= TN_MATCH for x in c) for c in candidates))
    support = sorted(x for c in candidates for x in c if abs(x - best) <= TN_MATCH)
    return support[len(support) // 2]


def tn_rights(rows: list[_TNRow], forward: float) -> list[str]:
    """Call or put for each row of a TN chain, given the futures price it implies. Where a strike
    has both, the dearer is the call below the futures price and the put above it, and a cabinet
    is the out-of-the-money one. A lone row is in the money if its delta is over a half."""
    out = [""] * len(rows)
    by_strike: dict[float, list[int]] = {}
    for i, r in enumerate(rows):
        by_strike.setdefault(r.strike, []).append(i)
    for k, idx in by_strike.items():
        itm = "C" if k < forward else "P"
        otm = "P" if itm == "C" else "C"
        if len(idx) == 2:
            a, b = rows[idx[0]], rows[idx[1]]
            if a.settle is None or b.settle is None:
                cheap = idx[0] if a.settle is None else idx[1]
            else:
                cheap = idx[0] if a.settle <= b.settle else idx[1]
            for i in idx:
                out[i] = otm if i == cheap else itm
        else:
            r = rows[idx[0]]
            out[idx[0]] = itm if r.settle is not None and r.delta is not None and r.delta > 0.5 else otm
    return out


def _tn_settles(label: str, rows: list[_TNRow], forward: float) -> list[OptionSettle]:
    rights = tn_rights(rows, forward)
    out = [OptionSettle("TN", label, right, r.strike, r.settle, r.delta, r.volume, r.open_interest)
           for r, right in zip(rows, rights) if r.priced]
    for right, sign in (("C", 1), ("P", -1)):
        prices = sorted((o.strike, o.settle) for o in out if o.right == right and o.settle is not None)
        if any(sign * (b - a) > 1 / 64 + 1e-9 for (_, a), (_, b) in zip(prices, prices[1:])):
            raise ValueError(f"TN {label}: calls and puts can't be told apart (futures at {forward:.4f})")
    return sorted(out, key=lambda o: (o.right, o.strike))


def parse_options(text: str) -> list[OptionSettle]:
    """Every standard (quarterly and serial) option settlement in Section 42's extracted text.

    Each block is checked: strikes strictly increasing (TN: at most a call and a put per strike),
    and its volume and open interest equal its TOTAL line. A block that fails raises ValueError
    (the layout may have changed). A row with no settlement printed ("----", expiring options
    on their last trading day) counts toward the TOTAL but isn't returned; so does a TN chain
    with no deltas printed (expiry day), whose calls and puts can't be told apart. TN's rights come from put-call parity (``tn_rights``), with the
    futures price implied by the chain, or by another chain on the same futures where it has no
    strike priced both ways (FEB27 next to JAN27); calls must then fall and puts rise with strike,
    or ValueError.
    """
    out: list[OptionSettle] = []
    product = right = label = header = None
    block: list[OptionSettle] = []
    tn: list[tuple[str, list[_TNRow]]] = []
    tn_block: list[_TNRow] = []
    for line in (s.strip() for s in text.splitlines()):
        if line.startswith("OPTIONS EOO'S"):
            break
        if line.endswith(("CALLS", "PUTS", "OPTIONS")):  # section title: a new product follows
            product = label = None
        elif line == "TN OPT":
            product, right, header, label = "TN", None, line, None
        elif line.endswith(" OPT"):  # another product in the ADDITIONAL section (TNW, GBO, ...)
            product = label = None
        elif m := _PRODUCT_LINE.match(line):
            product, right, header, label = _STANDARD[m[1]], m[2][0], line, None
        elif m := _EXPIRY_LINE.match(line):
            tn_expiry = product == "TN" and (m[2] or "").startswith(("TN OPT", "(FUTURES SETT"))
            if m[2] and m[2] != header and not tn_expiry:  # an expiry of something else (weekly, ...)
                product = None
            label, block, tn_block = m[1], [], []
        elif _ROW.match(line) and product == "TN" and label:
            row = _tn_row(line)
            if tn_block and (row.strike < tn_block[-1].strike
                             or sum(r.strike == row.strike for r in tn_block) >= 2):
                raise ValueError(f"TN {label}: strikes out of order at {line!r}")
            tn_block.append(row)
        elif _ROW.match(line) and product and label:
            row = _row(product, label, right, line)
            if block and row[0].strike <= block[-1][0].strike:
                raise ValueError(f"{product} {label} {right}: strikes not increasing at {line!r}")
            block.append(row)
        elif (m := _TOTAL.match(line)) and product and label:
            volume, oi = _int(m[1]), _int(m[2])
            rows = tn_block if product == "TN" else [r for r, _ in block]
            if (sum(r.volume for r in rows), sum(r.open_interest for r in rows)) != (volume, oi):
                name = f"{product} {label}" + (f" {right}" if right else "")
                raise ValueError(f"{name}: rows don't add up to {line!r}")
            if product != "TN":
                out += [r for r, priced in block if priced]
            elif any(r.delta is not None for r in tn_block):  # none on expiry day
                tn.append((label, tn_block))
            label, block, tn_block = None, [], []
    forwards: dict = {}
    for lab, rows in tn:
        if (f := tn_forward(rows)) is not None:
            forwards.setdefault(underlying_month(lab), []).append(f)
    for lab, rows in tn:
        f = tn_forward(rows)
        if f is None:
            same = sorted(forwards.get(underlying_month(lab), []))
            if not same:
                raise ValueError(f"TN {lab}: no strike priced both ways and no other chain on its futures")
            f = same[len(same) // 2]
        out += _tn_settles(lab, rows, f)
    return out


_LAST_TRADE = {"10YR NOTE OPT": "ZN", "5YR NOTE OPT": "ZF", "2YR NOTE OPT": "ZT", "30YR BOND OPT": "ZB",
               "ULTRA T-BOND OPT": "UB"}


def last_trade_dates(text: str) -> dict[tuple[str, str], date]:
    """``(product, label) -> last trade date`` from the table CME prints on page 1."""
    out = {}
    labels: list[str] = []
    for line in text.splitlines():
        if line.startswith("EXPIRATION:"):
            labels = line.split()[1:]
            continue
        for name, product in _LAST_TRADE.items():
            if line.startswith(name + " ") and labels:
                for label, mmdd in zip(labels, line[len(name):].split()):
                    month, day = int(mmdd[:2]), int(mmdd[3:])
                    year = 2000 + int(label[3:]) - (month > _MONTHS.index(label[:3]) + 1)
                    out[(product, label)] = date(year, month, day)
    return out


_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def text(content: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def read(store, asof: date) -> tuple[list[OptionSettle], dict[tuple[str, str], date]]:
    """``asof``'s standard option settlements and page 1's last trade dates, from the stored Section 42."""
    content = store.read(asof, "cme_bulletin", "Section42", "Section42.pdf")
    _, printed, _ = bulletin_header(content)
    if printed != asof:
        raise ValueError(f"stored Section 42 is for {printed}, not {asof}")
    t = text(content)
    return parse_options(t), last_trade_dates(t)


def read_options(store, asof: date) -> list[OptionSettle]:
    """``asof``'s standard option settlements from the stored Section 42 bulletin."""
    return read(store, asof)[0]


SPECS = [
    SourceSpec("cme_bulletin", "CME Daily Bulletin sections (Section 42: Treasury options)", Kind.DATED, "cme",
               units=lambda asof, cal: list(_sections()), fetch=None, validate=check, schedule="occasional"),
]
