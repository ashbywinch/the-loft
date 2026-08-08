"""Tests for the import-review kinship resolution (2026-08-08, user: the
review must confirm not just *that* someone is a cousin but *in what way*,
and the chat should have asked that as part of the review).

``resolve_relation`` maps the narrator's words ("She's my mum's cousin on
Fern's side") to one precise term from the closed kinship vocabulary,
anchored in the known family — an exact vocabulary term never needs the
model; free text goes through the model with a bounded redo on violation.
"""

from __future__ import annotations

from typing import Any

import pytest

from tools.memory import ElicitationError, Knowledge
from tools.review import RELATION_TERMS, resolve_relation

PEOPLE: list[dict[str, Any]] = [
    {"id": "p-alex", "name": "Alex Hale", "aliases": ["Alex"]},
    {"id": "p-nora", "name": "Nora Hale", "aliases": ["Mum", "Nora"]},
    {"id": "p-fern", "name": "Fern Kendall", "aliases": ["Gran", "Fern"]},
    {"id": "p-judith", "name": "Pearl Whitlock", "aliases": ["Pearl"], "relation": "cousin"},
]
PLACES: list[dict[str, Any]] = [{"id": "pl-marlock", "name": "Marlock"}]
THEMES: list[dict[str, Any]] = []
ITEMS: list[dict[str, Any]] = []


def make_knowledge(people: list[dict[str, Any]] | None = None) -> Knowledge:
    return Knowledge.from_projection(people or PEOPLE, PLACES, THEMES, ITEMS)


class FakeClient:
    """Satisfies the ChatClient protocol — one scripted response queue."""

    def __init__(self, responses: list[str]) -> None:
        self.responses: list[str] = list(responses)
        self.calls: list[tuple[str, str]] = []

    def chat(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.responses.pop(0)


def _person() -> dict[str, str]:
    return {"id": "p-judith", "name": "Pearl Whitlock", "relation": "cousin"}


def test_exact_vocabulary_term_is_deterministic_without_the_model() -> None:
    client = FakeClient([])
    result = resolve_relation(
        client, text="first cousin once removed", person=_person(), knowledge=make_knowledge(), who="Alex Hale"
    )
    assert result == {"term": "first cousin once removed", "note": ""}
    assert client.calls == []  # the model was never needed


def test_vocabulary_terms_are_all_specific() -> None:
    # the closed vocabulary — never a bare "cousin": the point of the review
    assert "cousin" not in RELATION_TERMS
    assert "first cousin" in RELATION_TERMS
    assert "first cousin once removed" in RELATION_TERMS
    assert "great-aunt" in RELATION_TERMS
    assert "mother-in-law" in RELATION_TERMS
    assert "half-sister" in RELATION_TERMS


def test_free_text_resolves_through_the_model_and_validates_the_term() -> None:
    client = FakeClient(['{"term": "first cousin once removed", "note": "Nora\'s first cousin via Fern."}'])
    result = resolve_relation(
        client,
        text="She's my mum's cousin on Fern's side.",
        person=_person(),
        knowledge=make_knowledge(),
        who="Alex Hale",
    )
    assert result == {"term": "first cousin once removed", "note": "Nora's first cousin via Fern."}
    assert len(client.calls) == 1
    assert "Pearl Whitlock" in client.calls[0][1]  # the person is in the prompt
    assert "Fern" in client.calls[0][1] or "Nora" in client.calls[0][1]  # the family context is in the prompt


def test_model_terms_outside_the_vocabulary_get_a_corrective_redo() -> None:
    # first response invents "cousinette" — the redo must produce a term
    client = FakeClient(['{"term": "cousinette", "note": "invented"}', '{"term": "second cousin", "note": ""}'])
    result = resolve_relation(
        client, text="something distant", person=_person(), knowledge=make_knowledge(), who="Alex"
    )
    assert result["term"] == "second cousin"
    assert len(client.calls) == 2
    assert "cousinette" in client.calls[1][0] or "cousinette" in client.calls[1][1]  # the violation was fed back


def test_model_that_never_returns_a_vocabulary_term_fails_loudly() -> None:
    client = FakeClient(['{"term": "cousinette", "note": "nope"}', '{"term": "also not real", "note": ""}'])
    with pytest.raises(ElicitationError):
        resolve_relation(client, text="distant", person=_person(), knowledge=make_knowledge(), who="Alex")


def test_empty_text_fails_loudly() -> None:
    with pytest.raises(ElicitationError):
        resolve_relation(FakeClient([]), text="  ", person=_person(), knowledge=make_knowledge(), who="Alex")
