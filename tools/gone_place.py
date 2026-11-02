"""The marker a delete leaves in the identification review's answer: the place
is gone.

A delete disposition removes the proposed place from the identity table, and
the answer the client renders is this marker — the id and ``gone`` (the app
reads it the same way it reads a person's, app/views/identify.js). Its wire
form (``{"id": …, "gone": true}``) is this class's dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GonePlace:
    """A place a delete removed from the identification review."""

    id: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> GonePlace:
        return cls(id=str(raw.get("id", "")))

    def to_dict(self) -> dict[str, Any]:
        """The marker as the client sees it."""
        return {"id": self.id, "gone": True}
