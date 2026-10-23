"""What a data source is, as far as the collector is concerned."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Literal

from ctd.data.http import Http
from ctd.reference.calendar import BusinessCalendar


class Kind(StrEnum):
    DATED = "dated"        # the request names the as-of date
    HISTORY = "history"    # the response is the full history to date (backfillable)
    SNAPSHOT = "snapshot"  # current state only; can't be recovered for a past date


@dataclass(frozen=True)
class RawFile:
    """One downloaded file, exactly as received."""

    name: str
    content: bytes
    url: str
    status: int = 200
    content_type: str = ""
    method: str = "GET"
    params: dict | None = None


@dataclass(frozen=True)
class SourceSpec:
    """A source is split into units (a product, a series, ...); each unit is fetched and tracked separately.

    ``window`` is the recovery window: the most business days after the as-of date that the
    source still serves that date (None = no limit). ``cme`` sources are only fetched
    automatically when the CME switch is on; otherwise they come through the manual-drop folder.
    ``schedule``: "daily" sources are expected every business day and flagged when missing;
    "backfill" ones run only via ``ctd backfill``; "occasional" ones only when asked for
    (``ctd fetch --source ...``) or dropped in the inbox, and are never flagged as gaps.
    ``validate(asof, name, content)``, if set, checks a manual file before ingest stores it and
    returns the reason to reject it (e.g. a bulletin printed for another date), or None.
    ``provisional(content)``, if set, marks the **one exception to never overwriting a stored
    file**. It is only for sources that can be pulled again for any past date (so nothing is
    lost by replacing), whose files for a date are completed after the first pull. A stored file
    it returns True for is fetched again on later runs and replaced by a download it returns
    False for (``RawStore.replace``); a provisional or broken download never replaces anything.
    """

    id: str
    description: str
    kind: Kind
    calendar: str
    units: Callable[[date, BusinessCalendar], list[str]]
    fetch: Callable[[date, str, Http], Iterator[RawFile]]
    window: int | None = None
    cme: bool = False
    schedule: Literal["daily", "backfill", "occasional"] = "daily"
    validate: Callable[[date, str, bytes], str | None] | None = None
    provisional: Callable[[bytes], bool] | None = None


def mmddyyyy(d: date) -> str:
    return d.strftime("%m/%d/%Y")
