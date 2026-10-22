"""The settings a dateparser parse runs under.

Every parse in the capture flow — an asserted date value, the stability probe,
a suggestion's year — hands dateparser one settings record: the archive's
locale date order for ambiguous numerics, the past bias, and the day-of-month
rule where a day must be invented. The dict this class serialises to is exactly
the one dateparser takes, so the reading of a date stays the library's own
behaviour, never a hand-rolled parser (docs/coding-standards.md).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any


def locale_date_order() -> str:
    """The archive's date order for ambiguous numerics. Default DMY (the
    family is British); LOFT_LOCALE (e.g. en_US) overrides — locale is
    respected when reading dates (docs/PRD/MEMORIES.md)."""
    locale = os.environ.get("LOFT_LOCALE", "en_GB")
    return "MDY" if locale.lower().startswith("en_us") else "DMY"


@dataclass(frozen=True)
class DateSettings:
    """One parse's settings — the locale date order, the day-of-month rule
    (None where the parse only reads a year, so no day is invented), the past
    bias, and the base moment a relative phrase is read against."""

    date_order: str
    prefer_day_of_month: str | None = None
    prefer_dates_from: str = "past"
    relative_base: datetime | None = None

    @classmethod
    def archive(cls) -> DateSettings:
        """The archive's own parse settings: its locale's date order, the first
        of the month where a day must be invented, and the past bias."""
        return cls(date_order=locale_date_order(), prefer_day_of_month="first")

    def for_a_year(self) -> DateSettings:
        """The same settings without the day-of-month rule — a parse that only
        reads the year never invents a day."""
        return replace(self, prefer_day_of_month=None)

    def at(self, base: datetime) -> DateSettings:
        """The same settings pinned to a base moment — a phrase's parts are
        then its own, never the base's (the stability probe)."""
        return replace(self, relative_base=base)

    def to_dict(self) -> dict[str, Any]:
        """The settings as the dict dateparser takes."""
        settings: dict[str, Any] = {"DATE_ORDER": self.date_order}
        if self.prefer_day_of_month is not None:
            settings["PREFER_DAY_OF_MONTH"] = self.prefer_day_of_month
        settings["PREFER_DATES_FROM"] = self.prefer_dates_from
        if self.relative_base is not None:
            settings["RELATIVE_BASE"] = self.relative_base
        return settings
