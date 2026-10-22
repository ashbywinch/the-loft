"""One recorded item as the import review's investigation reads it.

The item's id and title, the text the model may quote — the verbatim
transcription when the item has one, else the sidecar's story (the document
the family sees in the claim and the item page) — whether that text is a
machine-read draft (Rule L: a draft's sentences are never the document's own
words, so the model must know which texts are unverified), and the people the
item is recorded as involving.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReviewItem:
    """One item of the review's shortlist — what the model may quote."""

    id: str
    title: str
    story: str
    transcription_status: str | None
    people: list[str]

    def to_dict(self) -> dict[str, Any]:
        """The item as its wire record — the shape ``ReviewContext`` holds."""
        return {
            "id": self.id,
            "title": self.title,
            "story": self.story,
            "transcription_status": self.transcription_status,
            "people": self.people,
        }
