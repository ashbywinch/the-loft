"""The arguments of the search tools: the text the model wants to find.

``search_people`` and ``search_items`` both take one query — the model sends
the call's arguments as its own wire record (``{"query": …}``); this class
owns that shape and the normalization the tools match with (the query is
stripped and lowercased, so a differently cased mention still matches). An
empty query means the model called the tool without one — the tool answers
with the error, never a search for everything.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SearchQueryArgs:
    """One normalized query, or empty when the model called the tool without one."""

    query: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> SearchQueryArgs:
        """The arguments a tool call states — the query normalized the way
        the tools match."""
        return cls(query=str(raw.get("query", "")).strip().lower())

    def to_dict(self) -> dict[str, Any]:
        """The arguments as their wire record."""
        return {"query": self.query}
