"""The /api/review/start request.

The import session the walk belongs to. A fresh attempt starts only when the
last is empty or finished (the sessions' storage is attempt-separated), so
this names the walk being rendered, never a new one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReviewStartRequest:
    """The review walk's request: the import session it renders."""

    session_id: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ReviewStartRequest:
        """The walk a client states."""
        session_id = str(raw.get("session_id", ""))
        if not session_id:
            raise ValueError("session_id is required")
        return cls(session_id=session_id)
