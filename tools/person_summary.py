"""One person's record as the ``person`` tool shows it: the id, the name,
the recorded relation, and the status.

The status matters to the model: a proposed or estimated record is the
import's guess or the family's own recollection, never an attested fact — the
contradiction check must not treat it as evidence. The shape the model reads
(``{"id": …, "name": …, "relation": …, "status": …}``) is this class's dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PersonSummary:
    """One person's record — the id, the name, the recorded relation, the
    status."""

    id: str
    name: str
    relation: str = ""
    status: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PersonSummary:
        """The record a wire payload states."""
        return cls(
            id=str(raw.get("id", "")),
            name=str(raw.get("name", "")),
            relation=str(raw.get("relation", "")),
            status=str(raw.get("status", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """The record as its wire payload."""
        return {"id": self.id, "name": self.name, "relation": self.relation, "status": self.status}
