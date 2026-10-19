"""The marker a delete leaves in the review's answer: the person is gone.

A delete disposition removes the proposed person from the queue, and the
answer the client renders is this marker — the id and ``gone`` (the app
reads it: app/views/import.js). Its wire form (``{"id": …, "gone": true}``)
is this class's dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GonePerson:
    """A person a delete removed from the review queue."""

    id: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> GonePerson:
        return cls(id=str(raw.get("id", "")))

    def to_dict(self) -> dict[str, Any]:
        """The marker as the client sees it."""
        out: dict[str, Any] = {"id": self.id}
        out["gone"] = True
        return out
