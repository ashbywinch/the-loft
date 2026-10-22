"""The assessment: one model pass over a finished account.

The assessment is the flow's one record of what the model read in the account —
the suggested title, the entities the story is about, the dates, dates of birth
and ages the account states, and the bounded questions that nail down genuinely
missing detail (docs/PRD/MEMORIES.md) — and its wire form (``{"title": …,
"extractions": […], "facts": […], "questions": […]}``) is this class's dict.

The class owns the deterministic guards the flow applies to it: the kinship-term
strip and the plausibility filter on date-question suggestions
(docs/coding-standards.md: deterministic checks beat model judgment).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from tools.assessment_fact import AssessmentFact
from tools.extraction import Extraction
from tools.question import Question


@dataclass(frozen=True)
class Assessment:
    """One assessment — its title, the entities the story is about, the facts
    the account states, and the questions still worth asking."""

    title: str
    extractions: tuple[Extraction, ...]
    facts: tuple[AssessmentFact, ...]
    questions: tuple[Question, ...]

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("an assessment needs a title")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Assessment:
        """The assessment a wire object states — the model's output, validated:
        the title is required, and the extractions and questions must be lists
        (a malformed shape fails loudly, never a confusing downstream crash)."""
        title = raw.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("assessment missing a title")
        return cls(
            title=title.strip(),
            extractions=Extraction.from_list(_list_field(raw, key="extractions", what="extractions")),
            facts=AssessmentFact.from_list(raw.get("facts", [])),
            questions=Question.from_list(_list_field(raw, key="questions", what="questions")),
        )

    def to_dict(self) -> dict[str, Any]:
        """The assessment as its wire record — the shape the capture API and the
        browser read."""
        return {
            "title": self.title,
            "extractions": [ex.to_dict() for ex in self.extractions],
            "facts": [fact.to_dict() for fact in self.facts],
            "questions": [q.to_dict() for q in self.questions],
        }

    def strip_kinship_matches(self) -> Assessment:
        """A person extraction whose name is a bare kinship term ('Dad', 'Mum',
        'Aunt') never keeps a match — the term is the writer's own relative, and
        matching it to a record the archive happens to alias is a misattribution.
        The extraction survives (match null) so the unnamed relative can be
        proposed for the writer to identify."""
        return replace(
            self,
            extractions=tuple(ex.unmatched() if ex.is_kinship_term() else ex for ex in self.extractions),
        )

    def strip_ungrounded_matches(self, account: str) -> Assessment:
        """A person, place or item extraction that LINKS a name the account never
        mentions never keeps a match: a name the story never used is not the
        story's. A model that reaches into the archive for it (the account says
        "Dad"; the extraction says "Otto", because Otto's record carries that
        alias) would link a record the narrator never spoke of — and, for a
        kinship term, assert exactly the misattribution the 2026-08-05 ruling
        forbids. The extraction survives (match null) so the narrator can still
        be asked about the person they actually named."""
        spoken = account.casefold()
        return replace(
            self,
            extractions=tuple(ex.unmatched() if ex.has_ungrounded_link(spoken) else ex for ex in self.extractions),
        )

    def with_plausible_suggestions(self, dob_year: int | None) -> Assessment:
        """Filter the date questions' suggestions to the years the narrator could
        plausibly have lived — their date of birth is in the facts or in the
        standing knowledge (docs/coding-standards.md: deterministic checks beat
        model judgment)."""
        if dob_year is None:
            return self
        return replace(self, questions=tuple(q.with_plausible_suggestions(dob_year) for q in self.questions))


def _list_field(raw: Mapping[str, Any], key: str, what: str) -> Any:
    """The assessment field must be a list — a malformed shape fails loudly with
    a named error, never a confusing downstream crash."""
    value = raw.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"assessment {what} are not a list")
    return value
