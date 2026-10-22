"""One page after the orientation arbiter (Rule J): the rotation that won, the
text read in that rotation, and the audit trail of strong-word counts that
decided it.

`rotations.json` records the decision for every oriented page (``degrees``,
``strong``, ``scores``) and ``ocr-raw/<stem>.txt`` its text — both are this
class's dicts, so the arbiter's verdict and its trail are never spelled out
twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OrientedPage:
    """A page's winning rotation, its read text and the arbiter's audit trail."""

    name: str
    text: str
    strong: int  # the winner's strong-word count
    degrees: int  # the winning rotation
    scores: dict[str, int]  # strong counts per rotation — the audit trail

    def __post_init__(self) -> None:
        if self.strong < 0:
            raise ValueError(f"a strong-word count is never negative, got {self.strong}")
        if self.degrees % 90 != 0:
            raise ValueError(f"a page rotation is a quarter turn, got {self.degrees}")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> OrientedPage:
        """The oriented page a wire record states."""
        scores = {str(degrees): int(count) for degrees, count in raw["scores"].items()}
        return cls(
            str(raw["name"]),
            str(raw["text"]),
            int(raw["strong"]),
            int(raw["degrees"]),
            scores,
        )

    def to_dict(self) -> dict[str, Any]:
        """The oriented page as its wire record."""
        return {
            "name": self.name,
            "text": self.text,
            "strong": self.strong,
            "degrees": self.degrees,
            "scores": self.scores,
        }

    def rotation_record(self) -> dict[str, Any]:
        """This page's ``rotations.json`` record: the arbiter's decision and its
        trail — the page's name is the file's key, so it is not repeated here."""
        return {"degrees": self.degrees, "strong": self.strong, "scores": self.scores}
