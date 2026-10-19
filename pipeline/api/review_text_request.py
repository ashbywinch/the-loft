"""The /api/review/text request.

The reviewer's free text against the exact claim under review — the person the
claim is about, and the answer itself, which is recorded verbatim whether or
not the model can be reached (R7: the words are never lost).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReviewTextRequest:
    """The free-text check's request: the claim, and the answer to it."""

    session_id: str
    person_id: str
    text: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ReviewTextRequest:
        """The answer a client states."""
        person_id = str(raw.get("person_id", ""))
        text = str(raw.get("text", ""))
        if not person_id or not text.strip():
            raise ValueError("person_id and text are required")
        session_id = str(raw.get("session_id", ""))
        if not session_id:
            raise ValueError("session_id is required")
        return cls(session_id=session_id, person_id=person_id, text=text)
