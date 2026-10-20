from datetime import date

from fakes import FakeHttp, ok

from ctd.data import cme_tcf

LISTING = b"""-rwxr-xr-x    1 ftp      ftp         21425 Mar 22  2024 TCF.xlsx
-rwxr-xr-x    1 ftp      ftp         17809 Dec 09  2023 TCF_20231209.csv
-rw-r--r--    1 ftp      ftp         17191 Oct 16 06:30 TCF_20261016.csv
-rw-r--r--    1 ftp      ftp         29616 Oct 16 18:59 TCF_20261016.xlsx
-rw-r--r--    1 ftp      ftp         17191 Oct 19 06:31 TCF_20261019.csv
"""


def test_listing():
    http = FakeHttp([("GET", cme_tcf.BASE, ok(cme_tcf.BASE, LISTING))])
    assert cme_tcf.listing(http) == {date(2023, 12, 9): ["csv"], date(2026, 10, 16): ["csv", "xlsx"],
                                     date(2026, 10, 19): ["csv"]}


def test_fetch_names_file_by_date():
    http = FakeHttp([("GET", cme_tcf.BASE, ok("x", b"a,b\n"))])
    [f] = cme_tcf.fetch(date(2026, 10, 16), "xlsx", http)
    assert f.name == "TCF_20261016.xlsx" and http.calls[0][1] == cme_tcf.BASE + "TCF_20261016.xlsx"
