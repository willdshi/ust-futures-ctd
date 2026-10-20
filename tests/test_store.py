import gzip
import hashlib
from datetime import date

ASOF = date(2026, 10, 16)


def test_round_trip_and_meta(store):
    assert store.write(ASOF, "fred", "DGS10", "DGS10.csv", b"a,b\n1,2\n", {"origin": "auto", "url": "u"})
    assert store.read(ASOF, "fred", "DGS10", "DGS10.csv") == b"a,b\n1,2\n"
    meta = store.meta(ASOF, "fred", "DGS10", "DGS10.csv")
    assert meta["sha256"] == hashlib.sha256(b"a,b\n1,2\n").hexdigest()
    assert meta["bytes"] == 8 and meta["url"] == "u" and meta["origin"] == "auto"
    assert store.names(ASOF, "fred", "DGS10") == ["DGS10.csv"]
    assert store.units(ASOF, "fred") == ["DGS10"]
    assert store.asofs() == [ASOF]


def test_never_overwrites(store):
    store.write(ASOF, "s", "u", "f.csv", b"first", {"origin": "auto"})
    assert not store.write(ASOF, "s", "u", "f.csv", b"second", {"origin": "manual"})
    assert store.read(ASOF, "s", "u", "f.csv") == b"first"
    assert store.meta(ASOF, "s", "u", "f.csv")["origin"] == "auto"
    assert not list(store.unit_dir(ASOF, "s", "u").glob("*.tmp"))


def test_compression_is_deterministic(store):
    store.write(ASOF, "s", "u", "f.csv", b"x" * 1000, {})
    gz = (store.unit_dir(ASOF, "s", "u") / "f.csv.gz").read_bytes()
    assert gz == gzip.compress(b"x" * 1000, mtime=0)
