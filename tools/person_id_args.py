"""The arguments of the tools that name a person: the id of the person whose
record the model wants to see.

The ``person``, ``relationships`` and ``attested`` tools all take one person
id — the model sends the call's arguments as its own wire record
(``{"id": …}``); this class owns that shape. The id is an exact record id —
never normalized, never guessed — and an empty id means the model called the
tool without one, which each tool answers in its own way (an error, or a note
that nothing matched).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PersonIdArgs:
    """One person id, or empty when the model called the tool without one."""

    id: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> PersonIdArgs:
        """The arguments a tool call states."""
        return cls(id=str(raw.get("id", "")))

    def to_dict(self) -> dict[str, Any]:
        """The arguments as their wire record."""
        return {"id": self.id}
