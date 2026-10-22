"""The /api/review/start answer.

The lines the current attempt already holds. The app records its rendered
opening/claim only when they are NOT in here, so a mid-walk re-render never
duplicates the transcript.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReviewStartAnswer:
    """The start route's answer: the attempt's recorded lines."""

    messages: list[str]

    def to_dict(self) -> dict[str, Any]:
        """The answer as its wire record."""
        return {"ok": True, "messages": self.messages}
