"""Tests for the import-review investigation (2026-08-09, user: the review
never invents relationships — the model may dig into the reviewer's
statement with the read-only archive tools, then return the verdict; the
reviewer's own words are recorded verbatim or nothing is).
"""

from __future__ import annotations

from typing import Any

import pytest

from tools.memory import ElicitationError
from tools.records import Person, ReviewContext
from tools.review import investigate

PEOPLE: list[dict[str, Any]] = [
    {"id": "p-quentin", "name": "Quentin Whitlock", "relation": "brother of Pearl Whitlock"},
    {"id": "p-pearl", "name": "Pearl Whitlock"},
    {"id": "p-nora", "name": "Nora Whitlock"},
    {"id": "p-walter", "name": "Walter Whitlock", "dod": {"date": "1916-09-15", "precision": "exact"}},
]
PLACES: list[dict[str, Any]] = []
THEMES: list[dict[str, Any]] = []
ITEMS: list[dict[str, Any]] = [
    {
        "id": "item-war-record",
        "title": "The war record",
        "type": "document",
        "story": "Walter Whitlock died on 15 September 1916, aged 21 — the Commonwealth war record.",
    }
]
RELATIONSHIPS: list[dict[str, Any]] = [
    {"a": "p-walter", "b": "p-nora", "kind": "sibling", "label_a": "sibling", "label_b": "sibling"}
]


def make_facts() -> ReviewContext:
    return ReviewContext(
        people=tuple(Person.from_dict(p) for p in PEOPLE),
        items=tuple(ITEMS),
        relationships=tuple(RELATIONSHIPS),
    )


def _person() -> Person:
    return Person.from_dict({"id": "p-quentin", "name": "Quentin Whitlock", "relation": "brother of Pearl Whitlock"})


