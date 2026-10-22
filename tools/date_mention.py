"""A date the item's own text mentions, and what the mention is.

The mention is the reader's note that the text states a date — the date,
its precision, and the note saying what the mention is ("the submission",
a date on a stamp). It rides the item's sidecar; its wire form
(``{"date": …, "precision": …}``, plus ``note`` where one is written) is
this class's dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.dated_fact import PRECISIONS


@dataclass(frozen=True)
class DateMention:
    """One date the item's text mentions — the date, its precision, its note."""

    date: str
    precision: str = "exact"
    note: str = ""

    def __post_init__(self) -> None:
        if not self.date.strip():
            raise ValueError(f"date_mention missing date: {self.date!r}")
        if self.precision not in PRECISIONS:
            raise ValueError(f"date_mention has unknown precision: {self.precision!r}")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DateMention:
        """The mention a wire record states."""
        return cls(
            date=str(raw.get("date", "")),
            precision=str(raw.get("precision", "exact")),
            note=str(raw.get("note", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """The mention as its wire record — an unwritten note stays absent."""
        out: dict[str, Any] = {"date": self.date, "precision": self.precision}
        if self.note:
            out["note"] = self.note
        return out
