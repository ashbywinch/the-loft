"""The /api/identify/decide answer.

The entity as it now stands (a delete answers with the gone marker), the
receipt the family sees, and how many of the document's entities still
wait — the accurate remaining count from the server's post-decision truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


def receipt(name: str, decision: str, basis: dict[str, Any] | None, confirmed: bool = False) -> str:
    """The confirmation's rendered words — the receipt the family sees, in
    the genealogist's voice, naming the consequence (fact / guess / later /
    gone), never the statuses. ``confirmed`` is the record's own standing: a
    person the archive already holds as a fact is never called a guess."""
    if decision in ("attested", "estimated") and confirmed:
        return f"Done — {name} is already recorded as a fact."
    if decision == "attested":
        return f"Done — {name} is recorded as a fact."
    if decision == "estimated":
        text = str((basis or {}).get("text", "")) or "a guess"
        return f"Done — I've recorded {name} as a guess: '{text}'."
    if decision == "delete":
        return f"Done — {name} is not recorded after all."
    return f"{name} stays for later — we can pick it up then."


@dataclass(frozen=True)
class IdentifyDecideAnswer:
    """The decide route's answer: the decided entity and the review's state."""

    kind: Literal["person", "place"]
    entity: dict[str, Any] | None
    message: str
    pending: int

    def to_dict(self) -> dict[str, Any]:
        """The answer as its wire record."""
        return {
            "ok": True,
            "kind": self.kind,
            "entity": self.entity,
            "message": self.message,
            "pending": self.pending,
        }
