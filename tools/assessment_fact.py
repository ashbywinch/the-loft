"""A fact the account states, as the assessment carries it.

The model asserts *what* a phrase is (a birth date, an event date, an age) and
*where* it is; dateparser validates and normalizes the phrase against the
archive's locale (docs/PRD/MEMORIES.md — no hand-coded date parsers). This is
the assertion the flow hands between the assessment, the review and the save,
and its wire form (``{"kind": …, "text": …, "entity": …, "value": …,
"precision": …}``, plus ``status`` where the narrator's own answer asserted it)
is this class's dict. The story's own fact (tools/memory.py's ``Fact``) is the
sidecar's record: the same assertion with the status and the source the keeper
reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.dated_fact import DatedFact
from tools.parsed_phrase import CLAIMED_PRECISIONS, asserted_date

FACT_KINDS = ("dob", "event_date", "age")
MAX_AGE_YEARS = 110  # the oldest plausible human age — older assertions are rejected
MAX_FACT_TEXT = 300  # the verbatim quote is provenance, not an essay
MAX_ENTITY_CHARS = 64  # a record id, never a paragraph


@dataclass(frozen=True)
class AssessmentFact:
    """One fact the account states — its kind, the verbatim words it was stated
    in, the person it belongs to, and the validated value and precision."""

    kind: str
    text: str
    entity: str | None = None
    value: str | int | None = None
    precision: str | None = None
    status: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in FACT_KINDS:
            raise ValueError(f"unknown fact kind: {self.kind!r}")
        if not self.text.strip():
            raise ValueError("a fact needs the verbatim text it was stated in")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AssessmentFact:
        """The fact a wire entry states, validated: the kind is closed, the
        verbatim text is required, and the value is normalized by the library —
        a date by dateparser, an age by the plausible bound."""
        kind = str(raw.get("kind", ""))
        if kind not in FACT_KINDS:
            raise ValueError(f"unknown fact kind: {kind!r}")
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"fact needs the verbatim text it was stated in: {raw!r}")
        entity = raw.get("entity")
        entity = str(entity)[:MAX_ENTITY_CHARS] if entity else None
        status = raw.get("status")
        status = status if isinstance(status, str) and status else None
        if kind == "age":
            age = cls._age(raw.get("value"))
            if age is None:
                raise ValueError(f"age fact with no plausible age: {raw!r}")
            value: str | int | None = age
            precision = raw.get("precision") if raw.get("precision") in CLAIMED_PRECISIONS else "approx"
        else:
            dated = asserted_date(raw.get("value"), raw.get("precision"))
            value, precision = (dated.date, dated.precision) if dated else (None, None)
        return cls(
            kind=kind,
            text=text.strip()[:MAX_FACT_TEXT],
            entity=entity,
            value=value,
            precision=precision,
            status=status,
        )

    @classmethod
    def from_list(cls, raw: Any) -> tuple[AssessmentFact, ...]:
        """The facts a wire list states — an entry the library cannot validate
        is dropped, never trusted (the model's junk and a hand-made request's
        both end here)."""
        if not isinstance(raw, list):
            return ()
        out: list[AssessmentFact] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            try:
                out.append(cls.from_dict(entry))
            except ValueError:
                continue
        return tuple(out)

    @staticmethod
    def _age(value: Any) -> int | None:
        """The age a model-asserted value states — None when it is no age at
        all, or beyond the oldest plausible human one."""
        try:
            age = int(value)
        except (TypeError, ValueError):
            return None
        return age if 0 < age < MAX_AGE_YEARS else None

    def to_dict(self) -> dict[str, Any]:
        """The fact as its wire record — the status only where the narrator's
        own answer asserted it."""
        out: dict[str, Any] = {
            "kind": self.kind,
            "text": self.text,
            "entity": self.entity,
            "value": self.value,
            "precision": self.precision,
        }
        if self.status is not None:
            out["status"] = self.status
        return out

    def dated(self) -> DatedFact | None:
        """The date this fact states, validated by the real parser — None when
        the parser cannot make sense of it (a person's word resolves it)."""
        return asserted_date(self.value, self.precision)

    def is_pending(self) -> bool:
        """Still awaiting the narrator's word: a date fact with verbatim text
        and no value yet — the model is asked to assert one."""
        return self.kind in ("dob", "event_date") and bool(self.text.strip()) and not self.value

    def is_dob(self) -> bool:
        """Is this the date of birth the account states?"""
        return self.kind == "dob"

    def is_event_date(self) -> bool:
        """Is this when the events happened?"""
        return self.kind == "event_date"

    def is_age(self) -> bool:
        """Is this an age the narrator gives about themselves?"""
        return self.kind == "age"

    def is_confirmed(self) -> bool:
        """Did the narrator's own answer assert it (rather than the account's
        prose)?"""
        return self.status == "confirmed"
