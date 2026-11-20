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
from typing import Any, Literal, get_args

from pydantic import BaseModel, Field

from tools.contradiction import Contradiction
from tools.finding import Finding
from tools.trace_step import TraceStep

# The values the wire admits, declared once. The model uses these aliases and
# the validation sets below are derived from them, so the prompt, the schema and
# the validator cannot disagree.
Boolean = Literal["true", "false"]
Confidence = Literal["definitely", "think_so", "definitely_not", "think_not", "unclear", "dont_know"]
BOOLEAN_VALUES = frozenset(get_args(Boolean))
CONFIDENCE_VALUES = frozenset(get_args(Confidence))


class Verdict(BaseModel):
    """The verdict the model returns: the answer's members, each with its own
    description, rendered into the prompt.

    The prompt is the only carrier: the review loop's call cannot take a
    response schema without forbidding the tool call, so the six members are
    stated in the prompt and the closed vocabularies are enforced at parse
    (`VerdictRecord.complete`). Nothing in this request enforces the member
    set; do not describe it as if something does.
    """

    class ContradictionWire(BaseModel):
        """Whether the statement cannot both be true with an attested fact."""

        found: Boolean = Field(description="whether the statement cannot both be true with an attested fact")
        detail: str = Field(description="the attested fact that conflicts, or empty")

    class FindingWire(BaseModel):
        """One finding: the document and the sentence it quotes."""

        text: str = Field(
            description=(
                "one sentence in the family's voice ('your recollection', 'you said'), naming "
                "the specific document and its exact quoted sentence; never 'the records', "
                "'the archive' or 'the import'; never an absence; a person record is not "
                "evidence; quote only verified, non-draft text; report a matching item the "
                "reviewer's place or event names and ask if it is the same"
            )
        )
        item_id: str = Field(description="the document id from the tool results")

    relevant: Boolean = Field(description="whether the statement bears on the claim under review")
    contradiction: ContradictionWire = Field(description="whether the statement denies an attested fact")
    confidence: Confidence = Field(
        description=(
            "the reviewer's own certainty, read from their words: definitely (they assert "
            "it), think_so (they hedge it), definitely_not (they deny it), think_not (they "
            "hedge the denial), unclear (a guess they do not commit to), dont_know (nothing "
            "to go on: 'I don't know', 'no idea', 'can't recall' — a reason for knowing "
            "nothing is not a guess). Their words always decide."
        )
    )
    note: str = Field(
        description=(
            "one short sentence in the family's terms when relevant; when not, only the "
            "topic; never the reasoning or 'the reviewer'"
        )
    )
    findings: list[FindingWire] = Field(description="the documents the statement led to")
    question: str = Field(
        description=(
            "the genealogist's next question in the family's words, or a short conclusion "
            "when they have no knowledge and no lead; no process vocabulary"
        )
    )


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
class VerdictRecord:
    """The record of one review turn.

    `Verdict` above is the model's answer: its JSON schema *is* the request,
    so it holds only what the model states. This holds that answer plus
    everything the turn produced around it — the raw output, the tool trace,
    both prompt texts, and any key the wire carried that the model does not
    declare. The fields are flattened for callers that read one answer.
    """

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
    def from_dict(cls, raw: dict[str, Any]) -> VerdictRecord:
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
