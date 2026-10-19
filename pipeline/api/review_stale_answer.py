"""The /api/review/decide answer for a decision on an already-resolved person.

A stale decision is a state, not an error: a re-render can re-ask a link that
was already decided (an earlier tap, another reviewer). The answer carries the
person's record as it now stands and the words that say nothing changed — and
no remaining count, because the walk's queue was never re-read for a decision
that changed nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReviewStaleAnswer:
    """The decide route's answer for a decision that changed nothing."""

    person: dict[str, Any] | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        """The answer as its wire record."""
        return {"ok": True, "person": self.person, "message": self.message}
