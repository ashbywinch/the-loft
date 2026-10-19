"""One vision model call's answer: the text it read and what the call cost.

The pair is the ``.answer.json`` sidecar's record (``{"answer", "usage"}``)
and every caller's return value, so it is its own type: ``answer.answer``
reads the text and ``answer.usage`` the cost, instead of a positional pair
no call site can name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pipeline.model.token_usage import TokenUsage


@dataclass(frozen=True)
class VlmAnswer:
    """What one vision call produced: the transcription text and the usage
    the call cost."""

    answer: str
    usage: TokenUsage

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> VlmAnswer:
        """The answer an ``.answer.json`` sidecar carries."""
        return cls(str(raw["answer"]), TokenUsage.from_dict(raw.get("usage") or {}))

    def to_dict(self) -> dict[str, Any]:
        """The answer as its sidecar record."""
        return {"answer": self.answer, "usage": self.usage.to_dict()}
