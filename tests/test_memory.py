"""Tests for the elicitation module: the assessment contract (extractions,
facts, questions), the fact validation (real parser, locale-aware), speaker
resolution, and build_story's canonical story shape."""

from __future__ import annotations

from datetime import date

import pytest

from tools.memory import (
    ElicitationError,
    Knowledge,
    Person,
    assess,
    build_story,
)

PEOPLE = [
    {"id": "p-mum", "name": "Nora Hale", "aliases": ["Mum", "Mummy", "Nora"]},
    {"id": "p-dad", "name": "Owen Hale", "aliases": ["Dad", "Owen"]},
    {"id": "p-alex", "name": "Alex Hale", "aliases": ["Alex"]},
]
PLACES = [
    {"id": "pl-marlock", "name": "Marlock"},
    {"id": "pl-seagate", "name": "Seagate"},
]
THEMES = [{"id": "t-the-boats", "title": "The boats"}]
ITEMS = [{"id": "object-sunlight", "title": "Sunlight", "type": "object"}]

ANCHOR = {"kind": "theme", "id": "t-the-boats", "name": "The boats"}

# every story needs an events date (2026-08-05: the recorded-day fallback
# was a fabrication the moment card served as an anniversary) — fixtures
# that don't test the date derivation carry a real event date
EVENT_DATE = {"kind": "event_date", "text": "1963", "value": "1963", "precision": "year"}


def make_knowledge(people=PEOPLE, places=PLACES, themes=THEMES, items=ITEMS) -> Knowledge:
    """The standing knowledge as one object (docs/coding-standards.md)."""
    return Knowledge(people, places, themes, items)


