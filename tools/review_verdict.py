"""The verdict one review turn states: whether the reviewer's answer
addresses the claim under review, whether it contradicts the archive's
attested facts, the reviewer's own certainty, the findings the tools
surfaced, and the genealogist's next question.

The verdict is the investigation's one outcome — the eval's conditions and
the review transcript both read it, so this class owns its wire form: the
keys the model's verdict schema states, in its order, plus the model's final
raw output, the tool trace, and the two prompt texts (the completeness
property: everything the model produced is kept). Any key the model's
verdict JSON carried that this class does not model is kept in ``extra``,
never dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tools.contradiction import Contradiction
from tools.finding import Finding
from tools.trace_step import TraceStep

# The model's boolean as the wire spells it — "true"/"false" as words.
BOOLEAN_VALUES = frozenset({"true", "false"})

# The reviewer's own certainty, never the model's assessment: a hedged "I
# think" is think_so, never definitely; ONLY a bare "I don't know" is
# dont_know (2026-08-15, 2026-10-08).
CONFIDENCE_VALUES = frozenset({"definitely", "think_so", "dont_know", "think_not", "definitely_not", "unclear"})

# The keys the verdict's wire carries — every other key of a model turn is
# unmodeled and rides in ``extra``.
VERDICT_KEYS = frozenset(
    {
        "relevant",
        "contradiction",
        "confidence",
        "note",
        "findings",
        "question",
        "raw",
        "trace",
        "prompt",
        "final_prompt",
    }
)


@dataclass(frozen=True)
class ReviewVerdict:
    """One review turn's verdict — the check's answers, the findings the
    tools surfaced, and the genealogist's question to the family."""

    relevant: str = ""
    contradiction: Contradiction = field(default_factory=Contradiction)
    confidence: str = ""
    note: str = ""
    findings: tuple[Finding, ...] = ()
    question: str = ""
    raw: str = ""
    trace: tuple[TraceStep, ...] = ()
    prompt: str = ""
    final_prompt: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        """Whether the turn states all three closed-vocabulary fields. An
        incomplete turn is neither a tool call nor a verdict: the caller
        feeds it back for a correction, and the missing field stays empty so
        the condition fails loudly — never a silent empty value and never a
        second chance (user)."""
        return (
            self.relevant in BOOLEAN_VALUES
            and self.contradiction.found in BOOLEAN_VALUES
            and self.confidence in CONFIDENCE_VALUES
        )

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ReviewVerdict:
        """The verdict a wire record states — the known keys normalized (the
        vocabularies are lowercase, the prose trimmed), a finding with no
        text dropped, and every unmodeled key kept in ``extra``."""
        contradiction = raw.get("contradiction")
        raw_findings = raw.get("findings")
        raw_trace = raw.get("trace")
        return cls(
            relevant=str(raw.get("relevant", "")).strip().lower(),
            contradiction=Contradiction.from_dict(contradiction if isinstance(contradiction, dict) else {}),
            confidence=str(raw.get("confidence", "")).strip().lower(),
            note=str(raw.get("note", "")).strip(),
            findings=tuple(
                f
                for f in (Finding.from_dict(f) for f in (raw_findings if isinstance(raw_findings, list) else []))
                if f.text
            ),
            question=str(raw.get("question", "")).strip(),
            raw=str(raw.get("raw", "")),
            trace=tuple(TraceStep.from_dict(step) for step in (raw_trace if isinstance(raw_trace, list) else [])),
            prompt=str(raw.get("prompt", "")),
            final_prompt=str(raw.get("final_prompt", "")),
            extra={key: value for key, value in raw.items() if key not in VERDICT_KEYS},
        )

    def to_dict(self) -> dict[str, Any]:
        """The verdict as its wire record — the schema's keys in its order,
        then the unmodeled keys the model carried."""
        out: dict[str, Any] = {
            "relevant": self.relevant,
            "contradiction": self.contradiction.to_dict(),
            "confidence": self.confidence,
            "note": self.note,
            "findings": [finding.to_dict() for finding in self.findings],
            "question": self.question,
            "raw": self.raw,
            "trace": [step.to_dict() for step in self.trace],
            "prompt": self.prompt,
            "final_prompt": self.final_prompt,
        }
        out.update(self.extra)
        return out
