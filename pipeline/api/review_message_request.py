"""The /api/review/message request.

One of the app's own rendered lines (the opening, the claim), recorded so the
transcript is exactly what the family saw. The role is the speaker's, and an
empty line is refused: the transcript never records words nobody read.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

ROLES = ("user", "assistant")


@dataclass(frozen=True)
class ReviewMessageRequest:
    """The transcript record: one rendered line of the walk."""

    session_id: str
    role: Literal["user", "assistant"]
    text: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ReviewMessageRequest:
        """The rendered line a client states."""
        session_id = str(raw.get("session_id", ""))
        role = str(raw.get("role", ""))
        text = str(raw.get("text", ""))
        if not session_id or role not in ROLES or not text.strip():
            raise ValueError("session_id, role and text are required")
        return cls(session_id=session_id, role=cast(Literal["user", "assistant"], role), text=text)
