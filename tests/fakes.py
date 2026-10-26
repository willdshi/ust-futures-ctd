"""Fake HTTP and canned responses for offline fetcher tests."""

import json

from ctd.data.http import Response


class FakeHttp:
    """Serves canned responses by (method, URL prefix); unknown URLs get a 404. Records every call."""

    def __init__(self, routes):
        self.routes = list(routes)
        self.calls = []

    def _serve(self, method, url, payload):
        self.calls.append((method, url, payload))
        for m, prefix, resp in self.routes:
            if m == method and url.startswith(prefix):
                return resp(url, payload) if callable(resp) else resp
        return Response(url, 404, b"not found")

    def get(self, url, params=None, headers=None):
        return self._serve("GET", url, params)

    def post(self, url, data=None, headers=None):
        return self._serve("POST", url, data)


def ok(url, content: bytes, ctype="text/plain"):
    return Response(url, 200, content, {"content-type": ctype})


TD = "https://www.treasurydirect.gov/GA-FI/FedInvest/"


def gov_routes():
    """Valid-looking responses for every non-CME source."""
    return [
        ("GET", TD + "selectSecurityPriceDate", ok(TD, b'<input type="hidden" name="_csrf" value="t1" />')),
        ("POST", TD + "selectSecurityPriceDate",
         ok(TD, b'<form id="CSVFormat"><input type="hidden" name="_csrf" value="t2" /></form>')),
        ("POST", TD + "securityPriceDetail", ok(TD, b"912810XX0,MARKET BASED BOND,4.5,08/15/2046,,0,98.5,98.6\n",
                                                 "application/csv")),
        ("GET", "https://api.fiscaldata.treasury.gov/",
         lambda url, p: ok(url, json.dumps({"data": [], "meta": {"total-pages": 2}}).encode(), "application/json")),
        ("GET", "https://www.treasurydirect.gov/TA_WS/", ok("x", b'[{"cusip": "912810XX0"}]', "application/json")),
        ("GET", "https://home.treasury.gov/", ok("x", b'Date,"1 Mo"\n10/16/2026,4.12\n', "text/csv")),
        ("GET", "https://fred.stlouisfed.org/", ok("x", b"observation_date,DGS10\n2026-10-16,5.09\n", "text/csv")),
        ("GET", "https://markets.newyorkfed.org/", ok("x", b'{"refRates": []}', "application/json")),
        ("GET", "ftp://ftp.cmegroup.com/settle/TCF/TCF_", ok("x", b"CUSIP,Coupon,Maturity\n")),
        ("GET", "https://query1.finance.yahoo.com/v8/finance/chart/", yahoo),
    ]


def yahoo(url, params):
    """Yahoo chart API: June contracts aren't carried (404), everything else has one bar."""
    if "M27.CBT" in url:
        return Response(url, 404, b'{"chart":{"result":null,"error":{"code":"Not Found"}}}')
    body = {"chart": {"result": [{"meta": {}, "timestamp": [1792036800],
                                  "indicators": {"quote": [{"close": [105.25]}]}}], "error": None}}
    return ok(url, json.dumps(body).encode(), "application/json")


def make_pdf(*lines: str) -> bytes:
    """A minimal one-page PDF whose extractable text is ``lines``."""
    text = "BT /F1 10 Tf 20 750 Td 14 TL " + " ".join(f"({line}) Tj T*" for line in lines) + " ET"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
               b" /Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length %d >>\nstream\n%s\nendstream" % (len(text), text.encode()),
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, obj)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def bulletin_pdf(trade_date: str, number: int = 200, final: bool = True) -> bytes:
    """A stand-in Section 42 bulletin with the page-1 header ingest checks."""
    lines = ["10YR NOTE, 5YR NOTE, 2YR NOTE, AND 30YR BOND OPTIONS"] + (["FINAL"] if final else [])
    return make_pdf(*lines, f"PG42 BULLETIN # {number}@ 10YR NOTE OPTIONS {trade_date} PG42")
