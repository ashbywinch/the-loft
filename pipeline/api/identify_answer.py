"""The /api/identify/{item_id} answer: one document's identified entities.

The item as it now stands (its proposed refs), the records those refs name
(existing and freshly proposed), the receipt the family sees, and how many
entities are still waiting — the client's projection is stale until reload,
so the answer carries what the surface has to show.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.records import Item, Person, Place


@dataclass(frozen=True)
class IdentifyAnswer:
    """The identification route's answer: the document, its entities, and
    the review's state."""

    item: Item
    people: tuple[Person, ...] = ()
    places: tuple[Place, ...] = ()
    message: str = ""
    pending: int = 0

    def to_dict(self) -> dict[str, Any]:
        """The answer as its wire record."""
        return {
            "ok": True,
            "item": self.item.to_dict(),
            "people": [person.to_dict() for person in self.people],
            "places": [place.to_dict() for place in self.places],
            "message": self.message,
            "pending": self.pending,
        }
