"""A dated fact: a date and the precision its evidence supports.

The date-precision vocabulary (GEDCOM alignment): exact / month / year
express granularity (a year-only date is exact at year granularity, never
uncertainty); approx = about; before / after / between carry the bounds
the artifacts actually state ("Aft. 1881", "Bet. 1880-1881"). A
``between`` fact carries the upper bound in ``date2``.

The fact is the archive's one dated-fact record — a person's dob/dod, a
relationship's date, a reference's involvement date — and its wire shape
(``{"date": …, "precision": …}``, plus ``date2`` for a bound) is this
class's dict.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from typing import Any

# The date-precision vocabulary (GEDCOM alignment): exact /
# month / year express granularity (a year-only date is exact at year
# granularity, never uncertainty); approx = about; before / after / between
# carry bounds the artifacts actually state ("Aft. 1881", "Bet. 1880-1881").
# ``between`` carries the upper bound in date2.
PRECISIONS = frozenset({"exact", "month", "year", "approx", "before", "after", "between"})

MONTHS_IN_YEAR = 12  # the date-form validation's month bound

_DATE_RE = re.compile(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?")


def viable_date(value: str) -> bool:
    """A real calendar date in the archive's flexible forms: YYYY,
    YYYY-MM, or YYYY-MM-DD with valid month and day — 2026-99-99 and
    2026-02-31 are not dates. The granularity stays the precision's
    business; the form just has to be true."""
    m = _DATE_RE.fullmatch(value)
    if not m:
        return False
    month, day = m.group(2), m.group(3)  # lucidlint: ignore magic-number fixed regex capture-group
    # indices — (\d{4})(?:-(\d{2})(?:-(\d{2}))?)?
    if month and not 1 <= int(month) <= MONTHS_IN_YEAR:
        return False
    if day:
        try:
            datetime.date(int(m.group(1)), int(month), int(day))
        except ValueError:
            return False
    return True


@dataclass(frozen=True)
class DatedFact:
    """A date and the precision it can prove. ``date2`` is the upper bound
    of a ``between`` fact and is carried only then."""

    date: str
    precision: str
    date2: str | None = None

    def __post_init__(self) -> None:
        if not self.date:
            raise ValueError("needs a date")
        if not viable_date(self.date):
            raise ValueError(f"has an impossible date {self.date!r}")
        if self.precision not in PRECISIONS:
            raise ValueError(f"has unknown precision {self.precision!r}")
        if self.precision == "between":
            if not self.date2:
                raise ValueError("with precision 'between' needs date2")
            if not viable_date(self.date2):
                raise ValueError(f"has an impossible date {self.date2!r}")
        elif self.date2:
            # a bound that no precision states is not a bound — the wire
            # never carries one (the exact-date rule)
            object.__setattr__(self, "date2", None)

    @classmethod
    def from_dict(cls, raw: dict[str, Any], label: str = "date") -> DatedFact:
        date_str = str(raw.get("date", "")).strip()
        if not date_str:
            raise ValueError(f"{label} needs a date")
        if not viable_date(date_str):
            raise ValueError(f"{label} has an impossible date {date_str!r}")
        precision = str(raw.get("precision", "exact"))
        if precision not in PRECISIONS:
            raise ValueError(f"{label} has unknown precision {precision!r}")
        if precision == "between":
            date2 = str(raw.get("date2", "")).strip()
            if not date2:
                raise ValueError(f"{label} with precision 'between' needs date2")
            if not viable_date(date2):
                raise ValueError(f"{label} has an impossible date {date2!r}")
            return cls(date=date_str, precision=precision, date2=date2)
        return cls(date=date_str, precision=precision)

    def to_dict(self) -> dict[str, Any]:
        """The fact as its wire record — ``date2`` only where the precision
        states a bound."""
        out: dict[str, Any] = {"date": self.date, "precision": self.precision}
        if self.precision == "between" and self.date2:
            out["date2"] = self.date2
        return out
