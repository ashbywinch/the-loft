"""One cached panel read: the transcription text and what the read cost.

The entry is the cache's wire record (``{"text", "tokens"}``), so the class
owns both sides of it — the hit returns the record, not a pair a caller has
to unpack by position.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CachedRead:
    """A panel's cached read: the transcription text and the tokens it
    cost."""

    text: str
    tokens: int

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CachedRead:
        """The entry one cache file carries."""
        return cls(str(raw["text"]), int(raw["tokens"]))

    def to_dict(self) -> dict[str, Any]:
        """The entry as its cache record."""
        return {"text": self.text, "tokens": self.tokens}
