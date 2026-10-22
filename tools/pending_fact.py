"""A date fact still awaiting the narrator's word.

The narrator answered a date question in their own words; the fact carries the
kind and the verbatim text and no value yet, so the interpreter model is asked
to date it (the model asserts, the library parses —
docs/coding-standards.md). The entry the model is asked about is its own small
record — the kind and the words, never the archive's fact — and its wire form
(``{"kind": …, "text": …}``) is this class's dict.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from tools.assessment_fact import MAX_FACT_TEXT, AssessmentFact


@dataclass(frozen=True)
class PendingFact:
    """One fact the interpreter model must date — its kind and the words the
    answer was given in."""

    kind: str
    text: str

    @classmethod
    def of(cls, fact: AssessmentFact) -> PendingFact | None:
        """The pending entry a fact is — None when the fact is not a date fact,
        carries no verbatim text, or already has its value."""
        if not fact.is_pending():
            return None
        return cls(kind=fact.kind, text=fact.text.strip()[:MAX_FACT_TEXT])

    @classmethod
    def all_from(cls, facts: Iterable[AssessmentFact]) -> tuple[PendingFact, ...]:
        """Every fact still awaiting the narrator's word."""
        return tuple(pending for pending in (cls.of(fact) for fact in facts) if pending)

    def to_dict(self) -> dict[str, Any]:
        """The fact as the interpreter model's input — its kind and the words
        the narrator answered with."""
        return {"kind": self.kind, "text": self.text}
