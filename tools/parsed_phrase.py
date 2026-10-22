"""A date phrase the library resolved: the value's shape and what it proves.

No hand-rolled date parsers (docs/coding-standards.md): the model asserts *what*
a phrase is, dateparser reads it against the archive's locale, and this class
holds the parse — the phrase and the moment it resolved to, the pair every
demotion rule works on. The rules answer one question: what precision does the
VALUE's own shape support? An over-claimed "exact" on a bare year must never pin
an invented day (PRD §6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import dateparser

from tools.date_settings import DateSettings
from tools.dated_fact import DatedFact

# The precision a model-asserted date may CLAIM — the words' own granularity.
# The archive's dated-fact vocabulary (tools/dated_fact.py) adds the bounds the
# artifacts state (before/after/between); a claim never carries one.
CLAIMED_PRECISIONS = ("exact", "month", "year", "approx")

_HEDGE_RE = re.compile(r"^(?:around|circa|about)\s+", flags=re.IGNORECASE)
_SEASON_RE = re.compile(r"^(?:the\s+)?(?:summer|spring|autumn|fall|winter)\s+of\s+", flags=re.IGNORECASE)
_DECADE_RE = re.compile(r"(?:19|20)\d{2}s", flags=re.IGNORECASE)
_ISO_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_ISO_MONTH_RE = re.compile(r"\d{4}-\d{2}")
_ISO_YEAR_RE = re.compile(r"\d{4}")

# Far enough back that a bare year cannot borrow its month/day from the base.
_FAR_BASE_YEAR = 1600
_FAR_BASE = datetime(_FAR_BASE_YEAR, month=1, day=1)


@dataclass(frozen=True)
class ParsedPhrase:
    """A phrase the library resolved — the phrase itself and the moment it
    named. The phrase decides what the parse proves: an ISO shape names its own
    parts; anything else is probed against a far-off base."""

    phrase: str
    parsed: datetime

    @classmethod
    def of(cls, value: Any) -> ParsedPhrase | None:
        """The phrase a model-asserted date value states, resolved by the real
        parser: dateparser parses the asserted VALUE (locale-aware, incomplete
        forms allowed) and the verbatim text is provenance, never parsed. None
        when the parser cannot make sense of it — a person resolves."""
        if not isinstance(value, str) or not value.strip():
            return None
        # a hedge word ("around/circa/about 1965") is token stripping, not a
        # date parser
        phrase = _HEDGE_RE.sub("", value.strip())
        # ISO shapes are unambiguous — the stdlib parses them (locale-free);
        # anything else ("15/09/1981", "July 1979", "1979") goes to the
        # locale-aware parser
        try:
            if _ISO_DAY_RE.fullmatch(phrase):
                parsed = datetime.strptime(phrase, "%Y-%m-%d")
            elif _ISO_MONTH_RE.fullmatch(phrase):
                parsed = datetime.strptime(phrase, "%Y-%m")
            elif _ISO_YEAR_RE.fullmatch(phrase):
                parsed = datetime.strptime(phrase, "%Y")
            else:
                parsed = dateparser.parse(phrase, settings=DateSettings.archive().to_dict())
        except (ValueError, OverflowError):
            return None
        if parsed is None:
            return None
        return cls(phrase=phrase, parsed=parsed)

    @classmethod
    def year_of(cls, phrase: str) -> int | None:
        """The year a phrase names, via the real parser — never a hand-rolled
        date parser. A phrase the parser cannot date is None (a suggestion is
        kept, not dropped). Only two bounded token strips precede the parser: a
        hedge word ("around/about/circa") and a season lead-in ("the summer of
        1960" -> "1960"); a bare decade token ("the 1960s") the parser mis-reads
        is taken at its decade start."""
        text = _SEASON_RE.sub("", _HEDGE_RE.sub("", phrase.strip()))
        if _DECADE_RE.fullmatch(text):
            return int(text[:4])
        try:
            parsed = dateparser.parse(text, settings=DateSettings.archive().for_a_year().to_dict())
        except (ValueError, OverflowError):
            return None
        return parsed.year if parsed else None

    def demote(self, claimed: Any) -> DatedFact:
        """Demote an over-claimed precision to what the VALUE's shape actually
        supports — an over-claimed "exact" on a bare year must never pin an
        invented day (PRD §6; reviewer, 2026-08-03). ISO shapes decide by shape;
        a non-ISO phrase is probed against a far-off base — a stable parse means
        the value names its own parts, an unstable one means the parser filled
        them in (demote to the year the parse proved)."""
        precision = claimed if claimed in CLAIMED_PRECISIONS else None
        year = self.parsed.year
        if precision == "exact":
            # an exact day is only provable from a full ISO value; a non-ISO
            # phrase ("July 1979", "31 July 1979") can never claim one — a
            # month-only phrase must not claim an exact day (PRD §6: never
            # fabricate a date part)
            if _ISO_DAY_RE.fullmatch(self.phrase):
                return DatedFact(f"{year:04d}-{self.parsed.month:02d}-{self.parsed.day:02d}", "exact")
            return self.year_or_month()
        if precision == "month":
            return self.year_or_month()
        return DatedFact(f"{year:04d}", precision or "year")

    def year_or_month(self) -> DatedFact:
        """The precision a phrase can prove beyond a bare year: an ISO YYYY-MM
        names its own month; a bare year is a year — the stdlib's Jan-1 is not a
        real date; a non-ISO phrase is probed against a far-off base — a stable
        parse means it names its own month, an unstable one demotes to the year
        the parse proved."""
        year = self.parsed.year
        if _ISO_MONTH_RE.fullmatch(self.phrase):
            return DatedFact(f"{year:04d}-{self.parsed.month:02d}", "month")
        if _ISO_YEAR_RE.fullmatch(self.phrase):
            return DatedFact(f"{year:04d}", "year")
        if self.is_stable():
            return DatedFact(f"{year:04d}-{self.parsed.month:02d}", "month")
        return DatedFact(f"{year:04d}", "year")

    def is_stable(self) -> bool:
        """Does the phrase name its own parts? Re-parse against a far-off base —
        a bare "1963" picks up the base's month/day and shifts; a full
        "15/09/1981" is unchanged. This is the library's own behaviour, never a
        hand-rolled parser (docs/coding-standards.md)."""
        probe = dateparser.parse(self.phrase, settings=DateSettings.archive().at(_FAR_BASE).to_dict())
        return probe is not None and (probe.year, probe.month, probe.day) == (
            self.parsed.year,
            self.parsed.month,
            self.parsed.day,
        )


def asserted_date(value: Any, precision: Any) -> DatedFact | None:
    """The date a model-asserted value states, validated by the real parser:
    dateparser parses the asserted VALUE (locale-aware, incomplete forms
    allowed); the verbatim text is provenance, never parsed. None when the
    parser cannot make sense of it — a person resolves."""
    phrase = ParsedPhrase.of(value)
    return phrase.demote(precision) if phrase else None
