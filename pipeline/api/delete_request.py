"""The /api/delete request.

The draft to abandon and why. A delete is a SUPERSEDE, never an erasure: the
files stay and the newest version says deleted (append-only). A request with
no id names nothing to supersede, so it is refused here — the route's 400.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DeleteRequest:
    """The abandon request: which draft, and the reason recorded."""

    id: str
    reason: str = "abandoned"

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> DeleteRequest:
        """The abandon a client states."""
        item_id = str(raw.get("id", ""))
        if not item_id:
            raise ValueError("no id")
        return cls(id=item_id, reason=str(raw.get("reason", "abandoned")))
