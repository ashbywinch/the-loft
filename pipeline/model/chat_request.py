"""One chat-completions request: the model, the messages, and the knobs.

The request is the API's wire record, built in one place per client — the
class owns the payload dict so a knob's wire name and shape live with the
field that sets it. ``Reasoning`` owns the reasoning object and its fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pipeline.model.chat_message import ChatMessage
from pipeline.model.reasoning import Reasoning


@dataclass(frozen=True)
class ChatRequest:
    """One chat-completions request. ``reasoning`` is the reasoning state
    (None drops the param entirely, the retry for a model that rejects it);
    ``json_response`` asks the API for a syntactically valid JSON answer.
    The reasoning object's wire shape, including the token cap, is
    ``Reasoning.wire()``."""

    model: str
    messages: list[ChatMessage]
    temperature: float
    max_tokens: int
    reasoning: Reasoning | None = None
    json_response: bool = False

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
        if self.reasoning is not None:
            out["reasoning"] = self.reasoning.wire()
        return out
