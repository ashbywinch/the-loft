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
from tools.review import investigate, steer_message

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


def test_the_model_sees_the_whole_conversation_including_its_own_reasoning() -> None:
    """(2026-08-09, user): the flow misunderstood because the model could
    not see that an answer was re-answering an earlier question — the
    history (the family's words AND the assistant's previous reasoning,
    verbatim) is part of every investigation."""
    client = FakeClient(
        [
            '{"relevant": true, "contradiction": {"found": false, "detail": ""}, '
            '"confidence": "dont_know", '
            '"note": "the reviewer is re-answering the earlier question", "findings": [], "question": ""}'
        ]
    )
    from tools.records import Message

    history = (
        Message(
            role="assistant",
            text="Did Mum tell you that personally?",
            when="2026-08-09",
            thinking='{"relevant": true, "confidence": "think_so"}',
        ),
        Message(role="user", text="No, I don't remember.", when="2026-08-09"),
    )
    result = investigate(
        client,
        text="I've no idea whether she is or not",
        person=_person(),
        who="Alex",
        facts=make_facts(),
        history=history,
    )
    assert result["relevant"] == "true"
    prompt = client.calls[0][1]
    assert "Did Mum tell you that personally?" in prompt  # the assistant's own earlier speech
    assert '"relevant": true, "confidence": "think_so"' in prompt  # its earlier reasoning, verbatim
    assert "I've no idea whether she is or not" in prompt  # the latest statement
    assert "re-answering an EARLIER question" in prompt  # the arc is flagged


def test_the_history_goes_back_verbatim_byte_for_byte() -> None:
    """(2026-08-09, user: 'does the exact same text really go back to the
    model? — makes it cheaper if so, because of caching'): the rendered
    history is the messages unmodified — quotes, apostrophes, unicode —
    so the model's prompt-cache can reuse the stable prefix."""
    from tools.records import Message
    from tools.review import render_history

    history = (
        Message(role="user", text="I said: \"hello\" — it's exact, with 'quotes' and a café.", when="2026-08-09"),
        Message(
            role="assistant",
            text="Did Mum tell you?",
            when="2026-08-09",
            thinking='{"relevant": true, "note": "exact & verbatim \\"quotes\\""}',
        ),
    )
    rendered = render_history(history)
    assert "[family] I said: \"hello\" — it's exact, with 'quotes' and a café." in rendered
    assert '[assistant reasoning] {"relevant": true, "note": "exact & verbatim \\"quotes\\""}' in rendered
    assert "[assistant] Did Mum tell you?" in rendered

    # the same bytes reach the model's prompt
    client = FakeClient(
        [
            '{"relevant": true, "contradiction": {"found": false, "detail": ""}, '
            '"confidence": "dont_know", "note": "fine", "findings": [], "question": ""}'
        ]
    )
    investigate(client, text="next", person=_person(), who="Alex", facts=make_facts(), history=history)
    prompt = client.calls[0][1]
    assert "[family] I said: \"hello\" — it's exact, with 'quotes' and a café." in prompt
    assert '[assistant reasoning] {"relevant": true, "note": "exact & verbatim \\"quotes\\""}' in prompt


def test_the_previous_prompt_is_the_current_prompts_prefix() -> None:
    """The caching property (2026-08-09, user: 'the exact same text goes
    back… cheaper if so, because of caching'): the conversation renders
    uniformly and sits last, so the previous prompt's exact text is the
    current prompt's prefix — the model's prompt-cache reuses the whole
    thing."""
    from tools.records import Message

    client = FakeClient(
        [
            '{"relevant": true, "contradiction": {"found": false, "detail": ""}, '
            '"confidence": "think_so", "note": "first", "findings": [], "question": ""}',
            '{"relevant": true, "contradiction": {"found": false, "detail": ""}, '
            '"confidence": "think_so", "note": "second", "findings": [], "question": ""}',
        ]
    )
    investigate(client, text="first", person=_person(), who="Alex", facts=make_facts(), history=())
    first_prompt = client.calls[0][1]

    history = (
        Message(role="user", text="first", when=""),
        Message(role="assistant", text="Did Mum tell you?", when="", thinking=client.calls[0][0]),
    )
    investigate(client, text="second", person=_person(), who="Alex", facts=make_facts(), history=history)
    second_prompt = client.calls[1][1]

    assert second_prompt.startswith(first_prompt)


