"""The /api/identify/decide request.

One determination for one entity a document names: which document, which
entity (kind and id), the determination, and — for an estimate — the
reviewer's own words. The vocabulary is the review's (attested, estimated,
pending, delete); "confirm" is a status, never an action.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class IdentifyDecideRequest:
    """One entity's disposition: the document, the entity, the decision,
    and the basis."""

    item_id: str
    kind: Literal["person", "place"]
    entity_id: str
    decision: Literal["attested", "estimated", "pending", "delete"]
    basis: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> IdentifyDecideRequest:
        """The decision a client states."""
        item_id = str(raw.get("item_id", ""))
        entity_id = str(raw.get("entity_id", ""))
        kind = str(raw.get("kind", ""))
        decision = str(raw.get("decision", ""))
        if not item_id or not entity_id or kind not in ("person", "place"):
            raise ValueError("item_id, entity_id and a kind (person/place) are required")
        if decision not in ("attested", "estimated", "pending", "delete"):
            raise ValueError("a valid decision (attested/estimated/pending/delete) is required")
        basis = raw.get("basis")
        if basis is not None and not isinstance(basis, dict):
            raise ValueError("basis must be an object")
        return cls(item_id=item_id, kind=kind, entity_id=entity_id, decision=decision, basis=basis)
