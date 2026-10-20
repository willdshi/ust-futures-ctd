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
    ]


def cme_routes():
    base = "https://www.cmegroup.com/CmeWS/mvc/Settlements/"
    expirations = json.dumps([{"productId": 317, "expirations": [{"code": "Z6"}, {"code": "F7"}]}]).encode()
    return [
        ("GET", base + "Futures/", ok("x", b'{"settlements": []}', "application/json")),
        ("GET", base + "Options/TradeDateAndExpirations/", ok("x", expirations, "application/json")),
        ("GET", base + "Options/Settlements/", ok("x", b'{"settlements": []}', "application/json")),
        ("GET", "https://www.cmegroup.com/delivery_reports/",
         ok("https://www.cmegroup.com/delivery_reports/treasury.html",
            b'<a href="/files/report.pdf">report</a> <a href="/files/report.pdf">again</a>', "text/html")),
        ("GET", "https://www.cmegroup.com/files/", ok("x", b"%PDF-1.4", "application/pdf")),
    ]