def test_the_tool_calls_are_logged_in_the_trace_and_fed_back() -> None:
    """(2026-08-09, user: 'why would that stop you logging them correctly?'
    — nothing does: the tool calls and their deterministic results are part
    of the model's reasoning, logged verbatim in the trace, and the next
    investigation sees them in its history)."""
    import json as _json

    from tools.records import Message

    client = FakeClient(
        [
            '{"tool": "search_people", "args": {"query": "Walter"}}',
            '{"relevant": true, "contradiction": {"found": false, "detail": ""}, '
            '"confidence": "think_so", "note": "fine", "findings": [], "question": ""}',
        ]
    )
    result = investigate(client, text="Walter died in the war", person=_person(), who="Alex", facts=make_facts())
    trace = result["trace"]
    assert len(trace) == 2
    assert trace[0]["tool"] == "search_people"
    assert trace[0]["result"]  # the deterministic harness output
    assert trace[1]["model"]  # the final verdict's raw output

    # the next investigation sees the previous trace in its history
    history = (
        Message(role="user", text="Walter died in the war", when=""),
        Message(role="assistant", text="The documents show: ...", when="", thinking=_json.dumps(trace)),
    )
    client2 = FakeClient(
        [
            '{"relevant": true, "contradiction": {"found": false, "detail": ""}, '
            '"confidence": "think_so", "note": "fine", "findings": [], "question": ""}'
        ]
    )
    investigate(client2, text="next", person=_person(), who="Alex", facts=make_facts(), history=history)
    assert '"tool": "search_people"' in client2.calls[0][1]  # the tool call is in the model's history


def test_the_off_topic_steer_names_the_topic_never_the_reasoning() -> None:
    """2026-08-09 (user, the transcript's third departure): the steer is
    the genealogist's return to the claim — it names the topic the answer
    was about (the note, when it is the topic) and never the model's
    internal reasoning. The reasoning-shaped note would read as nonsense;
    the eval's persona guard catches it at the write seam."""
    person = Person(id="p-pearl", name="Pearl Whitlock", relation="cousin of Quentin Whitlock")
    steer = steer_message(person, "the house on Victoria Avenue")
    assert "That's about the house on Victoria Avenue" in steer
    assert "Pearl Whitlock" in steer
    assert "does that fit what you remember" in steer
    # the empty-note fallback is a plain redirect — nothing internal leaks
    fallback = steer_message(person, "")
    assert "something else" in fallback
    assert "reviewer" not in fallback


def test_the_attested_tool_returns_the_sentence_that_mentions_the_person() -> None:
    """2026-08-09 (user: "extremely bad at identifying the relevant part of
    the document to quote when explaining the attestation"): the attested
    tool returns the sentences that MENTION the person — the quotable
    attestation — never the document's opening. The model can only quote
    what the tools surface, so the relevant part must be what they surface."""
    from tools.review import run_tool

    facts = make_facts()
    # the item's mention sits AFTER a long opening — the first 300 chars
    # would never reach it
    long_item = {
        "id": "doc-1916-letter",
        "title": "Walter Whitlock's letter, Sep 1916",
        "story": (
            "The battalion rested at the camp all week and the weather has been fine. "
            "The mail caught up with us on Tuesday. "
            "I must tell you that Walter Whitlock was killed in the bombardment on the fifteenth."
        ),
    }
    facts = ReviewContext(people=facts.people, items=facts.items + (long_item,), relationships=facts.relationships)
    result = run_tool("attested", {"id": "p-walter"}, facts)
    letter = next(r for r in result if r["id"] == "doc-1916-letter")
    assert letter["quotes"] == ["I must tell you that Walter Whitlock was killed in the bombardment on the fifteenth."]
    assert not any("rested at the camp" in q for q in letter["quotes"])  # never the opening


