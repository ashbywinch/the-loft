"""One chat-completions response: the model's answer, why it stopped, and
what it cost.

The response is the API's wire record; the class reads it, tolerating the
shapes providers actually send (a null choice, a missing usage), so a
caller works with named fields instead of walking ``choices[0]["message"]``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pipeline.model.token_usage import TokenUsage


@dataclass(frozen=True)
class ChatResponse:
    """What one chat call returned: the assistant's text, the API's
    finish_reason, and the usage (the model's reasoning rides the usage —
    a failed call is diagnosable from its trace)."""

    answer: str
    finish_reason: str | None
    usage: TokenUsage

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ChatResponse:
        """The response one chat-completions body carries."""
        choice = raw.get("choices", [{}])[0]
        message = choice.get("message") or {}
        reasoning = message.get("reasoning") or message.get("reasoning_content") or ""
        return cls(
            answer=str(message.get("content") or ""),
            finish_reason=choice.get("finish_reason"),
            usage=TokenUsage.from_dict({**(raw.get("usage") or {}), "reasoning": reasoning}),
        )
