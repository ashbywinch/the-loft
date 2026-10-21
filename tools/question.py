"""A question the assessment asks the narrator.

Every question is skippable — the FLOW's guarantee, never the model's
discretion (user: the narrator answers in their own words or declines, while the
flow keeps pursuing the issue) — and its wire form (``{"text": …, "why": …,
"skippable": …, "suggestions": […], "type": …, "date_kind": …}``) is this
class's dict. The type is closed: a plain question, a date question (the
narrator answers it in their own words — never a hand-rolled picker), or a
people multi-select.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from tools.parsed_phrase import ParsedPhrase

MAX_QUESTIONS = 5
MAX_SUGGESTIONS = 3
MAX_SUGGESTION_CHARS = 60  # a tap-sized label, never a paragraph

QUESTION_TYPES = ("date", "people")

# The words that make a question a date question even when "type" is unset.
_DATE_ASK_WORDS = (
    "what year",
    "which year",
    "in what year",
    "in which year",
    "date of birth",
    "born",
    "how old",
    "your age",
    "what date",
    "when did",
    "when was",
    "when do",
    "when were",
)

# A date question that asks for the narrator's OWN date of birth (rather than
# when the events happened).
_DOB_ASK_WORDS = ("date of birth", "born", "how old", "your age")

# A question whose answer is one or more people: the app offers the cast picker.
_PEOPLE_ASK_WORDS = ("who ", "whose ", "who's ")


def _bounded_suggestions(raw: Any) -> tuple[str, ...]:
    """The tappable suggestions a wire entry states — at most MAX_SUGGESTIONS
    tap-sized labels, blanks dropped."""
    return tuple(
        str(s).strip()[:MAX_SUGGESTION_CHARS]
        for s in (raw if isinstance(raw, list) else [])
        if isinstance(s, str) and s.strip()
    )[:MAX_SUGGESTIONS]


@dataclass(frozen=True)
class Question:
    """One question — its text, its why, its tappable suggestions, and what
    kind of answer it takes. ``skippable`` is the flow's guarantee, never the
    model's discretion."""

    text: str
    why: str = ""
    skippable: bool = True
    suggestions: tuple[str, ...] = ()
    type: str | None = None
    date_kind: str | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("a question needs text")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Question:
        """The question a wire entry states, narrowed to the flow's fields —
        at most MAX_SUGGESTIONS bounded suggestions, and the schema's
        "skippable": true enforced here, at the seam (the eval's contract pins
        it)."""
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"question needs text: {raw!r}")
        q_type = raw.get("type") if raw.get("type") in QUESTION_TYPES else None
        return cls(
            text=text.strip(),
            why=str(raw.get("why", "")),
            skippable=True,
            suggestions=_bounded_suggestions(raw.get("suggestions", [])),
            type=q_type,
            date_kind=raw.get("date_kind") if q_type == "date" else None,
        )

    @classmethod
    def from_wording(cls, text: str, why: str = "", suggestions: Any = ()) -> Question:
        """A question the assessor stated as text, why and tappable
        suggestions — its input surface READ OFF THE WORDING here.

        `type`/`date_kind` are metadata the code infers, never the model's
        deliberation (the assessor used to be asked for them, and spent most of
        its reasoning re-deciding them; the multi-part split measured that).
        A date question is one asked in the date words, a `dob` one when it
        asks for the narrator's own birth; a question whose answer is one or
        more people takes the cast picker; anything else is plain text."""
        lowered = text.lower()
        if any(word in lowered for word in _DATE_ASK_WORDS):
            kind = "dob" if any(word in lowered for word in _DOB_ASK_WORDS) else "event"
            return cls(
                text=text.strip(),
                why=why,
                suggestions=_bounded_suggestions(suggestions),
                type="date",
                date_kind=kind,
            )
        if any(word in lowered for word in _PEOPLE_ASK_WORDS):
            return cls(text=text.strip(), why=why, suggestions=_bounded_suggestions(suggestions), type="people")
        return cls(text=text.strip(), why=why, suggestions=_bounded_suggestions(suggestions))

    @classmethod
    def from_list(cls, raw: Any) -> tuple[Question, ...]:
        """The questions a wire list states — capped at MAX_QUESTIONS, entries
        the flow cannot use dropped."""
        if not isinstance(raw, list):
            return ()
        out: list[Question] = []
        for entry in raw[:MAX_QUESTIONS]:
            if not isinstance(entry, dict):
                continue
            try:
                out.append(cls.from_dict(entry))
            except ValueError:
                continue
        return tuple(out)

    def to_dict(self) -> dict[str, Any]:
        """The question as its wire record."""
        return {
            "text": self.text,
            "why": self.why,
            "skippable": self.skippable,
            "suggestions": list(self.suggestions),
            "type": self.type,
            "date_kind": self.date_kind,
        }

    def asks_for_a_date(self) -> bool:
        """Does the question need a date — typed as one, or asked in the words
        the flow recognises? The narrator answers in their own words; the flow
        never shows a hand-rolled picker."""
        return self.type == "date" or any(word in self.text.lower() for word in _DATE_ASK_WORDS)

    def asks_for_a_date_of_birth(self) -> bool:
        """Is this the polite question for the narrator's own date of birth?"""
        return self.type == "date" and self.date_kind == "dob"

    def asks_for_the_events_date(self) -> bool:
        """Is this the (skippable) question for when the events happened?"""
        return self.type == "date" and self.date_kind == "event"

    def with_plausible_suggestions(self, dob_year: int) -> Question:
        """Keep only the suggestion years the narrator could plausibly have
        lived — a year before their birth is never offered. Suggestions the
        parser cannot date are kept; a dob question (the date is being asked) is
        never filtered."""
        if self.type != "date" or self.asks_for_a_date_of_birth() or not self.suggestions:
            return self
        kept = tuple(s for s in self.suggestions if (year := ParsedPhrase.year_of(s)) is None or year >= dob_year)
        return replace(self, suggestions=kept)
