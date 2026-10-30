"""The run window (design section 7, roadmap 1f.1): which contracts run on a date."""

from datetime import date, timedelta

from ctd.data import refdata
from ctd.reference.calendar import BusinessCalendar
from ctd.reference.options import rule_expiry
from ctd.reference.window import contracts_on, window_start

CME = refdata.calendar("cme")
MODELLED = ("ZN", "TN", "ZB", "UB")


def on(d: str, products=MODELLED) -> list[str]:
    return contracts_on(date.fromisoformat(d), products, CME)


def test_december_2026_window():
    assert on("2026-08-13", ("ZN",)) == ["ZNU6"]
    assert on("2026-08-14", ("ZN",)) == ["ZNU6", "ZNZ6"]  # the Friday a week before the September options expire
    assert on("2026-08-20", ("ZN",)) == ["ZNU6", "ZNZ6"]  # the day before they expire
    assert on("2026-08-21", ("ZN",)) == ["ZNZ6"]
    assert on("2026-10-30") == ["ZNZ6", "TNZ6", "ZBZ6", "UBZ6"]


def test_the_roll_to_march_2027():
    assert on("2026-11-12", ("ZN",)) == ["ZNZ6"]
    for d in ("2026-11-13", "2026-11-16", "2026-11-19"):
        assert on(d) == ["ZNZ6", "ZNH7", "TNZ6", "TNH7", "ZBZ6", "ZBH7", "UBZ6", "UBH7"]
    assert on("2026-11-20") == ["ZNH7", "TNH7", "ZBH7", "UBH7"]  # the day the December options expire
    assert on("2027-01-04", ("ZB",)) == ["ZBH7"]


def test_window_start_is_the_friday_a_week_before_or_the_next_business_day():
    assert window_start(date(2026, 11, 20), CME) == date(2026, 11, 13)
    assert window_start(date(2026, 4, 2), CME) == date(2026, 3, 27)  # Thursday expiry: the Friday of its week less 7
    closed = BusinessCalendar("test", frozenset({date(2026, 11, 13)}))
    assert window_start(date(2026, 11, 20), closed) == date(2026, 11, 16)


def test_an_expiry_exception_moves_the_window():
    def expiry_of(product, label):
        return date(2026, 11, 18) if label == "DEC26" else rule_expiry(product, label, CME).expiry

    assert contracts_on(date(2026, 11, 18), ("ZN",), CME, expiry_of) == ["ZNH7"]
    assert contracts_on(date(2026, 11, 17), ("ZN",), CME, expiry_of) == ["ZNZ6", "ZNH7"]


def test_every_business_day_runs_one_or_two_contracts_of_each_product_alike():
    d = date(2016, 1, 4)
    while d <= date(2027, 6, 30):  # inside the holiday list, with the quarter ahead
        if CME.is_business_day(d):
            by_product = {p: contracts_on(d, (p,), CME) for p in MODELLED}
            assert all(len(c) in (1, 2) for c in by_product.values()), d
            assert len({tuple(c[len(p):] for c in cs) for p, cs in by_product.items()}) == 1, d  # same months
        d += timedelta(days=1)


def test_the_default_is_the_modelled_products():
    assert refdata.contracts_on(date(2026, 10, 30)) == ["ZNZ6", "TNZ6", "ZBZ6", "UBZ6"]
    assert refdata.contracts_on(date(2026, 10, 30), ["ZF", "ZT"]) == ["ZFZ6", "ZTZ6"]