class FakeClient:
    """Satisfies the ChatClient protocol — one scripted response queue."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def chat(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.responses.pop(0)


VERDICT = {
    "relevant": "true",
    "contradiction": {"found": "false", "detail": ""},
    "confidence": "think_so",
    "note": "Grandma used to say so.",
}


def test_on_topic_answer_is_relevant() -> None:
    client = FakeClient(
        [
            '{"relevant": true, "contradiction": {"found": false, "detail": ""}, '
            '"confidence": "think_so", "note": "Grandma used to say so.", "findings": []}'
        ]
    )
    result = investigate(client, text="Grandma used to say so.", person=_person(), who="Alex", facts=make_facts())
    assert result["relevant"] == "true"
    assert result["contradiction"]["found"] == "false"
    assert len(client.calls) == 1  # no digging needed — a direct verdict
    # the prompt must name the exact claim and carry the attested facts
    assert "Quentin Whitlock" in client.calls[0][1]
    assert "brother of Pearl" in client.calls[0][1]
    assert "Walter Whitlock" in client.calls[0][1]  # the known family is in the prompt


def test_off_topic_answer_is_flagged_not_recorded() -> None:
    client = FakeClient(
        [
            '{"relevant": false, "contradiction": {"found": false, "detail": ""}, '
            '"confidence": "unclear", "note": "the house on Victoria Avenue", "findings": []}'
        ]
    )
    result = investigate(
        client,
        text="Quentin was definitely in that house at the time.",
        person=_person(),
        who="Alex",
        facts=make_facts(),
    )
    assert result["relevant"] == "false"
    assert "house" in result["note"]


def test_contradiction_with_the_attested_facts_is_flagged() -> None:
    """The wrong-person-for-the-attested-event shape (2026-08-09, user): the
    reviewer names the wrong person for an attested event — the check must
    surface the attested fact so the chat can resolve it before confirming."""
    client = FakeClient(
        [
            '{"relevant": true, "contradiction": {"found": true, '
            '"detail": "the war record attests Walter Whitlock died on 15 September 1916"}, '
            '"confidence": "definitely", "note": "the reviewer said it was someone else", "findings": []}'
        ]
    )
    result = investigate(
        client,
        text="It was Nora who died in the war, I remember that clearly.",
        person=_person(),
        who="Alex",
        facts=make_facts(),
    )
    assert result["relevant"] == "true"
    assert result["contradiction"]["found"] == "true"
    assert "Walter Whitlock" in result["contradiction"]["detail"]


def test_the_model_can_dig_with_the_tools_and_reports_findings() -> None:
    """The ad-hoc digging conversation through the app (2026-08-09, user): the
    statement carries a lead; the model calls the read-only tools, the
    harness executes them, and the verdict carries the findings."""
    client = FakeClient(
        [
            '{"tool": "search_people", "args": {"query": "Walter"}}',
            '{"relevant": true, "contradiction": {"found": false, "detail": ""}, '
            '"confidence": "think_so", "note": "the reviewer is half-remembering the right thing", '
            '"findings": ["one of Nora\'s siblings, Walter, died in the war — the archive has his record"]}',
        ]
    )
    result = investigate(
        client,
        text="Not sure. One of Nora's siblings died in the war, I think.",
        person=_person(),
        who="Alex",
        facts=make_facts(),
    )
    assert len(client.calls) == 2  # the tool call, then the verdict
    assert "Tool result (search_people)" in client.calls[1][1]  # the result was fed back
    assert result["findings"] == [
        {"text": "one of Nora's siblings, Walter, died in the war — the archive has his record", "item_id": None}
    ]


def test_the_tools_are_read_only() -> None:
    """The harness only looks things up — a write-shaped tool call is an
    unknown-tool error, never an effect."""
    assert investigate.__doc__  # the docstring pins the read-only contract
    # an unknown tool returns an error from the harness, and the loop continues
    client = FakeClient(
        [
            '{"tool": "delete_person", "args": {"id": "p-walter"}}',
            '{"relevant": true, "contradiction": {"found": false, "detail": ""}, '
            '"confidence": "think_so", "note": "fine", "findings": []}',
        ]
    )
    investigate(client, text="I think so.", person=_person(), who="Alex", facts=make_facts())
    assert "unknown tool" in client.calls[1][1]  # the harness refused, the loop continued


def test_the_model_never_derives_relationships() -> None:
    # the answer mentions a kinship the reviewer never stated — the check
    # must return the verdict, never a resolved term
    client = FakeClient(
        [
            '{"relevant": true, "contradiction": {"found": false, "detail": ""}, '
            '"confidence": "think_so", "note": "the reviewer words are recorded verbatim", "findings": []}'
        ]
    )
    result = investigate(client, text="He was her brother, I think.", person=_person(), who="Alex", facts=make_facts())
    assert "term" not in result
    assert result["relevant"] == "true"


def test_model_that_never_concludes_fails_loudly() -> None:
    # four digs, then the forced-conclusion nudge, then two invalid verdicts —
    # the model never produces a valid one, so the loop fails loudly
    client = FakeClient(
        [
            '{"tool": "search_people", "args": {"query": "x"}}',
            '{"tool": "search_people", "args": {"query": "y"}}',
            '{"tool": "search_people", "args": {"query": "z"}}',
            '{"tool": "search_people", "args": {"query": "w"}}',
            '{"verdict": "no_contradiction", "reasoning": "wrong shape"}',
            '{"verdict": "no_contradiction", "reasoning": "wrong shape"}',
            '{"verdict": "no_contradiction", "reasoning": "wrong shape"}',
            '{"verdict": "no_contradiction", "reasoning": "wrong shape"}',
            '{"verdict": "no_contradiction", "reasoning": "wrong shape"}',
        ]
    )
    with pytest.raises(ElicitationError):
        investigate(client, text="I think so.", person=_person(), who="Alex", facts=make_facts())
    assert len(client.calls) == 9  # the digs, the nudge, the redo prompts — then the loud failure


def test_empty_text_fails_loudly() -> None:
    with pytest.raises(ElicitationError):
        investigate(FakeClient([]), text="  ", person=_person(), who="Alex", facts=make_facts())
