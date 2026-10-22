"""One word of a layout line: the text, the box and the review's flag.

The layout's per-word entry is the flag source the review colours: the
word the reader sees, the box it was detected in (None when no detector
boxed it) and the confidence the surface paints (1.0 = the readings agree,
0.0 = doubt). It is its own record because it rides in every line's
``words`` and is written per word — the line's own fields are not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class LayoutWord:
    """One word of a layout line — its text, its box and its flag."""

    word: str
    box: list[float] | None = None
    conf: float = 0.0

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> LayoutWord:
        """The word a layout line's ``words`` entry describes."""
        return cls(word=str(raw.get("word", "")), box=raw.get("box"), conf=float(raw.get("conf", 0.0)))

    def to_dict(self) -> dict[str, Any]:
        """The word as its layout-JSON entry."""
        return {"word": self.word, "box": self.box, "conf": self.conf}
