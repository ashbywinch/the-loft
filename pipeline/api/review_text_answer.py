"""The /api/review/text answer.

The relevance check as the UI consumes it: the assistant's rendered line,
whether the answer addressed the claim, the contradiction (when the reviewer's
words conflict with an attested fact), the confidence, the findings the
read-only tools surfaced, and the genealogist's question. The model's raw
output, its tool trace and the prompt texts stay the model's internals — never
the family's (R7).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReviewTextAnswer:
    """The free-text check's answer — what the app renders back."""

    message: str
    relevant: str
    contradiction: dict[str, Any]
    confidence: str
    note: str
    findings: list[dict[str, Any]]
    question: str

    def to_dict(self) -> dict[str, Any]:
        """The answer as its wire record."""
        return {
            "ok": True,
            "message": self.message,
            "relevant": self.relevant,
            "contradiction": self.contradiction,
            "confidence": self.confidence,
            "note": self.note,
            "findings": self.findings,
            "question": self.question,
        }
