"""The /api/save request.

The narrator-approved draft the capture flow commits: the page it started
from, the title and the account, the extractions and the typed date answers
the assessment produced, the status, and — for a re-save of an existing draft
— the story's id and the chat it came from.

The facts stay raw: the typed answers to date questions arrive as pending
facts (value null), and ``memory.resolve_pending_facts`` is what turns them
into validated facts (the model asserts, the library parses) — never this
boundary. The narrator is never read from here either: the verified session
names the contribution.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tools.anchor import Anchor
from tools.extraction import Extraction


@dataclass(frozen=True)
class SaveRequest:
    """The save request: the story, its identity, and what it proposed."""

    anchor: Anchor
    title: str = ""
    account: str = ""
    extractions: tuple[Extraction, ...] = ()
    facts: tuple[Mapping[str, Any], ...] = ()
    status: str = "draft"
    story_id: str | None = None
    chat: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> SaveRequest:
        """The save a client states."""
        return cls(
            anchor=Anchor.from_dict(raw.get("anchor", {})),
            title=str(raw.get("title", "")),
            account=str(raw.get("account", "")),
            extractions=Extraction.from_list(raw.get("extractions", [])),
            facts=tuple(raw.get("facts", [])),
            status=str(raw.get("status", "draft")),
            story_id=raw.get("id"),
            chat=raw.get("chat"),
        )
