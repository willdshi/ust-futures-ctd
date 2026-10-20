"""Business-day calendars (pure). Holiday lists are loaded by ``ctd.data.refdata``."""

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class BusinessCalendar:
    """Weekends plus a fixed set of full-close holidays."""

    name: str
    holidays: frozenset[date]

    def is_business_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def latest_business_day(self, d: date) -> date:
        """``d`` if it is a business day, else the business day before it."""
        while not self.is_business_day(d):
            d -= timedelta(days=1)
        return d

    def prev_business_day(self, d: date) -> date:
        """The business day strictly before ``d``."""
        return self.latest_business_day(d - timedelta(days=1))

    def business_days_after(self, start: date, end: date) -> int:
        """Number of business days in ``(start, end]``; 0 if ``end <= start``."""
        n = 0
        d = start + timedelta(days=1)
        while d <= end:
            n += self.is_business_day(d)
            d += timedelta(days=1)
        return n

    def add_business_days(self, d: date, n: int) -> date:
        """Move ``n`` business days from ``d`` (``n`` may be negative)."""
        step = timedelta(days=1 if n >= 0 else -1)
        for _ in range(abs(n)):
            d += step
            while not self.is_business_day(d):
                d += step
        return d

    def trailing_business_days(self, end: date, n: int) -> list[date]:
        """The ``n`` business days ending on ``latest_business_day(end)``, oldest first."""
        last = self.latest_business_day(end)
        return [self.add_business_days(last, -k) for k in range(n - 1, -1, -1)]
