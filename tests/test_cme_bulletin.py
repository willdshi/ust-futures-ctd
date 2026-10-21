from datetime import date

from fakes import bulletin_pdf

from ctd.data import manifest as mf
from ctd.data import registry
from ctd.data.cme_bulletin import bulletin_header, check
from ctd.data.fetch import fetch_date
from ctd.data.inbox import ingest

OCT16, OCT19 = date(2026, 10, 16), date(2026, 10, 19)


def test_reads_number_date_and_final_flag():
    assert bulletin_header(bulletin_pdf("Mon, Oct 19, 2026", 201)) == (201, OCT19, True)
    assert bulletin_header(bulletin_pdf("Mon, Oct 19, 2026", 201, final=False))[2] is False


def test_check():
    assert check(OCT19, "Section42.pdf", bulletin_pdf("Mon, Oct 19, 2026")) is None
    assert "for 2026-10-19, not 2026-10-14" in check(date(2026, 10, 14), "Section42.pdf", bulletin_pdf("Mon, Oct 19, 2026"))
    assert "not FINAL" in check(OCT19, "Section42.pdf", bulletin_pdf("Mon, Oct 19, 2026", final=False))
    assert "not a PDF" in check(OCT19, "Section42.pdf", b"<html>blocked</html>")
    assert "can't read the trade date" in check(OCT19, "Section42.pdf", bulletin_pdf("no date here"))


def test_ingest_rejects_a_bulletin_for_another_date(store, tmp_path):
    inbox = tmp_path / "inbox"
    late = inbox / "2026-10-14" / "cme_bulletin" / "Section42.pdf"   # downloaded after 10/19's was published
    good = inbox / "2026-10-16" / "cme_bulletin" / "Section42.pdf"
    for p, d in ((late, "Mon, Oct 19, 2026"), (good, "Fri, Oct 16, 2026")):
        p.parent.mkdir(parents=True)
        p.write_bytes(bulletin_pdf(d))
    results = {r.asof: r for r in ingest(store, inbox, registry.units_for, registry.validate_manual)}
    assert results[date(2026, 10, 14)].status.startswith("rejected: Section42.pdf is bulletin #200 for 2026-10-19")
    assert results[date(2026, 10, 14)].problem and late.exists()  # left in the inbox, not stored
    assert store.names(date(2026, 10, 14), "cme_bulletin", "Section42") == []
    assert results[OCT16].status == "stored" and not good.exists()
    fetch_date(date(2026, 10, 14), store, None, sources=[registry.SOURCES["cme_bulletin"]], fill_missing=False,
               today=date(2026, 10, 20), log=lambda _: None)
    unit = mf.load(store, date(2026, 10, 14))["sources"]["cme_bulletin"]["units"]["Section42"]
    assert unit["status"] == mf.MANUAL_NEEDED  # still a gap
