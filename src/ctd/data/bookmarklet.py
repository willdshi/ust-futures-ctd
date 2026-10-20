"""Build the CME download bookmarklet from its template and the CME reference data."""

import json
from importlib.resources import files
from urllib.parse import quote

from ctd.data import refdata

PLACEHOLDER = "/*CONFIG*/null"
SOURCES = (("treasury", "cme_fut"), ("stir", "cme_stir"))


def config() -> dict:
    products = refdata.cme_products()
    futures = [{"source": source, "code": p["code"], "id": p["product_id"]}
               for group, source in SOURCES for p in products[group]]
    return {"futures": futures, "bulletins": products.get("bulletin", [])}


def script() -> str:
    js = files("ctd.data").joinpath("cme_bookmarklet.js").read_text(encoding="utf-8")
    if PLACEHOLDER not in js:
        raise ValueError(f"bookmarklet template has no {PLACEHOLDER} placeholder")
    return js.replace(PLACEHOLDER, json.dumps(config()))


def url() -> str:
    """The ``javascript:`` URL to paste into a bookmark."""
    return "javascript:" + quote(script(), safe="")


def install_page() -> str:
    """A local HTML page with the bookmarklet as a link to drag onto the bookmarks bar."""
    return f"""<!doctype html>
<meta charset="utf-8">
<title>ctd CME bookmarklet</title>
<body style="font: 16px system-ui, sans-serif; max-width: 40em; margin: 3em auto; line-height: 1.5">
<h1>ctd CME bookmarklet</h1>
<p>Drag this link onto Chrome's bookmarks bar (Ctrl+Shift+B shows the bar):</p>
<p><a href="{url()}" style="font-size: 1.3em; padding: .4em .8em; border: 1px solid #888;
   border-radius: 6px; text-decoration: none">ctd CME download</a></p>
<p>Then open any cmegroup.com page, ideally the Daily Bulletin page, and click the bookmark.
Files go to your Downloads folder as <code>ctd_&lt;date&gt;_&lt;source&gt;_&lt;name&gt;</code>;
<code>ctd ingest</code> moves them into the data store.</p>
<p>Rebuild this page with <code>ctd bookmarklet</code> after changing
<code>src/ctd/reference/data/cme_products.toml</code>, and drag the new link over the old one.</p>
</body>
"""