class FakeClient:
    """Satisfies the ChatClient protocol (chat(system, user) -> str).
    Routes by prompt: the assessor and the reviewer get their own queues."""

    def __init__(self, assessor: list[str], reviewer: list[str] | None = None) -> None:
        self.assessor: list[str] = list(assessor)
        self.reviewer: list[str] = list(reviewer or [])
        self.calls: list[tuple[str, str]] = []

    def chat(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if "review pass" in system:
            return self.reviewer.pop(0)
        return self.assessor.pop(0)


ASSESSOR = "assessor"
REVIEWER = "reviewer"


def make_client(assessor: list[str], reviewer: list[str] | None = None) -> FakeClient:
    return FakeClient(assessor, reviewer or ['{"violations": []}'])


def _basic_assessment(**overrides: object) -> str:
    payload = {
        "title": "The trips",
        "extractions": [
            {"kind": "place", "name": "Marlock", "match": "pl-marlock", "bucket": "proposed", "reason": "about it"},
        ],
        "facts": [
            {"kind": "event_date", "entity": None, "text": "May 1963", "value": "1963-05", "precision": "month"},
        ],
        "questions": [],
        **overrides,
    }
    import json

    return json.dumps(payload)


# -- Knowledge.speaker_for: the cast match is a method on the type ----------


def test_speaker_for_matches_name_and_alias() -> None:
    knowledge = make_knowledge()
    assert knowledge.speaker_for("Mum") == "p-mum"
    assert knowledge.speaker_for("owen") == "p-dad"
    assert knowledge.speaker_for("A Stranger") is None
    assert knowledge.speaker_for("") is None


def test_knowledge_normalizes_plain_dicts_into_typed_records() -> None:
    """The projection's dicts become typed records once, in the Knowledge
    constructor — the members carry their own behavior (docs/coding-
    standards.md: a group's members are their own types, and the functions
    that operate on them are methods)."""
    knowledge = make_knowledge()
    assert knowledge.people[0] == Person(id="p-mum", name="Nora Hale", aliases=("Mum", "Mummy", "Nora"))
    assert knowledge.people[0].matches("mummy")
    assert knowledge.narrator_dob(knowledge.speaker_for("Alex")) is None


def test_person_proposed_mints_an_archive_record() -> None:
    """Introducing a person mints their proposed record — one per name,
    never a duplicate id."""
    first = Person.proposed("Zofia Kowalski", set())
    second = Person.proposed("Zofia Kowalski", {first["id"]})
    assert first["id"] == "p-zofia-kowalski"
    assert second["id"].startswith("p-zofia-kowalski-")
    assert first["relation"] == "added from a story"


# -- assess: contract and the review-redo loop -----------------------------


def test_assess_parses_and_validates_the_model_response() -> None:
    client = make_client(
        [
            '{"title": "The trips", "extractions": [{"kind": "place", "name": "Marlock", "match": "pl-marlock", '
            + '"bucket": "proposed", "reason": "the story is about it"}], '
            + '"facts": [{"kind": "event_date", "text": "May 1963", "value": "1963-05", "precision": "month"}], '
            + '"questions": [{"text": "Who else was there?", "why": "", "skippable": true, '
            + '"suggestions": ["Mum", "Not sure"]}]}'
        ]
    )
    result = assess(
        client,
        anchor=ANCHOR,
        who="Alex",
        account="We went to Marlock in May 1963.",
        knowledge=make_knowledge(),
    )
    assert result["title"] == "The trips"
    assert result["extractions"][0]["match"] == "pl-marlock"
    assert result["facts"] == [
        {"kind": "event_date", "entity": None, "text": "May 1963", "value": "1963-05", "precision": "month"}
    ]
    assert result["questions"][0]["text"] == "Who else was there?"
    assert result["questions"][0]["suggestions"] == ["Mum", "Not sure"]
    assert "Marlock" in client.calls[0][1]  # standing knowledge reached the prompt


def test_assess_redoes_with_feedback_when_the_reviewer_finds_violations() -> None:
    """The single production call self-corrects: a violation triggers a
    feedback-driven redo, not a sampling retry (docs/CONTRIBUTIONS.md)."""
    bad = (
        '{"title": "Wedding", "extractions": [{"kind": "person", "name": "Aunt Nora", '
        + '"match": "p-mum", "bucket": "proposed", "reason": ""}], "facts": [], "questions": []}'
    )
    good = (
        '{"title": "Wedding", "extractions": [{"kind": "person", "name": "Aunt Nora", "match": null, '
        + '"bucket": "unresolved", "reason": "a mention, not a match"}], "facts": [], "questions": ['
        + '{"text": "How are you connected to the family?", "why": "", "skippable": true, '
        + '"suggestions": [], "type": null, "date_kind": null}, '
        + '{"text": "When did the wedding happen?", "why": "", "skippable": false, '
        + '"suggestions": [], "type": "date", "date_kind": "event"}]}'
    )
    client = FakeClient(
        assessor=[bad, good],
        reviewer=[
            '{"violations": ["Aunt Nora is a mention, not a match"]}',
            '{"violations": []}',
        ],
    )
    result = assess(
        client,
        anchor=ANCHOR,
        who="Marek",
        account="Aunt Nora from next door came to our wedding.",
        knowledge=make_knowledge(),
    )
    assert result["extractions"][0]["match"] is None  # the redo fixed the over-match
    assert len(client.calls) == 4  # assessor, reviewer, assessor-redo, reviewer
    assert "Aunt Nora is a mention" in client.calls[2][1]  # the feedback reached the redo


def test_assess_accepts_clean_review_in_one_call() -> None:
    client = make_client([_basic_assessment()])
    result = assess(
        client,
        anchor=ANCHOR,
        who="",
        account="x",
        knowledge=make_knowledge(),
    )
    assert result["title"] == "The trips"
    assert len(client.calls) == 2  # assessor + clean review, no redo


def test_assess_deterministically_redoes_when_a_new_narrator_gets_no_connection_question() -> None:
    """A narrator not in the cast needs a connection question — enforced in
    code, not left to model judgment (docs/CONTRIBUTIONS.md)."""
    first = '{"title": "T", "extractions": [], "facts": [], "questions": []}'
    fixed = (
        '{"title": "T", "extractions": [], "facts": [], "questions": ['
        + '{"text": "How are you connected to the family?", "why": "", "skippable": true, '
        + '"suggestions": [], "type": null, "date_kind": null}, '
        + '{"text": "When did this happen?", "why": "", "skippable": false, '
        + '"suggestions": [], "type": "date", "date_kind": "event"}]}'
    )
    client = FakeClient(
        assessor=[first, fixed],
        reviewer=['{"violations": []}', '{"violations": []}'],
    )
    result = assess(
        client,
        anchor=ANCHOR,
        who="Zofia",
        account="The wedding was lovely.",
        knowledge=make_knowledge(),
    )
    assert len(result["questions"]) == 2  # the connection question + the required events-date question
    assert "connected" in result["questions"][0]["text"]
    assert "connected to the family" in client.calls[2][1]  # the deterministic feedback reached the redo


def test_assess_deterministically_redoes_an_age_without_a_date_question() -> None:
    """An age given with no known dob must produce a polite date question —
    checked in code, not left to model judgment."""
    first = (
        '{"title": "T", "extractions": [], "facts": [{"kind": "age", "entity": null, "text": "I was eight", '
        + '"value": 8, "precision": "approx"}], "questions": []}'
    )
    fixed = (
        '{"title": "T", "extractions": [], "facts": [{"kind": "age", "entity": null, "text": "I was eight", '
        + '"value": 8, "precision": "approx"}], "questions": [{"text": "When did this happen?", "why": "", '
        + '"skippable": false, "suggestions": [], "type": "date", "date_kind": "event"}]}'
    )
    client = FakeClient(
        assessor=[first, fixed],
        reviewer=['{"violations": []}', '{"violations": []}'],
    )
    with_marek = PEOPLE + [{"id": "p-marek", "name": "Marek Kowalski", "aliases": ["Marek"]}]
    result = assess(
        client,
        anchor=ANCHOR,
        who="Marek",
        account="I was eight when we moved.",
        knowledge=make_knowledge(people=with_marek),
    )
    assert len(result["questions"]) == 1
    assert result["questions"][0]["type"] == "date"


def test_assess_deterministically_refuses_a_telling_day_date() -> None:
    """The model must never date the story by the telling day — an event
    date equal to today is a fabrication, redone into a date question that
    stays in the conversation (2026-08-05: the moment card served a story
    told this week as '0 years ago this week' because exactly this
    fabrication won; 2026-08-10: the question is skippable — the narrator
    answers in their own words or declines, but the issue is not dropped)."""
    today = date.today().isoformat()
    bad = (
        '{"title": "T", "extractions": [], "facts": [{"kind": "event_date", "entity": null, '
        + '"text": "the story", "value": "'
        + today
        + '", "precision": "exact"}], "questions": []}'
    )
    fixed = (
        '{"title": "T", "extractions": [], "facts": [], "questions": [{"text": "When did this '
        + 'happen?", "why": "", "skippable": true, "suggestions": [], "type": "date", '
        + '"date_kind": "event"}]}'
    )
    client = FakeClient(assessor=[bad, fixed], reviewer=['{"violations": []}', '{"violations": []}'])
    result = assess(client, anchor=ANCHOR, who="Alex", account="A story.", knowledge=make_knowledge())
    assert not any(f.get("kind") == "event_date" for f in result["facts"])
    date_q = [q for q in result["questions"] if q.get("type") == "date"]
    assert date_q and date_q[0]["skippable"] is True
    assert "telling day" in client.calls[2][1]  # the deterministic feedback reached the redo


def test_assess_accepts_a_narrator_stated_telling_day_date() -> None:
    """A diary-style story that really happened the day it was told is
    legitimate — the narrator's own words ("Today") are the discriminator;
    only fabricated telling-day dates are refused (2026-08-05)."""
    today = date.today().isoformat()
    ok = (
        '{"title": "Diary", "extractions": [], "facts": [{"kind": "event_date", "entity": null, '
        + '"text": "Today", "value": "'
        + today
        + '", "precision": "exact"}], "questions": []}'
    )
    client = FakeClient(assessor=[ok], reviewer=['{"violations": []}'])
    result = assess(client, anchor=ANCHOR, who="Alex", account="Went for a walk today.", knowledge=make_knowledge())
    assert any(f.get("kind") == "event_date" and f.get("value") == today for f in result["facts"])
    assert "telling day" not in client.calls[1][1]  # the reviewer saw no fabrication feedback


def test_assess_requires_a_date_question_when_none_is_established() -> None:
    """The flow must keep pursuing the events date: no event date and no
    computable dob+age -> a date question stays in the questions (2026-08-10,
    user: every question is skippable — the narrator answers in their own
    words or leaves it — but the issue is narrowed until they answer)."""
    bad = '{"title": "T", "extractions": [], "facts": [], "questions": []}'
    fixed = (
        '{"title": "T", "extractions": [], "facts": [], "questions": [{"text": "When did this '
        + 'happen?", "why": "", "skippable": true, "suggestions": [], "type": "date", '
        + '"date_kind": "event"}]}'
    )
    client = FakeClient(assessor=[bad, fixed], reviewer=['{"violations": []}', '{"violations": []}'])
    result = assess(client, anchor=ANCHOR, who="Alex", account="A story.", knowledge=make_knowledge())
    date_q = [q for q in result["questions"] if q.get("type") == "date"]
    assert date_q and date_q[0]["skippable"] is True
    assert "events date" in client.calls[2][1]


def test_assess_deterministically_redoes_a_new_artifact_without_a_tell_me_question() -> None:
    """A specific new artifact named in the story (item, no match) with no
    question about it is a violation — checked in code, not model judgment."""
    first = (
        '{"title": "T", "extractions": [{"kind": "item", "name": "SB Mirosa", "match": null, '
        + '"bucket": "proposed", "reason": ""}], "facts": [], "questions": []}'
    )
    fixed = (
        '{"title": "T", "extractions": [{"kind": "item", "name": "SB Mirosa", "match": null, '
        + '"bucket": "proposed", "reason": ""}], "facts": [], "questions": ['
        + '{"text": "Tell me more about the SB Mirosa.", "why": "", "skippable": true, '
        + '"suggestions": [], "type": null, "date_kind": null}, '
        + '{"text": "When did this happen?", "why": "", "skippable": false, '
        + '"suggestions": [], "type": "date", "date_kind": "event"}]}'
    )
    client = FakeClient(
        assessor=[first, fixed],
        reviewer=['{"violations": []}', '{"violations": []}'],
    )
    result = assess(
        client,
        anchor=ANCHOR,
        who="Alex",
        account="The Mirosa moored alongside.",
        knowledge=make_knowledge(),
    )
    assert len(result["questions"]) == 2  # the tell-me question + the required events-date question
    assert "Mirosa" in result["questions"][0]["text"]
    assert "tell me more" in client.calls[2][1]  # the deterministic feedback reached the redo


def test_assess_deterministically_blocks_a_date_question_when_the_year_is_computable() -> None:
    """An age plus a known dob makes the year computable — a date question is
    a violation, caught in code."""
    with_dob = PEOPLE + [{"id": "p-marek", "name": "Marek Kowalski", "aliases": ["Marek"], "dob": "1982-05-01"}]
    bad = (
        '{"title": "T", "extractions": [], "facts": [{"kind": "age", "entity": null, "text": "I was eight", '
        + '"value": 8, "precision": "approx"}], "questions": [{"text": "When did this happen?", "why": "", '
        + '"skippable": true, "suggestions": [], "type": "date", "date_kind": "event"}]}'
    )
    good = (
        '{"title": "T", "extractions": [], "facts": [{"kind": "age", "entity": null, "text": "I was eight", '
        + '"value": 8, "precision": "approx"}], "questions": []}'
    )
    client = FakeClient(
        assessor=[bad, good],
        reviewer=['{"violations": []}', '{"violations": []}'],
    )
    result = assess(
        client,
        anchor=ANCHOR,
        who="Marek",
        account="I was eight when we moved.",
        knowledge=make_knowledge(people=with_dob),
    )
    assert result["questions"] == []


def test_assess_raises_on_malformed_output() -> None:
    client = make_client(["not json at all"])
    with pytest.raises(ElicitationError):
        _ = assess(client, anchor=ANCHOR, who="", account="x", knowledge=make_knowledge())


def test_assess_rejects_missing_title() -> None:
    client = make_client(['{"extractions": [], "facts": [], "questions": []}'])
    with pytest.raises(ElicitationError):
        _ = assess(client, anchor=ANCHOR, who="", account="x", knowledge=make_knowledge())


# -- facts: validated by the real parser, locale-aware ----------------------


def test_assess_normalizes_facts_with_the_date_library() -> None:
    """The model asserts; the library parses and normalizes (no hand parsers)."""
    client = make_client(
        [
            '{"title": "T", "extractions": [], "facts": ['
            + '{"kind": "dob", "entity": "p-mum", "text": "15/09/1981", "value": "1981-09-15", "precision": "exact"}, '
            + '{"kind": "dob", "text": "July 1979", "value": "July 1979", "precision": "month"}, '
            + '{"kind": "dob", "text": "1979", "value": "1979", "precision": "year"}, '
            + '{"kind": "dob", "text": "sometime in spring", "value": "spring", "precision": "approx"}, '
            + '{"kind": "age", "text": "I was eight", "value": 8, "precision": "approx"}, '
            + '{"kind": "wombat", "text": "junk", "value": "x"}], "questions": []}'
        ]
    )
    result = assess(
        client,
        anchor=ANCHOR,
        who="",
        account="x",
        knowledge=make_knowledge(),
    )
    facts = result["facts"]
    by_text = {f["text"]: f for f in facts}
    # the model's value contract is ISO: an exact day arrives as YYYY-MM-DD;
    # a non-ISO phrase can never claim an exact day (reviewer, 2026-08-03)
    assert by_text["15/09/1981"]["value"] == "1981-09-15"
    assert by_text["15/09/1981"]["precision"] == "exact"
    assert by_text["15/09/1981"]["entity"] == "p-mum"
    assert by_text["July 1979"]["value"] == "1979-07" and by_text["July 1979"]["precision"] == "month"
    assert by_text["1979"]["value"] == "1979" and by_text["1979"]["precision"] == "year"
    # a phrase the parser cannot make sense of -> null value, kept for the keeper
    assert by_text["sometime in spring"]["value"] is None
    assert by_text["sometime in spring"]["precision"] is None
    assert by_text["I was eight"]["value"] == 8
    assert "wombat" not in facts


def test_facts_respect_the_locale_for_ambiguous_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """The parser reads ambiguous numerics per the archive locale: en_GB is
    DMY by default, en_US (LOFT_LOCALE) is MDY."""
    client = make_client(
        [
            '{"title": "T", "extractions": [], "facts": ['
            + '{"kind": "dob", "text": "15/09/1981", "value": "15/09/1981", "precision": "exact"}, '
            + '{"kind": "event_date", "text": "1963", "value": "1963", "precision": "year"}], "questions": []}'
        ]
    )
    # default archive locale: British — 15/09/1981 is 15 September (month 09),
    # never 9 January (month 01) — the demotion to month still shows the locale
    result = assess(
        client,
        anchor=ANCHOR,
        who="",
        account="x",
        knowledge=make_knowledge(),
    )
    assert result["facts"][0]["value"] == "1981-09"

    monkeypatch.setenv("LOFT_LOCALE", "en_US")
    client = make_client(
        [
            '{"title": "T", "extractions": [], "facts": ['
            + '{"kind": "dob", "text": "08/12/1967", "value": "08/12/1967", "precision": "exact"}, '
            + '{"kind": "event_date", "text": "1963", "value": "1963", "precision": "year"}], "questions": []}'
        ]
    )
    result = assess(
        client,
        anchor=ANCHOR,
        who="",
        account="x",
        knowledge=make_knowledge(),
    )
    assert result["facts"][0]["value"] == "1967-08"  # US reads 08/12 as August (month 08), never December


def test_standing_knowledge_includes_dob_and_items() -> None:
    client = make_client([_basic_assessment()])
    _ = assess(
        client,
        anchor=ANCHOR,
        who="",
        account="x",
        knowledge=make_knowledge(
            people=[{"id": "p-x", "name": "X", "aliases": [], "dob": "1978-04-12"}],
            items=[{"id": "object-sunlight", "title": "Sunlight", "type": "object"}],
        ),
    )
    prompt = client.calls[0][1]
    assert "(born 1978-04-12)" in prompt
    assert "object-sunlight — Sunlight (object)" in prompt


# -- build_story: facts decide the dates ------------------------------------


def test_build_story_dates_events_from_dob_and_age_facts() -> None:
    with_ashby = PEOPLE + [{"id": "p-alex", "name": "Alex Hale", "aliases": ["Alex"]}]
    story, _, _ = build_story(
        anchor=ANCHOR,
        who="Alex",
        title="T",
        account="When I was three or so I went to the boatyard.",
        extractions=[],
        facts=[
            {"kind": "dob", "entity": "p-alex", "text": "15/09/1981", "value": "1981-09-15", "precision": "exact"},
            {"kind": "age", "text": "three or so", "value": 3, "precision": "approx"},
        ],
        knowledge=make_knowledge(people=with_ashby),
        existing_ids=set(),
        recorded="2026-08-03",
    )
    assert story["date"] == "1984" and story["date_precision"] == "approx"  # 1981 + 3, arithmetic only
    assert story["facts"][0]["status"] == "proposed"  # stated in prose, not via the picker
    assert story["facts"][0]["value"] == "1981-09-15"


def test_build_story_answered_dob_is_confirmed() -> None:
    """A dob the narrator asserts in answer to a direct question is
    confirmed, not proposed — the answer IS the assertion (2026-08-03)."""
    with_ashby = PEOPLE + [{"id": "p-alex", "name": "Alex Hale", "aliases": ["Alex"]}]
    story, _, _ = build_story(
        anchor=ANCHOR,
        who="Alex",
        title="T",
        account="That was the year.",
        extractions=[],
        facts=[
            {
                "kind": "dob",
                "entity": "p-alex",
                "text": "",
                "value": "1981-09-15",
                "precision": "exact",
                "status": "confirmed",
            },
            EVENT_DATE,
        ],
        knowledge=make_knowledge(people=with_ashby),
        existing_ids=set(),
        recorded="2026-08-03",
    )
    fact = story["facts"][0]
    assert fact["status"] == "confirmed"
    assert fact["source"] == "the narrator's own answer"


def test_build_story_event_date_fact_wins() -> None:
    story, _, _ = build_story(
        anchor=ANCHOR,
        who="Alex",
        title="T",
        account="We went to Marlock.",
        extractions=[],
        facts=[{"kind": "event_date", "text": "May 1963", "value": "1963-05", "precision": "month"}],
        knowledge=make_knowledge(),
        existing_ids=set(),
        recorded="2026-08-03",
    )
    assert story["date"] == "1963-05" and story["date_precision"] == "month"


def test_build_story_unparseable_dob_stays_verbatim_for_the_keeper() -> None:
    """An unparseable dob phrase is recorded verbatim for a person to
    resolve — and the story still needs its events date (2026-08-05)."""
    story, _, _ = build_story(
        anchor=ANCHOR,
        who="Alex",
        title="T",
        account="I was born one winter.",
        extractions=[],
        facts=[
            {"kind": "dob", "entity": None, "text": "born one winter", "value": None, "precision": None},
            EVENT_DATE,
        ],
        knowledge=make_knowledge(),
        existing_ids=set(),
        recorded="2026-08-03",
    )
    fact = story["facts"][0]
    assert fact["value"] is None and fact["precision"] is None
    assert fact["status"] == "proposed"  # the keeper resolves the phrase
    assert story["date"] == "1963"  # the events date, not the recorded day


def test_build_story_new_narrator_record_carries_the_stated_dob() -> None:
    story, new_people, _ = build_story(
        anchor=ANCHOR,
        who="Zofia",
        title="T",
        account="I was eight then.",
        extractions=[],
        facts=[
            {"kind": "dob", "entity": None, "text": "born 15/09/1984", "value": "1984-09-15", "precision": "exact"},
            {"kind": "age", "text": "I was eight", "value": 8, "precision": "approx"},
        ],
        knowledge=make_knowledge(),
        existing_ids=set(),
        recorded="2026-08-03",
    )
    assert story["date"] == "1992" and story["date_precision"] == "approx"
    narrator = [p for p in new_people if p["id"] == story["told_by"]][0]
    assert narrator["dob"] == "1984-09-15"


def test_build_story_links_artifacts_and_leaves_unknowns_unresolved() -> None:
    story, _, _ = build_story(
        anchor=ANCHOR,
        who="Alex",
        title="T",
        account="We sailed Sunlight and later a new boat Dad was building.",
        extractions=[
            {"kind": "item", "name": "Sunlight", "match": "object-sunlight", "bucket": "proposed", "reason": ""},
            {"kind": "item", "name": "the new boat", "match": None, "bucket": "unresolved", "reason": "no match"},
        ],
        facts=[EVENT_DATE],
        knowledge=make_knowledge(),
        existing_ids=set(),
    )
    assert {"id": "object-sunlight", "status": "proposed"} in story["items"]
    assert len(story["items"]) == 1  # an artifact without a match stays unresolved


def test_build_story_catalogued_item_link_to_draft_artifact_is_proposed() -> None:
    """A catalogued story never confirms a link the reader cannot see: an
    item ref whose artifact is still a draft is downgraded to proposed
    (2026-08-05 — story-2026-08-03-05 confirmed a draft object-sb-mirosa,
    leaving a dangling link)."""
    story, _, _ = build_story(
        anchor=ANCHOR,
        who="Alex",
        title="T",
        account="We were babysat by the crew of the Mirosa.",
        extractions=[
            {"kind": "item", "name": "SB Mirosa", "match": "object-sb-mirosa", "bucket": "proposed", "reason": ""},
        ],
        facts=[EVENT_DATE],
        knowledge=make_knowledge(
            items=[{"id": "object-sb-mirosa", "title": "SB Mirosa", "type": "object", "status": "draft"}]
        ),
        existing_ids=set(),
        recorded="2026-08-03",
        status="catalogued",
    )
    assert {"id": "object-sb-mirosa", "status": "proposed"} in story["items"]


def test_build_story_catalogued_item_link_to_catalogued_artifact_is_confirmed() -> None:
    """A catalogued artifact is a fair target for a confirmed link — the
    downgrade applies to drafts only."""
    story, _, _ = build_story(
        anchor=ANCHOR,
        who="Alex",
        title="T",
        account="We sailed Sunlight.",
        extractions=[
            {"kind": "item", "name": "Sunlight", "match": "object-sunlight", "bucket": "proposed", "reason": ""},
        ],
        facts=[EVENT_DATE],
        knowledge=make_knowledge(
            items=[{"id": "object-sunlight", "title": "Sunlight", "type": "object", "status": "catalogued"}]
        ),
        existing_ids=set(),
        recorded="2026-08-03",
        status="catalogued",
    )
    assert {"id": "object-sunlight", "status": "confirmed"} in story["items"]


def test_story_sidecar_serializes_typed_refs() -> None:
    """The Story domain object carries typed Ref links and serializes to
    the sidecar shape the archive writes (docs/coding-standards.md: a
    group's members are their own types)."""
    from tools.memory import Ref, Story

    story = Story(
        story_id="story-x",
        title="T",
        date="2026-08-03",
        date_precision="exact",
        recorded="2026-08-03",
        description="",
        story="text",
        transcription="",
        told_by="p-alex",
        comment_on=None,
        chat=None,
        source="Site contribution, 2026-08-03",
        people=(),
        places=(),
        themes=(),
        items=(Ref("object-sunlight", "confirmed"),),
        facts=(),
        status="catalogued",
    )
    sidecar = story.to_sidecar()
    assert sidecar["items"] == [{"id": "object-sunlight", "status": "confirmed"}]
    assert sidecar["status"] == "catalogued" and sidecar["type"] == "story"


def test_assess_strips_kinship_term_matches() -> None:
    """A bare kinship term ('Dad', 'Mum') is never matched to a person
    record — the code strips the model's default rather than trusting it
    (eval: kinship-term-not-an-archive-alias, 2026-08-05); writer-relative
    resolution is a later seam, not the model's guess. A real name keeps
    its match."""
    import json as _json

    client = make_client(
        [
            _json.dumps(
                {
                    "title": "The house",
                    "extractions": [
                        {
                            "kind": "person",
                            "name": "Dad",
                            "match": "p-otto",
                            "bucket": "proposed",
                            "reason": "about it",
                        },
                        {
                            "kind": "person",
                            "name": "Owen",
                            "match": "p-dad",
                            "bucket": "proposed",
                            "reason": "about it",
                        },
                    ],
                    "facts": [
                        {"kind": "event_date", "entity": None, "text": "1963", "value": "1963", "precision": "year"}
                    ],
                    "questions": [],
                }
            )
        ]
    )
    result = assess(client, anchor=ANCHOR, who="Alex", account="Dad came with me.", knowledge=make_knowledge())
    by_name = {ex["name"]: ex for ex in result["extractions"]}
    assert by_name["Dad"]["match"] is None, "bare kinship term kept a match"
    assert by_name["Owen"]["match"] == "p-dad", "a real name must keep its match"


def test_build_story_reuses_an_existing_place_by_name() -> None:
    """A story mentioning a place whose name is already in the standing
    knowledge reuses that id — it never mints a duplicate entity (the
    moored-barges ×3 came from minting one id per story mention,
    2026-08-05)."""
    story, _, new_places = build_story(
        anchor=ANCHOR,
        who="Alex",
        title="T",
        account="We moored among the moored barges.",
        extractions=[
            {"kind": "place", "name": "the moored barges", "match": None, "bucket": "proposed", "reason": ""},
        ],
        facts=[EVENT_DATE],
        knowledge=make_knowledge(places=[{"id": "pl-the-moored-barges", "name": "the moored barges"}]),
        existing_ids=set(),
        recorded="2026-08-03",
        status="catalogued",
    )
    assert {"id": "pl-the-moored-barges", "status": "confirmed"} in story["places"]
    assert new_places == []  # no duplicate record minted


def test_build_story_reuses_an_existing_person_by_name() -> None:
    """A story naming a cast member who is not model-matched reuses their
    id — never mints a duplicate (the person analog of the place name-dedup,
    2026-08-05 bot review)."""
    story, new_people, _ = build_story(
        anchor=ANCHOR,
        who="Alex",
        title="T",
        account="Nora was there.",
        extractions=[
            {"kind": "person", "name": "Nora Smith", "match": None, "bucket": "proposed", "reason": ""},
        ],
        facts=[EVENT_DATE],
        knowledge=make_knowledge(people=PEOPLE + [{"id": "p-nora", "name": "Nora Smith", "aliases": []}]),
        existing_ids=set(),
        recorded="2026-08-03",
        status="catalogued",
    )
    assert {"id": "p-nora", "status": "confirmed"} in story["people"]
    assert new_people == []  # no duplicate record minted


def test_build_story_kinship_term_reuses_an_existing_proposed_record() -> None:
    """Two stories mentioning the same bare kinship term (Grandma) must
    share ONE proposed record. Minting a fresh proposed id per story makes
    the projection's name-dedup drop the second mint, and its story's ref
    then dangles at publish (2026-08-05 bot review). A CONFIRMED person is
    still never reused for a kinship term — fail closed; only another
    proposed record is."""
    first, new_people, _ = build_story(
        anchor=ANCHOR,
        who="Alex",
        title="T1",
        account="Grandma came.",
        extractions=[
            {"kind": "person", "name": "Grandma", "match": None, "bucket": "proposed", "reason": ""},
        ],
        facts=[EVENT_DATE],
        knowledge=make_knowledge(people=PEOPLE),
        existing_ids=set(),
        recorded="2026-08-03",
        status="catalogued",
    )
    assert len(new_people) == 1 and new_people[0]["name"] == "Grandma"
    grandma_id = new_people[0]["id"]

    # the second story's standing knowledge includes the queued proposal as
    # the projection carries it (status proposed — the archive propose seam
    # marks it when the first story saves)
    queued = [{**new_people[0], "status": "proposed"}]
    second, new_people2, _ = build_story(
        anchor=ANCHOR,
        who="Eli",
        title="T2",
        account="Grandma came too.",
        extractions=[
            {"kind": "person", "name": "Grandma", "match": None, "bucket": "proposed", "reason": ""},
        ],
        facts=[EVENT_DATE],
        knowledge=make_knowledge(people=PEOPLE + queued),
        existing_ids={grandma_id},
        recorded="2026-08-03",
        status="catalogued",
    )
    assert grandma_id in {r["id"] for r in second["people"]}
    # no duplicate Grandma mint — the only new record is the narrator Eli
    assert all(p["name"] != "Grandma" for p in new_people2)
    assert [p["name"] for p in new_people2] == ["Eli"]


def test_build_story_kinship_term_stays_proposed_not_reused() -> None:
    """A bare kinship term is the writer's own relative, never a cast alias —
    even when a standing person carries that exact alias, the term is minted
    proposed for the writer to identify (the kinship filter's strip stays
    effective, 2026-08-05)."""
    story, new_people, _ = build_story(
        anchor=ANCHOR,
        who="Alex",
        title="T",
        account="Grandma came.",
        extractions=[
            {"kind": "person", "name": "Grandma", "match": None, "bucket": "proposed", "reason": ""},
        ],
        facts=[EVENT_DATE],
        knowledge=make_knowledge(people=PEOPLE + [{"id": "p-x", "name": "X", "aliases": ["Grandma"]}]),
        existing_ids=set(),
        recorded="2026-08-03",
        status="catalogued",
    )
    assert {"id": "p-x", "status": "confirmed"} not in story["people"]
    assert len(new_people) == 1 and new_people[0]["name"] == "Grandma"


def test_fact_round_trip_and_validation() -> None:
    """A stated fact is a typed, serialisable record — kind and status are
    closed, and the sidecar shape round-trips exactly (2026-08-05)."""
    from tools.memory import Fact

    raw = {
        "kind": "dob",
        "entity": "p-alex",
        "text": "15/09/1981",
        "value": "1981-09-15",
        "precision": "exact",
        "status": "confirmed",
        "source": "the narrator's own answer",
    }
    assert Fact.from_dict(raw).to_dict() == raw
    with pytest.raises(ValueError, match="kind"):
        Fact.from_dict({"kind": "bogus", "text": ""})
    with pytest.raises(ValueError, match="status"):
        Fact.from_dict({"kind": "dob", "text": "", "status": "maybe"})


def test_build_story_dedupes_anchor_and_extraction_refs() -> None:
    """The starting page and an extraction may name the same entity — one ref."""
    story, _, _ = build_story(
        anchor={"kind": "place", "id": "pl-seagate", "name": "Seagate"},
        who="Alex",
        title="T",
        account="We sailed around Seagate.",
        extractions=[{"kind": "place", "name": "Seagate", "match": "pl-seagate", "bucket": "proposed", "reason": ""}],
        facts=[EVENT_DATE],
        knowledge=make_knowledge(),
        existing_ids=set(),
        recorded="2026-08-03",
    )
    assert story["places"].count({"id": "pl-seagate", "status": "proposed"}) == 1


def test_build_story_verified_save_is_catalogued_with_confirmed_refs() -> None:
    """The operator verifies the AI's guesses in the same flow: a completed,
    reviewed save is catalogued and its kept links are confirmed; an
    abandoned one stays draft with proposed links (docs/CONTRIBUTIONS.md)."""
    verified, _, _ = build_story(
        anchor={"kind": "place", "id": "pl-seagate", "name": "Seagate"},
        who="Alex",
        title="T",
        account="We sailed around Seagate.",
        extractions=[{"kind": "place", "name": "Seagate", "match": "pl-seagate", "bucket": "proposed", "reason": ""}],
        facts=[EVENT_DATE],
        knowledge=make_knowledge(),
        existing_ids=set(),
        recorded="2026-08-03",
        status="catalogued",
    )
    assert verified["status"] == "catalogued"
    assert verified["places"] == [{"id": "pl-seagate", "status": "confirmed"}]

    abandoned, _, _ = build_story(
        anchor={"kind": "place", "id": "pl-seagate", "name": "Seagate"},
        who="Alex",
        title="T",
        account="We sailed around Seagate.",
        extractions=[{"kind": "place", "name": "Seagate", "match": "pl-seagate", "bucket": "proposed", "reason": ""}],
        facts=[EVENT_DATE],
        knowledge=make_knowledge(),
        existing_ids=set(),
        recorded="2026-08-03",
        status="draft",
    )
    assert abandoned["status"] == "draft"
    assert abandoned["places"] == [{"id": "pl-seagate", "status": "proposed"}]


def test_build_story_ids_are_unique() -> None:
    existing = {"story-2026-08-03-01"}
    story, _, _ = build_story(
        anchor=ANCHOR,
        who="Alex",
        title="T",
        account="x",
        extractions=[],
        facts=[EVENT_DATE],
        knowledge=make_knowledge(),
        existing_ids=existing,
        recorded="2026-08-03",
    )
    assert story["id"] == "story-2026-08-03-02"


def test_resolve_pending_facts_asks_the_model_and_validates_with_the_parser() -> None:
    """A typed date answer (kind + verbatim text, value null) is asserted by
    the model and validated by the library — never a hand-rolled parser."""
    from tools.memory import resolve_pending_facts

    class Interpreter:
        def chat(self, system: str, user: str) -> str:
            return '{"answers": [{"text": "the summer of 1970", "value": "1970-06-01", "precision": "approx"}]}'

    facts = [
        {"kind": "event_date", "entity": None, "text": "the summer of 1970", "value": None, "precision": None},
    ]
    out = resolve_pending_facts(Interpreter(), facts)
    assert out[0]["value"] == "1970"
    assert out[0]["precision"] == "approx"


def test_resolve_pending_facts_keeps_unparseable_answers_null_for_a_person() -> None:
    from tools.memory import resolve_pending_facts

    class Interpreter:
        def chat(self, system: str, user: str) -> str:
            return '{"answers": [{"text": "no idea", "value": null, "precision": null}]}'

    facts = [
        {"kind": "event_date", "entity": None, "text": "no idea", "value": None, "precision": None},
    ]
    out = resolve_pending_facts(Interpreter(), facts)
    assert out[0]["value"] is None
    assert out[0]["text"] == "no idea"


def test_resolve_pending_facts_offline_save_keeps_the_fact_pending() -> None:
    from tools.memory import resolve_pending_facts

    facts = [
        {"kind": "dob", "entity": None, "text": "31 July 1979", "value": None, "precision": None},
    ]
    assert resolve_pending_facts(None, facts) == facts


def test_resolve_pending_facts_ignores_a_model_value_the_parser_rejects() -> None:
    from tools.memory import resolve_pending_facts

    class Interpreter:
        def chat(self, system: str, user: str) -> str:
            return '{"answers": [{"text": "sometime", "value": "the other day", "precision": "exact"}]}'

    facts = [
        {"kind": "event_date", "entity": None, "text": "sometime", "value": None, "precision": None},
    ]
    out = resolve_pending_facts(Interpreter(), facts)
    assert out[0]["value"] is None  # the parser rejected the assertion


def test_filter_implausible_suggestions_drops_years_before_the_narrator_was_born() -> None:
    """A quick reply must never offer a date before the narrator was born —
    checkable in code from the facts (docs/coding-standards.md)."""
    from tools.memory import _filter_implausible_suggestions

    assessment = {
        "title": "T",
        "extractions": [],
        "facts": [{"kind": "dob", "entity": "p-alex", "text": "born 1965", "value": "1965", "precision": "year"}],
        "questions": [
            {
                "text": "When did this happen?",
                "why": "",
                "skippable": True,
                "type": "date",
                "date_kind": "event",
                "suggestions": ["the summer of 1960", "1965", "around 1970"],
            },
        ],
    }
    out = _filter_implausible_suggestions(assessment, "Alex", make_knowledge())
    assert out["questions"][0]["suggestions"] == ["1965", "around 1970"]


def test_filter_implausible_suggestions_uses_the_standing_knowledge_dob() -> None:
    from tools.memory import _filter_implausible_suggestions

    people = [
        {"id": "p-alex", "name": "Alex Hale", "aliases": ["Alex"], "dob": "1981-09-15"},
    ]
    assessment = {
        "title": "T",
        "extractions": [],
        "facts": [],
        "questions": [
            {
                "text": "When did this happen?",
                "why": "",
                "skippable": True,
                "type": "date",
                "date_kind": "event",
                "suggestions": ["1975", "1985"],
            },
        ],
    }
    out = _filter_implausible_suggestions(assessment, "Alex", make_knowledge(people=people))
    assert out["questions"][0]["suggestions"] == ["1985"]


def test_filter_implausible_suggestions_never_filters_a_dob_question() -> None:
    from tools.memory import _filter_implausible_suggestions

    assessment = {
        "title": "T",
        "extractions": [],
        "facts": [{"kind": "dob", "entity": "p-alex", "text": "born 1965", "value": "1965", "precision": "year"}],
        "questions": [
            {
                "text": "When were you born?",
                "why": "",
                "skippable": True,
                "type": "date",
                "date_kind": "dob",
                "suggestions": ["the 1960s", "1965"],
            },
        ],
    }
    out = _filter_implausible_suggestions(assessment, "Alex", make_knowledge())
    assert out["questions"][0]["suggestions"] == ["the 1960s", "1965"]


def test_filter_implausible_suggestions_keeps_unparseable_suggestions() -> None:
    from tools.memory import _filter_implausible_suggestions

    assessment = {
        "title": "T",
        "extractions": [],
        "facts": [{"kind": "dob", "entity": "p-alex", "text": "born 1965", "value": "1965", "precision": "year"}],
        "questions": [
            {
                "text": "When did this happen?",
                "why": "",
                "skippable": True,
                "type": "date",
                "date_kind": "event",
                "suggestions": ["when I was little", "the summer of 1970"],
            },
        ],
    }
    out = _filter_implausible_suggestions(assessment, "Alex", make_knowledge())
    assert out["questions"][0]["suggestions"] == ["when I was little", "the summer of 1970"]


def test_assess_keeps_a_people_question_type() -> None:
    """'Who was there' carries type people so the client renders the
    multi-select flow (docs/CHAT-UX.md) — the schema knows three shapes:
    a plain question, a date, and a people multi-select."""
    client = make_client(
        [
            '{"title": "T", "extractions": [], "facts": [{"kind": "event_date", "entity": null, '
            + '"text": "1963", "value": "1963", "precision": "year"}], '
            + '"questions": [{"text": "Who was there?", "why": "", "skippable": true, '
            + '"suggestions": ["Mum"], "type": "people", "date_kind": null}]}',
        ]
    )
    result = assess(client, anchor=ANCHOR, who="Alex", account="We went to Marlock.", knowledge=make_knowledge())
    assert result["questions"][0]["type"] == "people"


def test_exact_precision_is_demoted_to_what_the_value_supports() -> None:
    """An over-claimed "exact" on a bare year must never pin an invented
    day (PRD §6 — a vague memory is never a fake on-this-day)."""
    from tools.memory import _normalize_date_fact

    assert _normalize_date_fact("1963", "exact") == ("1963", "year")
    assert _normalize_date_fact("1963", "month") == ("1963", "year")
    assert _normalize_date_fact("1979-07", "exact") == ("1979-07", "month")
    assert _normalize_date_fact("1981-09-15", "exact") == ("1981-09-15", "exact")
    # a non-ISO phrase can never claim an exact day — "July 1979" must not
    # become 1979-07-01 (reviewer, 2026-08-03; PRD §6)
    assert _normalize_date_fact("July 1979", "exact") == ("1979-07", "month")
    assert _normalize_date_fact("31 July 1979", "exact") == ("1979-07", "month")


def test_build_story_emits_kind_text_for_testimony() -> None:
    """PRD §19.2: every testimony carries kind (audio|text) alongside speaker
    and recorded date — a capture story is typed, so it is text."""
    story, _, _ = build_story(
        anchor=ANCHOR,
        who="Alex",
        title="T",
        account="We went to Marlock.",
        extractions=[],
        facts=[EVENT_DATE],
        knowledge=make_knowledge(),
        existing_ids=set(),
        recorded="2026-08-03",
    )
    assert story["kind"] == "text"


def test_build_story_requires_an_event_date() -> None:
    """A story without an events date cannot be saved — the flow must make
    the narrator provide one. The old fallback (date the story by its
    recording day, approximately) was a fabrication the moment card then
    served as an anniversary (2026-08-05); the recorded day is `recorded`,
    never `date`."""
    with pytest.raises(ValueError, match="events date"):
        build_story(
            anchor=ANCHOR,
            who="Alex",
            title="T",
            account="text",
            extractions=[],
            facts=[],  # no event date — the narrator skipped or declined
            knowledge=make_knowledge(),
            existing_ids=set(),
            recorded="2026-08-03",
        )
