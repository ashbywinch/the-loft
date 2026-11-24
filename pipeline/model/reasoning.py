"""A call's reasoning: the request's switch and cap, and the reply's text.

The wire field is ``reasoning: {"enabled": …}`` — the object the gateway
(Cloudflare AI Gateway -> OpenRouter) honours. The Anthropic-style
``thinking: {"type": …}`` object was measured to be ignored: every turn came
back ``reasoning: null`` and ``reasoning_tokens: 0``, while the same prompt
with ``reasoning: {"enabled": true}`` returned thousands of reasoning
characters. ``wire()`` is the one place that knows the field names.

A budget (the cap, ``reasoning.max_tokens``) is only meaningful when the
switch is on: construction refuses one on a disabled request rather than
silently dropping it, so a caller that set both gets an error instead of a
call that quietly ran without a cap.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class Reasoning:
    """One call's reasoning state: whether it was asked for, the optional
    token cap, and the deliberation text the reply carried (empty when the
    reply carried none). A reply's text rides the same value as the request
    that produced it, so the two cannot be confused."""

    enabled: bool
    budget: int | None = None
    text: str = ""

    def __post_init__(self) -> None:
        """Refuse a cap on a disabled request: a budget without the switch is
        not a request, and dropping it silently would hide the mistake."""
        if self.budget is not None and not self.enabled:
            raise ValueError(
                "a reasoning budget needs reasoning.enabled — a cap on a disabled request is not a request"
            )

    @property
    def has_text(self) -> bool:
        """Whether the reply carried any deliberation."""
        return bool(self.text)

    def with_text(self, text: str) -> Reasoning:
        """The same request state with the reply's deliberation text."""
        return replace(self, text=text)

    def wire(self) -> dict[str, Any]:
        """The reasoning object for the request body: the switch, plus the
        cap only when the request enables reasoning and sets one."""
        out: dict[str, Any] = {"enabled": self.enabled}
        if self.enabled and self.budget is not None:
            out["max_tokens"] = self.budget
        return out
