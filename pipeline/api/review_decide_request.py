"""The /api/review/decide request.

One decision per proposed link, in the reviewer's own word: ``attested`` (→
confirmed, the reviewer's own verified word), ``estimated`` (→ estimated with
the recorded basis ``{text, by, when}``), ``pending`` (→ the import's guess
stays proposed) or ``delete`` (→ gone). The decision vocabulary is NOT the
status vocabulary: "confirm" is a status, never an action.

The basis is the reviewer's words carried verbatim, and it is an object or
nothing — a scalar there would be silently dropped by the resolution.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast


@dataclass(frozen=True)
class ReviewDecideRequest:
    """One link's disposition: who, what was decided, and on what basis."""

    session_id: str
    person_id: str
    decision: Literal["attested", "estimated", "pending", "delete"]
    basis: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ReviewDecideRequest:
        """The decision a client states."""
        person_id = str(raw.get("person_id", ""))
        decision = str(raw.get("decision", ""))
        if not person_id or decision not in ("attested", "estimated", "pending", "delete"):
            raise ValueError("person_id and a valid decision (attested/estimated/pending/delete) are required")
        basis = raw.get("basis")
        if basis is not None and not isinstance(basis, dict):
            raise ValueError("basis must be an object")
        session_id = str(raw.get("session_id", ""))
        if not session_id:
            raise ValueError("session_id is required")
        return cls(
            session_id=session_id,
            person_id=person_id,
            decision=cast(Literal["attested", "estimated", "pending", "delete"], decision),
            basis=basis,
        )
