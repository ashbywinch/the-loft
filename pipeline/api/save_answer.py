"""The /api/save answer.

The committed story — its id and its sidecar as the projection holds them —
and the identity records the save proposed (never committed without a
reviewer): the app merges all of it into its state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SaveAnswer:
    """The save route's answer: the story, and the records it proposed."""

    id: str
    story: dict[str, Any]
    people: list[dict[str, Any]]
    places: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        """The answer as its wire record."""
        return {
            "ok": True,
            "id": self.id,
            "story": self.story,
            "people": self.people,
            "places": self.places,
        }
