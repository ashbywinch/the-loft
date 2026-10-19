"""One step of an investigation's trace: the model's raw turn, its
reasoning, and — on a tool step — the tool it called with the arguments the
model sent and the result the harness answered.

The trace is the model's reasoning made auditable: it is persisted verbatim
as JSON in the review transcript (the assistant message's thinking) and fed
back into later prompts, so this class owns that wire form — a verdict step
carries only ``model`` and ``reasoning``; a tool step adds
``tool``/``args``/``result``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TraceStep:
    """One step — the model's turn, its reasoning, and the tool call it made
    (empty on the turn that concludes the investigation)."""

    model: str
    reasoning: str
    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    result: Any = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TraceStep:
        """The step a wire record states."""
        args = raw.get("args")
        return cls(
            model=str(raw.get("model", "")),
            reasoning=str(raw.get("reasoning", "")),
            tool=str(raw.get("tool", "")),
            args=dict(args) if isinstance(args, dict) else {},
            result=raw.get("result"),
        )

    def to_dict(self) -> dict[str, Any]:
        """The step as its wire record — the tool's keys appear only on a
        tool step (a verdict step is the model's turn and its reasoning)."""
        out: dict[str, Any] = {"model": self.model, "reasoning": self.reasoning}
        if self.tool:
            out["tool"] = self.tool
            out["args"] = self.args
            out["result"] = self.result
        return out
