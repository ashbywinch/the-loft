"""The arguments of the ``person`` tool: the id of the person whose record
the model wants to see.

The model sends the call's arguments as its own wire record
(``{"id": …}``); this class owns that shape. The id is an exact record id —
never normalized, never guessed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PersonArgs:
    """The lookup's arguments — the person id, or empty when the model
    called the tool without one (the tool answers with the error)."""

    id: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> PersonArgs:
        """The arguments a tool call states."""
        return cls(id=str(raw.get("id", "")))

    def to_dict(self) -> dict[str, Any]:
        """The arguments as their wire record."""
        return {"id": self.id}
