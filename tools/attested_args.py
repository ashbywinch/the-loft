"""The arguments of the ``attested`` tool: the id of the person whose
attested facts (the recorded items that mention them) the model wants.

The model sends the call's arguments as its own wire record
(``{"id": …}``); this class owns that shape. The id is an exact record id —
never normalized, never guessed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AttestedArgs:
    """The lookup's arguments — the person id, or empty when the model
    called the tool without one (the tool falls back to the empty id as its
    only needle, and answers with its note)."""

    id: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> AttestedArgs:
        """The arguments a tool call states."""
        return cls(id=str(raw.get("id", "")))

    def to_dict(self) -> dict[str, Any]:
        """The arguments as their wire record."""
        return {"id": self.id}