def test_a_partial_answer_is_fed_back_verbatim_on_the_correction() -> None:
    """2026-08-09 (user: "how can it be that you wrote comprehensive evals
    to make sure our transcript went back verbatim, and now you've found
    that things were missing"): the transcript-going-back principle has a
    second surface — INSIDE an investigation, when the harness re-prompts
    after a partial response, the model's own words must go back too. The
    eval pinned the cross-turn surface only; the intra-turn correction
    dropped the model's reasoning, and the second pass flipped its own
    correct judgment. The correction now feeds the previous answer back
    verbatim."""
    partial = (
        '{"verdict": "uncertain", "reasoning": "The reviewer has no knowledge of Pearl and '
        'cannot confirm or deny the relationship."}'
    )
    verdict = (
        '{"relevant": true, "contradiction": {"found": false, "detail": ""}, '
        '"confidence": "dont_know", "note": "no knowledge", "findings": [], '
        '"question": "I\'ll leave her as she stands unless you\'d like to record what you remember as an estimate."}'
    )
    client = FakeClient([partial, verdict])
    result = investigate(
        client,
        text="I've no idea whether Pearl was Quentin's sister — I never met her.",
        person=_person(),
        who="Alex",
        facts=make_facts(),
    )
    # the second call carries the first response verbatim — the model's own
    # reasoning is its context, exactly as across turns
    assert partial in client.calls[1][1]
    assert result["relevant"] == "true"
    assert result["confidence"] == "dont_know"
    # and the trace logs the partial answer too — nothing the model said is lost
    assert any("verdict" in str(step.get("model", "")) for step in result["trace"])


def test_the_attested_tool_matches_mentions_case_insensitively() -> None:
    """2026-08-11 review: the attested tool matched the person's name
    case-sensitively while its own quote extractor lowercases — an item
    whose only mention is lowercased (OCR text) was silently dropped, so
    the model could conclude no document attests the person. The item
    door now matches the case-insensitive quote semantics."""
    from tools.review import run_tool

    facts = make_facts()
    lower_item = {
        "id": "doc-ocr-letter",
        "title": "An OCR'd letter",
        "story": "the notes my aunt left say pearl was the one who kept the photographs.",
    }
    facts = ReviewContext(people=facts.people, items=facts.items + (lower_item,), relationships=facts.relationships)
    result = run_tool("attested", {"id": "p-pearl"}, facts)
    assert any(r["id"] == "doc-ocr-letter" for r in result)
    quotes = next(r for r in result if r["id"] == "doc-ocr-letter")["quotes"]
    assert quotes == ["the notes my aunt left say pearl was the one who kept the photographs."]


def test_known_facts_mark_guess_statuses_never_attested() -> None:
    """2026-08-11 review: the people table handed to the review still holds
    the proposed person under review, and their import relation used to be
    listed as an attested fact with no status — the contradiction check
    could treat the unverified import guess as attested. Non-confirmed
    statuses are now marked in the rendered facts."""
    proposed = Person.from_dict(
        {"id": "p-nova", "name": "Nova Whitlock", "relation": "cousin of Pearl", "status": "proposed"}
    )
    facts = make_facts()
    facts = ReviewContext(
        people=facts.people + (proposed,),
        items=facts.items,
        relationships=facts.relationships,
    )
    client = FakeClient(
        [
            '{"relevant": true, "contradiction": {"found": false, "detail": ""}, '
            '"confidence": "think_so", "note": "Grandma used to say so.", "findings": []}'
        ]
    )
    _ = investigate(client, text="Grandma used to say so.", person=_person(), who="Alex", facts=facts)
    prompt = client.calls[0][1]
    assert "Nova Whitlock" in prompt
    assert "(status: proposed)" in prompt  # the guess is marked, never attested


def test_over_budget_tool_calls_are_logged_and_fed_back() -> None:
    """2026-08-11 review: a tool-shaped response beyond the four-call budget
    was consumed and discarded — neither logged in the trace nor fed back,
    so the model's own words for that turn vanished (the completeness
    property: everything the model produced is fed back and logged). It is
    now traced and fed back verbatim."""
    tool = '{"tool": "search_people", "args": {"query": "Walter"}}'
    over = '{"tool": "search_people", "args": {"query": "Nora"}}'
    verdict = (
        '{"relevant": true, "contradiction": {"found": false, "detail": ""}, '
        '"confidence": "think_so", "note": "fine", "findings": []}'
    )
    client = FakeClient([tool, tool, tool, tool, over, verdict])
    result = investigate(
        client,
        text="Not sure about the brother link.",
        person=_person(),
        who="Alex",
        facts=make_facts(),
    )
    assert len(client.calls) == 6  # four digs, the over-budget turn, the verdict
    # the over-budget turn's own words are in the trace AND fed forward
    assert any(over in str(step.get("model", "")) for step in result["trace"])
    assert over in client.calls[5][1]
