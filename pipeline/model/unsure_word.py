"""One word the transcription model flagged: the model's own doubt.

The flag is the self-report's record (``selfreport.json``:
``{"line", "word"}``) — the word as transcribed and the line number it sits
on, so the layout pass can merge it into that line's per-word flags.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UnsureWord:
    """One word the model is least sure of, or that reads oddly in context:
    the word as transcribed and the number of the line it is on (1-based,
    the numbering the model was shown)."""

    line: int
    word: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> UnsureWord:
        """The flag one self-report record carries."""
        return cls(int(raw["line"]), str(raw["word"]))

    def to_dict(self) -> dict[str, Any]:
        """The flag as its selfreport.json record."""
        return {"line": self.line, "word": self.word}
