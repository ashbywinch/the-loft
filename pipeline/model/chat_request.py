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
    """One chat-completions request. ``thinking`` is the reasoning switch —
    it goes on the wire as the normalized ``reasoning: {"enabled": …}``
    object the gateway honours (None drops the param entirely, the retry
    for a model that rejects it); ``json_response`` asks the API for a
    syntactically valid JSON answer; ``reasoning_budget`` caps the thinking
    tokens when a gateway honours the cap."""

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
            # The gateway (Cloudflare AI Gateway -> OpenRouter) honours its
            # normalized ``reasoning`` object; Anthropic-style
            # ``thinking: {"type": …}`` was silently ignored — measured:
            # every thinking turn came back `reasoning: null`,
            # `reasoning_tokens: 0`, while the same prompt with
            # ``reasoning: {"enabled": true}`` returned thousands of
            # reasoning characters. The switch is the same field the cap
            # rides on, so the budget merges into this object.
            reasoning: dict[str, Any] = {"enabled": bool(self.thinking)}
            if self.reasoning_budget is not None:
                reasoning["max_tokens"] = self.reasoning_budget
            out["reasoning"] = reasoning
        # a budget without a switch is not a request: it is dropped rather than
        # sent as {"max_tokens": n}, which asks for a cap on a feature nobody
        # enabled
        return out
