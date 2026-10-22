"""The /api/review/decide answer for a recorded decision.

The person's record after the decision (None when a duplicate delete found
them already gone), the confirmation words the family saw — rendered, shown
verbatim and recorded verbatim — and the accurate remaining count: the
client's projection is stale until reload, so the count comes from the
server's post-decision truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReviewDecideAnswer:
    """The decide route's answer: the decided person and the walk's state."""

    person: dict[str, Any] | None
    message: str
    pending: int

    def to_dict(self) -> dict[str, Any]:
        """The answer as its wire record."""
        return {"ok": True, "person": self.person, "message": self.message, "pending": self.pending}
