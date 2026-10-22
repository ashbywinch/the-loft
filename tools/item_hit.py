"""One recorded item the tools surfaced: the id, the title, whether its
transcription is a draft, and the sentences that mention the subject.

The item hit is what the model can quote: the sentences that MENTION the
person (or the searched phrase) are the part that attests the fact, never the
document's opening. ``draft`` marks a machine-read transcription — unverified,
so its sentences are never quoted as the document's own words (IMPORT-PRD
Rule L). The shape the model reads
(``{"id": …, "title": …, "draft": …, "quotes": …}``) is this class's dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ItemHit:
    """One item the tools surfaced — the id, the title, the draft flag, the
    quotable sentences."""

    id: str
    title: str
    draft: bool = False
    quotes: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ItemHit:
        """The hit a wire record states."""
        return cls(
            id=str(raw.get("id", "")),
            title=str(raw.get("title", "")),
            draft=bool(raw.get("draft")),
            quotes=tuple(str(q) for q in (raw.get("quotes") or [])),
        )

    def to_dict(self) -> dict[str, Any]:
        """The hit as its wire record — the quotes as the list the model
        reads."""
        return {"id": self.id, "title": self.title, "draft": self.draft, "quotes": list(self.quotes)}
