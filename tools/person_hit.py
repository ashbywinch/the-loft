"""A person the ``search_people`` tool matched: the id, the name, and the
recorded relation the model may follow up.

The hit is the tool's answer to a search — the model reads it and decides
which ids to look at next, so this class owns the shape the model reads
(``{"id": …, "name": …, "relation": …}``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PersonHit:
    """One person the search matched — the id, the name, the recorded
    relation."""

    id: str
    name: str
    relation: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PersonHit:
        """The hit a wire record states."""
        return cls(
            id=str(raw.get("id", "")),
            name=str(raw.get("name", "")),
            relation=str(raw.get("relation", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """The hit as its wire record."""
        return {"id": self.id, "name": self.name, "relation": self.relation}
