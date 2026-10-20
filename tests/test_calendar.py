from datetime import date

from ctd.data import refdata
from ctd.data.cme_delivery import in_delivery_period

CME = refdata.calendar("cme")
SIFMA = refdata.calendar("sifma")


def test_weekends_and_holidays():
    assert not CME.is_business_day(date(2026, 10, 17))  # Saturday
    assert not CME.is_business_day(date(2026, 11, 26))  # Thanksgiving
    assert CME.is_business_day(date(2026, 10, 12))  # Columbus Day: CME open
    assert not SIFMA.is_business_day(date(2026, 10, 12))  # ... bond market closed


def test_prev_business_day_across_holiday_weekend():
    assert CME.prev_business_day(date(2026, 9, 8)) == date(2026, 9, 4)  # Labor Day Monday
    assert CME.latest_business_day(date(2026, 10, 18)) == date(2026, 10, 16)


def test_business_days_after():
    assert CME.business_days_after(date(2026, 10, 16), date(2026, 10, 16)) == 0
    assert CME.business_days_after(date(2026, 10, 16), date(2026, 10, 18)) == 0
    assert CME.business_days_after(date(2026, 10, 16), date(2026, 10, 19)) == 1
    assert CME.business_days_after(date(2026, 11, 25), date(2026, 11, 30)) == 2  # skips Thanksgiving


def test_add_and_trailing_business_days():
    assert CME.add_business_days(date(2026, 11, 25), 1) == date(2026, 11, 27)
    assert CME.add_business_days(date(2026, 11, 27), -1) == date(2026, 11, 25)
    assert CME.trailing_business_days(date(2026, 10, 18), 3) == [date(2026, 10, 14), date(2026, 10, 15),
                                                                  date(2026, 10, 16)]


def test_delivery_report_window():
    # Dec 2026: first business day Tue 1 Dec; first intention day two business days earlier, Fri 27 Nov.
    assert not in_delivery_period(date(2026, 11, 25), CME)
    assert in_delivery_period(date(2026, 11, 27), CME)
    assert in_delivery_period(date(2026, 12, 15), CME)
    # ... through the 3rd business day of January (1 Jan holiday): Wed 6 Jan 2027.
    assert in_delivery_period(date(2027, 1, 6), CME)
    assert not in_delivery_period(date(2027, 1, 7), CME)
    assert not in_delivery_period(date(2026, 10, 16), CME)
