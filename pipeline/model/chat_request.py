"""One chat-completions request: the model, the messages, and the knobs.

The request is the API's wire record, built in one place per client — the
class owns the payload dict so a knob's wire name and shape live with the
field that sets it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pipeline.model.chat_message import ChatMessage


@dataclass(frozen=True)
class ChatRequest:
    """One chat-completions request. ``thinking`` is the reasoning switch
    (None drops the param entirely — the retry for a model that rejects
    it); ``json_response`` asks the API for a syntactically valid JSON
    answer; ``reasoning_budget`` caps the thinking tokens when a gateway
    honours the cap."""

    model: str
    messages: list[ChatMessage]
    temperature: float
    max_tokens: int
    thinking: bool | None = None
    json_response: bool = False
    reasoning_budget: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """The request as its wire record."""
        out: dict[str, Any] = {
            "model": self.model,
            "messages": [message.to_dict() for message in self.messages],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.json_response:
            out["response_format"] = {"type": "json_object"}
        if self.thinking is not None:
            out["thinking"] = {"type": "enabled" if self.thinking else "disabled"}
        if self.reasoning_budget is not None:
            out["reasoning"] = {"max_tokens": self.reasoning_budget}
        return out
