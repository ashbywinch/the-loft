"""The page a contribution started from: what the narrator was looking at.

The anchor is the record the capture flow carries through the assessment —
the kind of page (item, person, place, theme), its id, and its name — and
its wire form (``{"kind": …, "id": …, "name": …}``, the shape the client
sends) is this class's dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Anchor:
    """The page a contribution started from — its kind, id and name."""

    kind: str = "item"
    id: str | None = None
    name: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Anchor:
        """The anchor the client states — an absent kind is an item (the
        archive's default page)."""
        record_id = raw.get("id")
        return cls(
            kind=str(raw.get("kind", "item")),
            id=str(record_id) if record_id else None,
            name=str(raw.get("name", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """The anchor as its wire record."""
        return {"kind": self.kind, "id": self.id, "name": self.name}

    def label(self) -> str:
        """How the anchor reads in a prompt: the name, else the id, else the
        archive's own words for a page with neither."""
        return self.name or self.id or "an item in the archive"
