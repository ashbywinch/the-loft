"""The /api/sync/pending/received request.

The outbox items the site pulled and recorded — the drain's ids. The outbox
validates each id against its own charset (a path-traversal id is refused,
never unlinked), so this record only carries what the client claimed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReceivedRequest:
    """The drain's request: the outbox items the site now holds."""

    ids: list[str]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ReceivedRequest:
        """The received items a client states."""
        return cls(ids=[str(item_id) for item_id in raw.get("ids", [])])
