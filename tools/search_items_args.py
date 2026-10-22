"""The arguments of the ``search_items`` tool: the place, town, event, or
phrase the model wants to find in the recorded items' texts.

The model sends the call's arguments as its own wire record
(``{"query": …}``); this class owns that shape and the normalization the
tool matches with (the query is stripped and lowercased, so a differently
cased mention still matches).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SearchItemsArgs:
    """The search's arguments — the query, or empty when the model called
    the tool without one (the tool answers with the error, never a search
    for everything)."""

    query: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> SearchItemsArgs:
        """The arguments a tool call states — the query normalized the way
        the tool matches."""
        return cls(query=str(raw.get("query", "")).strip().lower())

    def to_dict(self) -> dict[str, Any]:
        """The arguments as their wire record."""
        return {"query": self.query}
