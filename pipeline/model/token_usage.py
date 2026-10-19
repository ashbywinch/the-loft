"""What one model call cost: the token counts the API reported and the
model's reasoning.

The usage record rides every answer (the ``.answer.json`` sidecars and the
run reports) and sums across a run's calls, so it is its own type: a caller
reads ``usage.total_tokens`` instead of guessing at dict keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TokenUsage:
    """What one model call cost, as the API reported it: the counts the API
    sent (a count it did not send stays absent, so the record round-trips
    exactly) plus the model's reasoning — recorded here because a failed
    call is diagnosable from its trace (``None`` when the call's answer
    carried none, ``""`` when the reasoning was empty)."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    reasoning: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TokenUsage:
        """The usage one API body (or sidecar) carries."""
        return cls(
            prompt_tokens=_count(raw.get("prompt_tokens")),
            completion_tokens=_count(raw.get("completion_tokens")),
            total_tokens=_count(raw.get("total_tokens")),
            reasoning=None if raw.get("reasoning") is None else str(raw["reasoning"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """The usage as its record: the counts the API sent, plus the
        reasoning when the call produced any (even empty)."""
        out: dict[str, Any] = {}
        for key, value in (
            ("prompt_tokens", self.prompt_tokens),
            ("completion_tokens", self.completion_tokens),
            ("total_tokens", self.total_tokens),
        ):
            if value is not None:
                out[key] = value
        if self.reasoning is not None:
            out["reasoning"] = self.reasoning
        return out

    def plus(self, other: TokenUsage) -> TokenUsage:
        """The run's total with one more call's usage added: the counts sum
        and the reasoning concatenates (the trace keeps every call's
        thinking, the honest cost of the run)."""
        return TokenUsage(
            prompt_tokens=_sum(self.prompt_tokens, other.prompt_tokens),
            completion_tokens=_sum(self.completion_tokens, other.completion_tokens),
            total_tokens=_sum(self.total_tokens, other.total_tokens),
            reasoning=(self.reasoning or "") + (other.reasoning or ""),
        )

    @property
    def tokens(self) -> int:
        """The total the API reported, 0 when it reported none."""
        return self.total_tokens or 0


def _count(value: Any) -> int | None:
    """A token count from a wire record: None when the API sent none."""
    return None if value is None else int(value)


def _sum(a: int | None, b: int | None) -> int | None:
    """Two counts added: absent stays absent."""
    if a is None and b is None:
        return None
    return (a or 0) + (b or 0)
