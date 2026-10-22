"""One GEDCOM date: the date, the precision its payload states, its bound.

The island's date record — the DATE payload's grammar (ABT/EST/CAL/BEF/AFT,
BET … AND …, FROM … TO …, INT …, and the qualifier-less exact form) mapped
to our shape (``{"date": …, "precision": …}``, plus ``date2`` for a
between) — and the class owns both ends of that mapping: ``from_payload``
reads a GEDCOM 7 DATE payload, ``payload`` renders one.

Its own class, not ``DatedFact``: the island keeps a payload it cannot read
(``(text)`` — the date stays empty) and DatedFact refuses an empty date.
``from_dated_fact`` is the one seam between the archive's dated fact and the
island's date record.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from tools.dated_fact import DatedFact

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

MONTH_NUMBERS = {month: number for number, month in enumerate(MONTHS, start=1)}

# ISO-8601 fixed widths and dash positions, used to tell the date forms
# apart before the GEDCOM reorder: "YYYY-MM-DD" is 10 chars with dashes at
# 4 and 7; "YYYY-MM" is 7 chars with the dash at 4.
ISO_DATE_LEN = 10  # YYYY-MM-DD
ISO_YEAR_MONTH_LEN = 7  # YYYY-MM
YEAR_MONTH_DASH = 4  # the "-" between year and month in both forms
MONTH_DAY_DASH = 7  # the "-" between month and day in the full form
DAY_MONTH_YEAR_PARTS = 3  # "D MON YYYY" splits into day, month, year

_QUALIFIER = re.compile(r"^(ABT|EST|CAL|BEF|AFT)\s+(.+)$")
_BETWEEN = re.compile(r"^BET\s+(.+)\s+AND\s+(.+)$")
# a GEDCOM period — the FROM … TO … payload, which a DATE and a residence's
# dates both use (gedcom_document.py reads a RESI's dates with this)
PERIOD_RE = re.compile(r"^FROM\s+(.+)\s+TO\s+(.+)$")
_INTERPRETED = re.compile(r"^INT\s+(.+?)\s*\((.+)\)$")

# the qualifier's precision: EST/CAL are approximations, never certainties
_QUALIFIER_PRECISIONS = {"ABT": "approx", "EST": "approx", "CAL": "approx", "BEF": "before", "AFT": "after"}


def _iso(value: str) -> str:
    """'7 JAN 1871' -> '1871-01-07'; 'JAN 1871' -> '1871-01'; '1871' stays."""
    value = value.strip()
    parts = value.split()
    if len(parts) == DAY_MONTH_YEAR_PARTS and parts[1].upper() in MONTH_NUMBERS:
        return f"{parts[2]}-{MONTH_NUMBERS[parts[1].upper()]:02d}-{int(parts[0]):02d}"
    if len(parts) == 2 and parts[0].upper() in MONTH_NUMBERS:
        return f"{parts[1]}-{MONTH_NUMBERS[parts[0].upper()]:02d}"
    return value


def _between(pattern: re.Pattern[str], payload: str) -> GedcomDate | None:
    """A BETWEEN/PERIOD payload -> the two-date between record (the two
    callers differ only in the keyword)."""
    m = pattern.match(payload)
    if m:
        return GedcomDate(date=_iso(m.group(1)), precision="between", date2=_iso(m.group(2)))
    return None


@dataclass(frozen=True)
class GedcomDate:
    """A date and the precision its payload states — ``date2`` is a
    between's upper bound, and only a between carries one."""

    date: str
    precision: str = "exact"
    date2: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> GedcomDate:
        """The date a wire record states."""
        return cls(
            date=str(raw.get("date", "")),
            precision=str(raw.get("precision", "exact")),
            date2=raw.get("date2"),
        )

    @classmethod
    def from_dated_fact(cls, fact: DatedFact) -> GedcomDate:
        """The archive's dated fact as the island's date record."""
        return cls(date=fact.date, precision=fact.precision, date2=fact.date2)

    @classmethod
    def from_payload(cls, payload: str) -> GedcomDate:
        """A GEDCOM 7 DATE payload -> our date. A payload we cannot read
        (``(text)``) keeps an empty date — the island records what the file
        says, never a date it does not state."""
        payload = payload.strip()
        qualifier = _QUALIFIER.match(payload)
        if qualifier:
            return cls(date=_iso(qualifier.group(2)), precision=_QUALIFIER_PRECISIONS[qualifier.group(1)])
        for pattern in (_BETWEEN, PERIOD_RE):
            between = _between(pattern, payload)
            if between is not None:
                return between
        interpreted = _INTERPRETED.match(payload)
        if interpreted:
            return cls(date=_iso(interpreted.group(1)), precision="approx")
        if payload.startswith("(") and payload.endswith(")"):
            return cls(date="", precision="approx")
        return cls(date=_iso(payload), precision="exact")

    def payload(self) -> str:
        """The GEDCOM 7 DATE payload this date states.

        exact -> the date as written (24 MAR 1945); month -> MON YYYY;
        year -> YYYY; approx -> ABT; before -> BEF; after -> AFT;
        between -> BET <date> AND <date2>. Granularity is the date's form,
        never uncertainty; never a fake exact date."""
        out = self.date
        if len(out) == ISO_DATE_LEN and out[YEAR_MONTH_DASH] == "-" and out[MONTH_DAY_DASH] == "-":  # YYYY-MM-DD
            out = f"{int(out[8:10])} {MONTHS[int(out[5:7]) - 1]} {out[0:4]}"
        elif len(out) == ISO_YEAR_MONTH_LEN and out[YEAR_MONTH_DASH] == "-":  # YYYY-MM
            out = f"{MONTHS[int(out[5:7]) - 1]} {out[0:4]}"
        if self.precision == "approx":
            return f"ABT {out}"
        if self.precision == "before":
            return f"BEF {out}"
        if self.precision == "after":
            return f"AFT {out}"
        if self.precision == "between":
            return f"BET {out} AND {self.date2 or ''}"
        return out

    def to_dict(self) -> dict[str, Any]:
        """The date as its wire record — ``date2`` only where the record
        states a bound."""
        out: dict[str, Any] = {"date": self.date, "precision": self.precision}
        if self.date2:
            out["date2"] = self.date2
        return out
