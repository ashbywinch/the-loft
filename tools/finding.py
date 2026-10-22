"""One thing the investigation's tools surfaced and the family is shown:
the sentence, and the document that attests it.

A finding is the model's report of a document the tools returned — never a
bare absence ("no record connects X to Y"), never a person record's relation
field (the import's guess, not an attestation), and never a draft
transcription's sentence quoted as the document's own words. Its wire form
(``{"text": …, "item_id": …}``) is this class's dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Finding:
    """One finding — the sentence the family reads, and the document it came
    from (None when the finding names no document)."""

    text: str
    item_id: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | str) -> Finding:
        """The finding a wire record states — a bare string is the model's
        shorthand for a finding with no document."""
        if isinstance(raw, str):
            return cls(text=raw.strip())
        return cls(text=str(raw.get("text", "")).strip(), item_id=str(raw.get("item_id", "")).strip() or None)

    def to_dict(self) -> dict[str, Any]:
        """The finding as its wire record — the document id is present even
        when the finding names none (the model reads the shape)."""
        return {"text": self.text, "item_id": self.item_id}
