import shutil
import subprocess
from urllib.parse import unquote

import pytest

from ctd.cli import main
from ctd.data import bookmarklet


def test_config_has_every_product_with_an_id():
    futures = bookmarklet.config()["futures"]
    assert {f["code"] for f in futures} == {"ZT", "ZF", "ZN", "TN", "ZB", "UB", "SR1", "SR3", "ZQ"}
    assert all(isinstance(f["id"], int) for f in futures)
    assert {f["source"] for f in futures} == {"cme_fut", "cme_stir"}
    assert bookmarklet.config()["bulletins"][0]["source"] == "cme_bulletin"


def test_url_round_trips_to_script():
    url = bookmarklet.url()
    assert url.startswith("javascript:") and bookmarklet.PLACEHOLDER not in unquote(url)
    assert unquote(url[len("javascript:"):]) == bookmarklet.script()
    assert not any(c in url for c in "\"'<> \n")  # safe inside an HTML href


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_script_parses(tmp_path):
    js = tmp_path / "b.js"
    js.write_text(bookmarklet.script(), encoding="utf-8")
    subprocess.run(["node", "--check", str(js)], check=True)


def test_cli_writes_install_page(tmp_path):
    assert main(["--data-root", str(tmp_path), "bookmarklet"]) == 0
    assert bookmarklet.url() in (tmp_path / "cme_bookmarklet.html").read_text(encoding="utf-8")
