"""Memory — the AI assessment of a contribution and the story it becomes.

Two phases (docs/PRD/MEMORIES.md): the client closes the account open-endedly
("anything else?"), then :func:`assess` runs the model over the finished
account — extracting the people/places/themes the story is *about* (matched
against the standing knowledge, proposing new records, never guessing
identity), asserting any dates/dobs/ages the account states as structured
*facts*, and returning the bounded questions that nail down genuinely missing
detail (date questions typed so the narrator answers them in their own words
— never a hand-rolled picker; the phrase is parsed by the library and the
model). :func:`build_story` then turns the narrator-approved draft into a
canonical story item plus any proposed person/place records — pure, so the
caller writes them through the append-only store (tools/store.py).

No hand-coded date parsers: the model asserts *what* a phrase is (a birth
date, an event date, an age) and *where* it is; dateparser validates and
normalizes the phrase against the archive's locale (LOFT_LOCALE, default
en_GB — DMY); phrases it cannot parse become facts with null value that a person
resolves.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any, Literal, Protocol, cast

from pipeline.model.ai_client import AIClientError, json_object
from tools.anchor import Anchor
from tools.assessment import Assessment
from tools.assessment_fact import FACT_KINDS, AssessmentFact
from tools.dated_fact import DatedFact
from tools.extraction import BUCKETS, KINDS, Extraction
from tools.fact_answer import FactAnswer
from tools.pending_fact import PendingFact
from tools.question import MAX_QUESTIONS, MAX_SUGGESTIONS
from tools.records import Item, Person, Place
from tools.ref import Ref, RefStatus
from tools.theme import Theme

MAX_ASSESS_ATTEMPTS = 3


class ChatClient(Protocol):
    """The model seam — satisfied by AIClient and by test doubles."""

    # instance method using self

    def chat(self, system: str, user: str) -> str: ...


_SYSTEM_PROMPT = f"""\
You are the contribution assistant for a private family archive. A contributor \
has told a story about something in the archive. Your job is ONE assessment with \
four parts: a suggested title; the extractions (the people, places, themes and \
artifacts the story is about); the facts (the dates, dates of birth and ages the \
account states); and up to {MAX_QUESTIONS} questions.

Extraction rules. Link an entity only when the story is about it: a passing \
mention is not a link, and a name that merely shares a name or alias with \
someone in the standing knowledge is NOT a match — same name, different person. \
A kinship term ("Dad", "Mum", "Aunt X", "Grandma") names the WRITER's own \
relative: it matches only where the account evidences the writer's own family. \
Ask a question only when it is genuinely ambiguous which person is meant, and \
never guess an identity — an unnamed or ambiguous person is a question or stays \
unresolved; that rule binds the matches you propose, never the suggestions a \
question offers. When in doubt between a link and a mention, choose unresolved: \
a false link is worse than no link. A person mentioned near a place is not \
automatically at that place, and presence must be plausible for the story's time. \
The anchor is the archive record the story is filed under: never an extraction.

An entity the story is about that is not in the standing knowledge — of any \
kind — is listed with "match": null and bucket "proposed": a new proposed record \
the narrator verifies in the review. Artifacts (items) are the named objects the \
story mentions — a boat, a document, a letter, a photograph; a meal, a \
celebration or a generic thing is not an artifact. They are linked by title; one \
the story mentions that is not in the catalog stays "unresolved", and no \
artifact record is ever created. Bucket meanings: "proposed" = a confident link \
worth one review tap; "question" = genuinely ambiguous, needs a question; \
"unresolved" = leave as plain text.

Fact rules. Assert every date, date of birth and age the account STATES, and \
never invent one. "kind": "dob" for a date of birth (entity = the person's id \
when you can match them to the standing knowledge, else null), "event_date" for \
when the events happened, "age" for an age the narrator gives about themselves. \
Quote the exact phrase as "text"; give the best "value" (ISO: a full date must \
be YYYY-MM-DD, a month YYYY-MM, a year YYYY — never a phrase, which would lose \
its day; or an integer for an age) and an honest "precision" (exact | month | \
year | approx). Incomplete forms ("the summer of 1979", "born in 1979") get what \
is there. If a phrase makes no sense as a date at all, "value": null.

Question rules. Ask only what is missing and matters, at most {MAX_QUESTIONS}; \
every question is skippable and nothing is required. A date the account states \
is asserted as a fact instead, and a year computable from an asserted date of \
birth and age is not asked for. Ask for: the event date; who was actually present; the identity of unnamed \
people; place precision ("the old ford" — which one?); the connection of a \
narrator not in the standing knowledge — ask this whenever the contributor is \
absent from the standing knowledge, unless the story itself states the relation; \
and a specific artifact the story names that is not in the catalog — a \
particular boat, object or document — since that is how its archive page gets \
built. A boat is no more worthy than a letter, a photograph or a tool; the same \
goes for a named person or place that matters to the story. A question whose \
answer is one or more people carries "type": "people" — the narrator picks names \
from the cast, any number — so its "suggestions" are the likely people; a \
question needing a date carries "type": "date" and "date_kind": "dob" when \
asking for a date of birth, else "event", and the narrator answers it in their \
own words; every other question carries "type": null. Every question carries up \
to {MAX_SUGGESTIONS} short "suggestions" the narrator can tap instead of typing: \
give them only where they are plausible for this narrator — never a date before \
their birth, and consistent with their stated age and with the story's stated \
time; with neither known, leave them out. A date of birth is asked politely, \
never required, and only when it would disambiguate presence or date a story.

If nothing is missing, "questions" is an empty list.

Respond with ONLY this JSON: {{"title": string, "extractions": [{{"kind": \
"{"|".join(KINDS)}", "name": string, "match": "<id>"|null, "bucket": \
"{"|".join(BUCKETS)}", "reason": string}}], "facts": [{{"kind": \
"{"|".join(FACT_KINDS)}", "entity": "<person id>"|null, "text": "<verbatim \
quote>", "value": "<date or integer>"|null, "precision": "exact|month|year| \
approx"|null}}], "questions": [{{"text": string, "why": string, \
"skippable": true, "suggestions": [string], "type": "date"|"people"|null, \
"date_kind": "dob"|"event"|null}}]}}`"""


_REVIEWER_SYSTEM_PROMPT = """\
You are the review pass for a family-archive contribution. You are given the \
story, the standing knowledge, and the assessor's proposed extractions, facts \
and questions. Find ONLY genuine rule violations:
- an extraction links an entity the story merely mentions (a passing mention, \
  or a same-name person in a different family: the narrator's own \"Dad\", \
  \"Mum\", \"Aunt Nora\", a neighbour) instead of being about it;
- a match that presence or the story's own time makes impossible;
- a question that the account, the facts, or the standing knowledge already \
  answers;
- a date question when the year is computable: the facts include a date of \
  birth and an age for the narrator, or the standing knowledge has their date \
  of birth and the account gives an age;
- the account gave an age, no date of birth is known or stated, and no \
  question asks politely for the date of birth or the year (with a decline \
  option);
- a date, date of birth, or age stated in the account that is not asserted in \
  the facts;
- the narrator is not in the standing knowledge and no question asks how they \
  are connected to the family (unless the story already makes it obvious);
- a specific new artifact named in the story (a particular boat, object, or \
  document not in the catalog) with no question asking about it.
Be conservative: do NOT flag style, or anything a reasonable person could \
confirm. A clean assessment gets an empty list.

Respond with ONLY this JSON: {"violations": [string]} — each a short, \
specific description of what to fix."""


class ElicitationError(RuntimeError):
    """Raised when the assessment cannot be produced or is malformed."""


@dataclass(frozen=True)
class Knowledge:
    """The standing archive an assessment works against — one object, one
    name, one home for the invariant (docs/coding-standards.md: groups that
    travel together are a type, never repeated parallel parameters). The
    projection's plain dicts are normalized once, in from_projection, into
    typed records that carry their own behavior — the members are never
    re-parsed by the callers."""

    people: tuple[Person, ...] = ()
    places: tuple[Place, ...] = ()
    themes: tuple[Theme, ...] = ()
    items: tuple[Item, ...] = ()

    @classmethod
    def from_projection(
        cls,
        people: Iterable[Mapping[str, Any]],
        places: Iterable[Mapping[str, Any]],
        themes: Iterable[Mapping[str, Any]],
        items: Iterable[Mapping[str, Any]],
    ) -> Knowledge:
        """The typed view of the projection — the one conversion point for
        the server's plain dicts (docs/coding-standards.md: members are
        typed records; callers never re-parse them)."""
        return cls(
            people=tuple(Person.from_dict(dict(p)) for p in people),
            places=tuple(Place.from_dict(dict(pl)) for pl in places),
            themes=tuple(Theme.from_dict(dict(t)) for t in themes),
            items=tuple(Item.from_dict(dict(i)) for i in items),
        )

    def speaker_for(self, who: str) -> str | None:
        """Match the contributor's self-name against the cast (name or alias)."""
        person = self.person_named(who)
        return person.id if person else None

    def person_named(self, name: str) -> Person | None:
        """The cast member whose name or alias is this name — the one way a
        person is named (a story mention reuses them, never mints a duplicate)."""
        wanted = name.strip().lower()
        if not wanted:
            return None
        return next((p for p in self.people if self._is_named(p, wanted)), None)

    def proposed_person_named(self, name: str) -> Person | None:
        """The queued proposal whose name or alias is this name — two stories
        mentioning the same bare kinship term share ONE proposed record: a
        fresh proposed id per story makes the projection's name-dedup drop the
        second mint, and its story's ref then dangles at publish."""
        wanted = name.strip().lower()
        if not wanted:
            return None
        return next((p for p in self.people if p.status == "proposed" and self._is_named(p, wanted)), None)

    def place_named(self, name: str) -> Place | None:
        """The standing place whose name is this name — a story mention reuses
        it, never mints a duplicate (the moored-barges ×3 came from minting one
        id per story mention, 2026-08-05)."""
        wanted = name.strip().lower()
        if not wanted:
            return None
        return next((pl for pl in self.places if pl.name.strip().lower() == wanted), None)

    def person(self, person_id: str) -> Person | None:
        """The cast member with this id — the record a model-matched person ref
        must name."""
        return next((p for p in self.people if p.id == person_id), None)

    def place(self, place_id: str) -> Place | None:
        """The standing place with this id — the record a model-matched place
        ref must name."""
        return next((pl for pl in self.places if pl.id == place_id), None)

    def theme(self, theme_id: str) -> Theme | None:
        """The curated theme with this id — themes are curated arrangements, so
        only a real one may be linked."""
        return next((t for t in self.themes if t.id == theme_id), None)

    def item(self, item_id: str) -> Item | None:
        """The catalog item with this id — the artifact a story links by title."""
        return next((it for it in self.items if it.id == item_id), None)

    def narrator_dob(self, speaker_id: str | None) -> str | None:
        """The narrator's date of birth from the standing knowledge, when the
        cast records it — used to keep suggestions plausible (a quick reply
        is never a date before the narrator was born)."""
        if not speaker_id:
            return None
        person = self.person(speaker_id)
        return person.dob.date if person and person.dob else None

    def render(self) -> str:
        """Compact render of the cast/places/themes/items for the model
        prompt."""
        lines = ["People:"]
        for p in self.people:
            info = [f"  {p.id} — {p.name}"]
            if p.aliases:
                info.append(f"(aliases: {', '.join(p.aliases)})")
            if p.dob:
                info.append(f"(born {p.dob.date})")
            lines.append(" ".join(info))
        lines.append("Places:")
        lines += [f"  {pl.id} — {pl.name}" for pl in self.places]
        lines.append("Themes:")
        lines += [f"  {t.id} — {t.title}" for t in self.themes]
        lines.append("Artifacts:")
        lines += [f"  {it.id} — {it.title} ({it.type})" for it in self.items]
        return "\n".join(lines)

    @staticmethod
    def _is_named(person: Person, wanted: str) -> bool:
        """Name or alias, case-insensitive — the one way a person is named."""
        return person.name.strip().lower() == wanted or any(a.strip().lower() == wanted for a in person.aliases)


def _anchor_line(anchor: Anchor) -> str:
    kind = anchor.kind
    return f"Anchor (where the contributor started): {kind} — {anchor.label()}"


class _AssessmentReview:
    """The code-checkable review of one assessment — owns the assessment and
    its context (the narrator and the standing knowledge), the data clump
    the deterministic guards, the plausibility filter and the model review
    pass all read (docs/coding-standards.md: deterministic checks beat
    model judgment)."""

    def __init__(self, assessment: Assessment, who: str, knowledge: Knowledge) -> None:
        self.assessment = assessment
        self.who = who
        self.knowledge = knowledge

    def narrator_dob(self) -> str | None:
        """The narrator's date of birth for the plausibility guard — the
        assessment's own dob fact first (the one being established), then
        the standing knowledge's."""
        speaker_id = self.knowledge.speaker_for(self.who)
        for fact in self.assessment.facts:
            if fact.is_dob() and fact.value and fact.entity in (None, speaker_id):
                return str(fact.value)
        return self.knowledge.narrator_dob(speaker_id)

    def filter_implausible_suggestions(self) -> Assessment:
        """Deterministic guard on date-question suggestions (docs/coding-
        standards.md: deterministic checks beat model judgment): never offer
        a year before the narrator was born — their dob is in the
        assessment's facts or the standing knowledge. Suggestions the parser
        cannot date are kept; dob questions (the date is being asked) are
        never filtered."""
        dob_value = self.narrator_dob()
        if not dob_value:
            return self.assessment
        try:
            dob_year = int(str(dob_value)[:4])
        except (TypeError, ValueError):
            return self.assessment
        return self.assessment.with_plausible_suggestions(dob_year)

    def violations(self) -> list[str]:
        """Rule violations checkable in code — no model judgment needed.
        These feed the same redo-with-feedback loop as the reviewer's
        findings."""
        ages = [f.value for f in self.assessment.facts if f.is_age() and isinstance(f.value, int)]
        violations = self._check_narrator_unknown()
        violations += self._check_age_without_dob(ages)
        violations += self._check_event_date_rules(ages)
        violations += self._check_new_item_question()
        return violations

    def model_violations(self, client: ChatClient, anchor: Anchor, account: str) -> list[str]:
        """A second, cheap model pass reviews the assessment for rule
        violations (mentions linked, impossible matches, redundant
        questions). Returns the violations to feed back — empty means the
        assessment stands."""
        user = "\n\n".join(
            [
                _anchor_line(anchor),
                f"Contributor: {self.who or 'unknown'}",
                f"The story (verbatim):\n{account}",
                "Standing knowledge:\n" + self.knowledge.render(),
                "The assessor's output to review:\n" + json.dumps(self.assessment.to_dict(), ensure_ascii=False),
            ]
        )
        try:
            raw = client.chat(_REVIEWER_SYSTEM_PROMPT, user)
            parsed = json_object(raw)
            violations = parsed.get("violations", [])
            if not isinstance(violations, list):
                return []
            return [str(v).strip()[:200] for v in violations if isinstance(v, str) and v.strip()]
        except AIClientError:
            # a failed review pass never blocks the capture — the narrator's own
            # review is the final gate
            return []

    def _check_narrator_unknown(self) -> list[str]:
        """A narrator outside the standing knowledge must be asked how they
        connect — the account cannot be placed otherwise."""
        violations: list[str] = []
        if self.who.strip() and self.knowledge.speaker_for(self.who) is None:
            questions = " ".join(q.text for q in self.assessment.questions).lower()
            if not any(w in questions for w in ("connect", "related", "relationship", "family")):
                violations.append(
                    "the narrator is not in the standing knowledge and no question asks "
                    "how they are connected to the family"
                )
        return violations

    def _check_age_without_dob(self, ages: list[int]) -> list[str]:
        """An age in the account must pair with a date of birth — the age is
        anchored to the narrator's birth year, so the flow must establish the
        dob or ask for it."""
        violations: list[str] = []
        if ages:
            known_dob = self.knowledge.narrator_dob(self.knowledge.speaker_for(self.who))
            dob_in_facts = any(f.is_dob() and f.value for f in self.assessment.facts)
            if known_dob or dob_in_facts:
                if self._date_question_asked():
                    violations.append(
                        "a date question is asked although the year is computable from the "
                        "narrator's date of birth and age"
                    )
            elif not self._date_question_asked():
                violations.append(
                    "the account gave an age and no date of birth is known or stated — ask "
                    "politely for the date of birth or the year"
                )
        return violations

    def _check_event_date_rules(self, ages: list[int]) -> list[str]:
        """The events-date rules — a date equal to the telling day is only
        legitimate when the narrator's own words stated it; and when no events
        date exists and nothing derives one, the (skippable) date question
        must stay in the flow, never dropped."""
        violations: list[str] = []
        event_dates = tuple(f for f in self.assessment.facts if f.is_event_date() and f.value)
        known_dob = self.knowledge.narrator_dob(self.knowledge.speaker_for(self.who))
        dob_in_facts = any(f.is_dob() and f.value for f in self.assessment.facts)
        if event_dates:
            violations += self._fabricated_today_violations(event_dates)
        elif not (ages and (known_dob or dob_in_facts)):
            violations += self._missing_event_date_violations()
        return violations

    def _check_new_item_question(self) -> list[str]:
        """A specific new artifact the story names deserves a "tell me more"
        question — checkable in code from the extractions (item, no match)."""
        violations: list[str] = []
        new_items = [ex for ex in self.assessment.extractions if ex.is_new_item()]
        if new_items:
            questions = " ".join(q.text for q in self.assessment.questions).lower()
            if not any(ex.name.lower() in questions for ex in new_items):
                violations.append(
                    "a specific new artifact is named in the story and no question asks about it "
                    '("tell me more" — that is how its archive page gets built)'
                )
        return violations

    def _date_question_asked(self) -> bool:
        return any(q.asks_for_a_date() for q in self.assessment.questions)

    def _missing_event_date_violations(self) -> list[str]:
        """No events date and nothing to derive one from — the issue must stay
        pursued, never forced and never dropped (user: every question is
        skippable, but the flow keeps narrowing the issue until the narrator
        answers — even with a "leave it for now"; a story without a date
        would otherwise slip through). The question is skippable: the
        narrator answers in their own words or declines, and the item stays
        undated until a later pass."""
        if any(q.asks_for_the_events_date() for q in self.assessment.questions):
            return []
        return [
            "no events date is established — keep the (skippable) date question for when "
            "the events happened in the questions; the narrator answers in their own "
            "words, and declining is allowed, but the issue is not dropped"
        ]

    @staticmethod
    def _fabricated_today_violations(event_dates: tuple[AssessmentFact, ...]) -> list[str]:
        """A date equal to the telling day is only legitimate when the
        narrator's own words stated it — a diary-style entry that really
        happened that day. The verbatim is the discriminator: "Today" / the
        date itself in the answer, never a fabricated value with no such
        words. The events date must be the narrator's, never the telling day —
        the model fabricating today as the event date is exactly how the
        moment card came to serve "0 years ago this week" (2026-08-05)."""
        violations: list[str] = []
        today = date.today().isoformat()
        todayish = ("today", "tonight", "this morning", "this evening", "this week", "just now", "now", "earlier today")
        for fact in event_dates:
            value = str(fact.value)
            if value in (today, today[:7], today[:4]):
                verbatim = fact.text.strip().lower()
                if value.lower() not in verbatim and not any(w in verbatim for w in todayish):
                    violations.append(
                        "the events date is the telling day and the narrator never stated it — a "
                        "fabrication; quote the date from the account itself or keep the events "
                        "date question (skippable — the narrator answers in their own words, and "
                        "'I don't remember' is a legitimate answer) in the questions"
                    )
                    break
        return violations


_PENDING_FACT_PROMPT = """\
You are the date interpreter for a family archive. The narrator answered a \
date question in their own words; each answer must become a structured date \
fact.

Rules:
- "value": the date the answer states, as ISO text ("1981-09-15", \
"1979-07", "1979") — a full date MUST be emitted as YYYY-MM-DD, never as a \
phrase ("31 July 1979" would lose its day) — or null when the answer \
contains no usable date ("I'd rather not say", "no idea").
- "precision": "exact" | "month" | "year" | "approx" — only as precise as \
the words are ("31 July 1979" = exact; "July 1979" = month; "the summer of \
1970" = approx; "1979" = year). Never claim a precision the words do not \
support.
- "text": quote the answer verbatim.
Never invent a date the answer does not state.

Respond with ONLY this JSON: {"answers": [{"text": string, "value": \
string|null, "precision": "exact"|"month"|"year"|"approx"|null}]}"""


def resolve_pending_facts(
    client: ChatClient | None, raw_facts: Iterable[Mapping[str, Any]]
) -> tuple[AssessmentFact, ...]:
    """Fill the date facts the narrator answered in their own words: a fact
    with kind dob/event_date, verbatim text and no value yet goes to the
    model to assert value and precision; the library validates both
    (docs/coding-standards.md: the model asserts, the library parses). An
    answer the model or the parser cannot date stays null — a person's word
    resolves it. Never runs without a client (an offline save keeps the
    fact pending)."""
    facts = AssessmentFact.from_list(list(raw_facts))
    pending = PendingFact.all_from(facts)
    if not pending or client is None:
        return facts
    answers = _answer_pending_facts(client, pending)
    if answers is None:
        return facts
    return _merge_pending_answers(facts, answers)


def _answer_pending_facts(client: ChatClient, pending: tuple[PendingFact, ...]) -> tuple[FactAnswer, ...] | None:
    """Ask the model to assert value and precision for the pending facts.
    None when the model or the JSON parsing fails — the caller keeps the
    facts pending (an offline save never runs without a client)."""
    try:
        raw = client.chat(
            _PENDING_FACT_PROMPT,
            json.dumps([fact.to_dict() for fact in pending], ensure_ascii=False),
        )
        parsed = json_object(raw)
        answers = parsed.get("answers") if isinstance(parsed, dict) else None
        if not isinstance(answers, list):
            return None
        return FactAnswer.from_list(answers)
    except AIClientError:
        return None


def _merge_pending_answers(
    facts: tuple[AssessmentFact, ...],
    answers: tuple[FactAnswer, ...],
) -> tuple[AssessmentFact, ...]:
    """Fold the model's answers into the pending facts: a pending fact
    whose verbatim text the model answered gets the validated value and
    precision (the library validates both — the model asserts, the library
    parses); an answer the model or the parser cannot date stays null — a
    person's word resolves it."""
    by_text = {answer.text: answer for answer in answers}
    out: list[AssessmentFact] = []
    for fact in facts:
        answer = by_text.get(fact.text.strip()) if fact.is_pending() else None
        dated = answer.dated() if answer else None
        out.append(replace(fact, value=dated.date, precision=dated.precision) if dated else fact)
    return tuple(out)


def assess(
    client: ChatClient,
    *,
    anchor: Anchor,
    who: str,
    account: str,
    knowledge: Knowledge,
) -> Assessment:
    """Run the model over the finished account; returns the validated
    assessment {title, extractions, facts, questions}.

    The single production call self-corrects: deterministic rule checks and a
    second cheap model pass review the output, and genuine violations are fed
    back for a bounded redo — never sampling-twice-and-picking.
    """
    user = "\n\n".join(
        [
            _anchor_line(anchor),
            f"Contributor: {who or 'unknown'}",
            f"The story so far (verbatim):\n{account}",
            "Standing knowledge:\n" + knowledge.render(),
        ]
    )
    assessment: Assessment | None = None
    for attempt in range(MAX_ASSESS_ATTEMPTS):
        try:
            raw = client.chat(_SYSTEM_PROMPT, user)
            parsed = json_object(raw)
        except AIClientError as e:
            raise ElicitationError(f"assessment failed: {e}") from e
        assessment = _validate_assessment(parsed)
        if attempt >= MAX_ASSESS_ATTEMPTS - 1:
            break  # last attempt: accept the best effort
        review = _AssessmentReview(assessment, who, knowledge)
        violations = review.violations()
        violations += review.model_violations(client, anchor, account)
        if not violations:
            break
        user = (
            user
            + "\n\nA reviewer found these problems in your assessment. Fix them and re-respond "
            + "with the corrected assessment JSON:\n- "
            + "\n- ".join(violations)
        )
    assert assessment is not None, "the assessment loop always runs at least once"
    return _AssessmentReview(assessment, who, knowledge).filter_implausible_suggestions().strip_kinship_matches()


def _validate_assessment(parsed: Any) -> Assessment:
    """The model's JSON, validated into the assessment record — a malformed
    shape fails loudly with a named error, never a confusing downstream
    crash."""
    if not isinstance(parsed, dict):
        raise ElicitationError(f"assessment is not an object: {parsed!r}")
    try:
        return Assessment.from_dict(parsed)
    except ValueError as e:
        raise ElicitationError(str(e)) from e


# ---------------------------------------------------------------------------
# build_story — the narrator-approved draft becomes a canonical story item
# ---------------------------------------------------------------------------


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:40] or "new"


class StoryLinks:
    """The story's links from the narrator-approved assessment — the refs by
    kind and the proposed records minted for it. The class owns the link
    rules: the anchor and the kept extractions become refs (one per entity),
    a mention links to its standing record or mints a proposed record, and a
    catalogued story never confirms a link the reader cannot see — an item ref
    is downgraded to ``proposed`` when its artifact is still a draft
    (2026-08-05: story-2026-08-03-05 confirmed a draft object-sb-mirosa,
    leaving a dangling link)."""

    def __init__(self, *, verified: bool, all_ids: set[str]) -> None:
        self.ref_status: RefStatus = "confirmed" if verified else "proposed"
        self.all_ids = all_ids
        self.people: list[Ref] = []
        self.places: list[Ref] = []
        self.themes: list[Ref] = []
        self.items: list[Ref] = []
        self.new_people: list[Person] = []
        self.new_places: list[Place] = []

    def anchor(self, page: Anchor) -> None:
        """The page the narrator started from is their own aboutness evidence."""
        if not page.id:
            return
        if page.kind == "person":
            self._ref(self.people, page.id)
        elif page.kind == "place":
            self._ref(self.places, page.id)
        elif page.kind == "theme":
            self._ref(self.themes, page.id)

    def add(self, extraction: Extraction, knowledge: Knowledge) -> None:
        """One kept extraction becomes its ref — linked to the standing record
        the model matched, or minted as a proposed record when none matches."""
        if extraction.kind == "person":
            self._person(extraction, knowledge)
        elif extraction.kind == "place":
            self._place(extraction, knowledge)
        elif extraction.kind == "theme":
            self._theme(extraction, knowledge)
        else:
            self._item(extraction, knowledge)

    def speaker(self, who: str, known_id: str | None, dob: DatedFact | None) -> str:
        """The story's told_by — the known narrator, or a proposed person
        record minted for a narrator outside the knowledge (their dob rides
        along when the account offered one)."""
        if known_id:
            return known_id
        return self.mint_person(who.strip() or "Guest", dob=dob).id

    def mint_person(self, name: str, dob: DatedFact | None = None) -> Person:
        """The archive record for a person the story introduces — proposed,
        never confirmed (docs/PRD/MEMORIES.md)."""
        person = Person(
            id=self._unique_id("p", _slug(name)),
            name=name.strip(),
            relation="added from a story",
            hue="amber",
            dob=dob,
            status="proposed",
        )
        self.all_ids.add(person.id)
        self.new_people.append(person)
        return person

    def mint_place(self, name: str) -> Place:
        """The archive record for a place the story introduces — proposed,
        location unknown (docs/PRD/MEMORIES.md)."""
        place = Place(
            id=self._unique_id("pl", _slug(name)),
            name=name.strip(),
            note="Added from a story — location unknown.",
            status="proposed",
        )
        self.all_ids.add(place.id)
        self.new_places.append(place)
        return place

    def _person(self, extraction: Extraction, knowledge: Knowledge) -> None:
        """A person mention: the model's match, a standing cast member named
        the same, or a proposed record. A bare kinship term is the writer's own
        relative, never a cast alias — it stays proposed for the writer to
        identify (the kinship filter's strip must stay effective). A kinship
        term never resolves to a CONFIRMED cast member — that alias could be
        the wrong relative (writer-relative resolution is the option-C task) —
        but two stories mentioning the same "Grandma" must share ONE proposed
        record."""
        if extraction.match and knowledge.person(extraction.match):
            self._ref(self.people, extraction.match)
            return
        name = extraction.name
        if extraction.is_kinship_term():
            existing = knowledge.proposed_person_named(name)
        else:
            # reuse a standing cast member by name/alias before minting — a
            # fresh id per story mention fragments the cast (the person analog
            # of the place name-dedup)
            existing = knowledge.person_named(name)
        self._ref(self.people, existing.id if existing else self.mint_person(name).id)

    def _place(self, extraction: Extraction, knowledge: Knowledge) -> None:
        """A place mention: the model's match, a standing place named the same,
        or a proposed record (a fresh id per story mention multiplies one place
        into many — the moored-barges ×3)."""
        if extraction.match and knowledge.place(extraction.match):
            self._ref(self.places, extraction.match)
            return
        existing = knowledge.place_named(extraction.name)
        self._ref(self.places, existing.id if existing else self.mint_place(extraction.name).id)

    def _theme(self, extraction: Extraction, knowledge: Knowledge) -> None:
        """Themes are curated arrangements — proposed only, never auto-created."""
        if extraction.match and knowledge.theme(extraction.match):
            self._ref(self.themes, extraction.match)

    def _item(self, extraction: Extraction, knowledge: Knowledge) -> None:
        """Artifacts are linked by title; a mention without a catalog match
        stays unresolved — never auto-create artifact records. A draft artifact
        is hidden from everyone but its owner, so a confirmed link to it would
        dangle: it stays proposed until the artifact is catalogued
        (2026-08-05)."""
        item = knowledge.item(extraction.match) if extraction.match else None
        if item is None:
            return
        status: RefStatus = self.ref_status
        if status == "confirmed" and item.status == "draft":
            status = "proposed"
        self._ref(self.items, item.id, status=status)

    def _ref(self, refs: list[Ref], record_id: str, status: RefStatus | None = None) -> None:
        """One ref per entity — the anchor and an extraction may name the same
        one; the first link wins."""
        if any(ref.id == record_id for ref in refs):
            return
        refs.append(Ref(record_id, status or self.ref_status))

    def _unique_id(self, prefix: str, slug: str) -> str:
        """The next free id for the slug — a name the archive already minted an
        id for takes the next suffix, so one story mention never mints a second
        record for the same name."""
        candidate = f"{prefix}-{slug}"
        if candidate not in self.all_ids:
            return candidate
        n = 2
        while f"{candidate}-{n}" in self.all_ids:
            n += 1
        return f"{candidate}-{n}"


@dataclass(frozen=True)
class Fact:
    """A stated fact the story records (kind: dob / event_date / age) —
    typed and serialisable to the sidecar's fact shape. The verbatim text
    is provenance, never parsed; the value/precision are the validated
    parse (dateparser — no hand-rolled date parsers, docs/coding-
    standards.md)."""

    kind: str
    text: str
    value: str | None
    precision: str | None
    entity: str | None = None
    status: Literal["confirmed", "proposed"] = "proposed"
    source: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Fact:
        kind = str(raw.get("kind", ""))
        if kind not in FACT_KINDS:
            raise ValueError(f"unknown fact kind: {kind!r}")
        status = str(raw.get("status", "proposed"))
        if status not in ("confirmed", "proposed"):
            raise ValueError(f"bad fact status: {status!r}")
        return cls(
            kind=kind,
            text=str(raw.get("text", "")),
            value=raw.get("value"),
            precision=raw.get("precision"),
            entity=raw.get("entity"),
            status=cast(Literal["confirmed", "proposed"], status),
            source=str(raw.get("source", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "entity": self.entity,
            "text": self.text,
            "value": self.value,
            "precision": self.precision,
            "status": self.status,
            "source": self.source,
        }


@dataclass(frozen=True)
class Story:
    """A story contribution as the capture flow's domain object
    (docs/PRD/MEMORIES.md): the sidecar's shape with typed links. The
    class owns the links invariant: a catalogued story never confirms a
    link the reader cannot see — an item ref is downgraded to ``proposed``
    when its artifact is still a draft (2026-08-05: story-2026-08-03-05
    confirmed a draft object-sb-mirosa, leaving a dangling link)."""

    story_id: str
    title: str
    date: str
    date_precision: str
    recorded: str
    description: str
    story: str
    transcription: str
    told_by: str
    comment_on: str | None
    chat: dict[str, Any] | None
    source: str
    people: tuple[Ref, ...]
    places: tuple[Ref, ...]
    themes: tuple[Ref, ...]
    items: tuple[Ref, ...]
    facts: tuple[Fact, ...]
    status: str

    @classmethod
    def refs_from_assessment(
        cls,
        *,
        anchor: Anchor,
        extractions: Iterable[Extraction],
        knowledge: Knowledge,
        verified: bool,
        all_ids: set[str],
    ) -> StoryLinks:
        """The story's links from the narrator-approved assessment: the
        anchor and the kept extractions become refs (one per entity), and
        newly introduced people/places mint proposed records."""
        links = StoryLinks(verified=verified, all_ids=all_ids)
        links.anchor(anchor)
        for extraction in extractions:
            links.add(extraction, knowledge)
        return links

    def to_sidecar(self) -> Item:
        """The archive sidecar the capture server writes — the app and the
        tests read this shape."""
        return Item(
            {
                "id": self.story_id,
                "type": "story",
                "kind": "text",  # PRD §19.2: every testimony carries kind (audio|text)
                "title": self.title,
                "date": self.date,
                "date_precision": self.date_precision,
                "recorded": self.recorded,
                "description": self.description,
                "story": self.story,
                "transcription": self.transcription,
                "told_by": self.told_by,
                "comment_on": self.comment_on,
                **({"chat": self.chat} if self.chat else {}),  # the transcript behind a draft
                "source": self.source,
                "people": [ref.to_dict() for ref in self.people],
                "places": [ref.to_dict() for ref in self.places],
                "themes": [ref.to_dict() for ref in self.themes],
                "items": [ref.to_dict() for ref in self.items],
                "facts": [fact.to_dict() for fact in self.facts],
                "sensitive": False,
                "status": self.status,
                "assets": [],
                "created": self.recorded,
                "created_at": datetime.now().isoformat(timespec="seconds"),  # the recent feed's tie-break
            }
        )


@dataclass(frozen=True)
class StoryFacts:
    """The assessed facts sorted into the story's date inputs: the facts
    recorded verbatim for the keeper, the asserted events date, and the dob
    and ages that derive the events year when no date is stated. One record
    instead of the positional 5-tuple the collector used to return."""

    story_facts: tuple[Fact, ...]
    event_date: str | None
    event_precision: str | None
    dob: DatedFact | None
    ages: tuple[int, ...]


def _next_story_id(recorded: str, existing: set[str]) -> str:
    prefix = f"story-{recorded}"
    n = 1
    while f"{prefix}-{n:02d}" in existing:
        n += 1
    return f"{prefix}-{n:02d}"


@dataclass(frozen=True)
class StoryRequest:
    """A story-capture request — the narrator-approved draft the capture
    flow saves (docs/PRD/MEMORIES.md): the account, its assessment, and
    the save's identity. The group travels together into both build_story
    entry points (docs/coding-standards.md: a group that travels together
    is a type)."""

    anchor: Anchor
    who: str
    title: str
    account: str
    extractions: tuple[Extraction, ...]
    facts: tuple[AssessmentFact, ...]
    status: str = "draft"
    story_id: str | None = None
    chat: dict[str, Any] | None = None


@dataclass(frozen=True)
class BuiltStory:
    """A completed story draft and the identity records it proposes: the way
    `build_story`'s answer travels (three lists in one hand are a silent swap
    away from three wrong ones)."""

    story: Item
    new_people: tuple[Person, ...]
    new_places: tuple[Place, ...]


def build_story(
    *,
    request: StoryRequest,
    knowledge: Knowledge,
    existing_ids: set[str],
    recorded: str | None = None,
) -> BuiltStory:
    """Turn the narrator-approved draft into the story and its proposed records.

    Pure: the caller writes the sidecar and the proposed records through the
    append-only store. The operator verifies the AI's guesses in the same
    flow (docs/PRD/MEMORIES.md): a completed, reviewed save is
    ``catalogued`` with ``confirmed`` refs; an abandoned one is ``draft``
    with ``proposed`` refs. Facts decide the dates: an asserted event date
    wins; a date of birth plus an age derives the events year (dob + age,
    arithmetic only); a dob the narrator asserts in answer to a direct
    question is confirmed, one merely stated in prose is proposed
    (docs/PRD/MEMORIES.md — no hand-coded date parsers).
    """
    verified = request.status == "catalogued"
    recorded = recorded or date.today().isoformat()
    # an ongoing draft keeps ONE id through its life: the client's auto-saves
    # and the final save supersede the same story in place (append-only —
    # every version stays, the newest wins; docs/TECHSPEC.md §3). A fresh
    # save without an id mints the next story id.
    story_id = request.story_id or _next_story_id(recorded, existing_ids)
    speaker_id = knowledge.speaker_for(request.who)

    # facts decide the story's date and the dob proposals
    collected = _collect_story_facts(request.facts, speaker_id)
    event = _derive_event_year(collected)

    # the links: built by the Story domain object, which enforces the
    # invariant that a catalogued story never confirms a link to an
    # artifact the reader cannot see (a draft item stays proposed)
    all_ids = set(existing_ids) | {p.id for p in knowledge.people}
    all_ids |= {pl.id for pl in knowledge.places} | {t.id for t in knowledge.themes}
    links = Story.refs_from_assessment(
        anchor=request.anchor,
        extractions=request.extractions,
        knowledge=knowledge,
        verified=verified,
        all_ids=all_ids,
    )
    speaker = links.speaker(request.who, speaker_id, collected.dob)

    story = Story(
        story_id=story_id,
        title=request.title.strip() or f"A story about {request.anchor.name or 'the archive'}",
        date=event.date,
        date_precision=event.precision,
        recorded=recorded,
        description="",
        story=request.account.strip(),
        transcription="",
        told_by=speaker,
        comment_on=request.anchor.id if request.anchor.kind == "item" else None,
        chat=request.chat,
        source=f"Site contribution, {recorded}",
        people=tuple(links.people),
        places=tuple(links.places),
        themes=tuple(links.themes),
        items=tuple(links.items),
        facts=collected.story_facts,
        status=request.status,
    )
    return BuiltStory(story.to_sidecar(), tuple(links.new_people), tuple(links.new_places))


def _collect_story_facts(facts: Iterable[AssessmentFact], speaker_id: str | None) -> StoryFacts:
    """Sort the assessed facts into the story's date inputs and dob
    proposals: the asserted events date wins; the dob is recorded whether
    or not it could be parsed — a phrase the parser rejected still needs a
    person's word; ages collect for the dob + age arithmetic."""
    story_facts: list[Fact] = []
    event_date: str | None = None
    event_precision: str | None = None
    dob: DatedFact | None = None
    ages: list[int] = []
    for fact in facts:
        if fact.is_event_date() and fact.value:
            event_date, event_precision = str(fact.value), fact.precision or "year"
        elif fact.is_dob():
            dob = fact.dated() or dob
            # the fact is recorded whether or not it could be parsed — a
            # phrase the parser rejected still needs a person's word
            story_facts.append(
                Fact(
                    kind="dob",
                    entity=fact.entity or speaker_id,
                    text=fact.text,
                    value=str(fact.value) if fact.value is not None else None,
                    precision=fact.precision,
                    status="confirmed" if fact.is_confirmed() else "proposed",
                    source=("the narrator's own answer" if fact.is_confirmed() else "stated in the account"),
                )
            )
        elif fact.is_age() and isinstance(fact.value, int):
            ages.append(fact.value)
    return StoryFacts(tuple(story_facts), event_date, event_precision, dob, tuple(ages))


def _derive_event_year(collected: StoryFacts) -> DatedFact:
    """The story's date: the asserted events date wins; else dob + age
    (arithmetic only — the parsing was the library's and the model's);
    else the story cannot be saved — dating the story by its recording
    day would serve it as an anniversary ("0 years ago this week"); the
    flow must make the narrator provide the events date. The recorded
    day is `recorded`, never `date`."""
    if collected.event_date:
        return DatedFact(collected.event_date, collected.event_precision or "year")
    if collected.dob and collected.ages:
        return DatedFact(f"{int(collected.dob.date[:4]) + max(collected.ages):04d}", "approx")
    raise ValueError(
        "no events date was established — the narrator must provide one "
        "(the story's date is the events' date, never the telling day)"
    )


class Memory:
    """The narrator's capture flow — a memory (story, clarification,
    reflection) captured in the narrator's own words. The UI's word is
    memory ("Add a memory"); the code uses the same word.
    The flow's two entries are assess() — the per-turn chat assessment over
    the finished account — and build_story(), which turns the approved
    draft into the archive sidecar. The class is the noun the server and
    the CLI drive; the module functions are its machinery.
    """

    def __init__(self, client: ChatClient, knowledge: Knowledge) -> None:
        self.client = client
        self.knowledge = knowledge

    def assess(
        self,
        *,
        anchor: Anchor,
        who: str,
        account: str,
    ) -> Assessment:
        """Run the model over the finished account — {title, extractions,
        facts, questions}, validated and self-corrected."""
        return assess(self.client, anchor=anchor, who=who, account=account, knowledge=self.knowledge)

    def build_story(
        self,
        *,
        request: StoryRequest,
        existing_ids: set[str],
        recorded: str | None = None,
    ) -> BuiltStory:
        """Turn the narrator-approved draft into (story, new_people, new_places)."""
        return build_story(
            request=request,
            knowledge=self.knowledge,
            existing_ids=existing_ids,
            recorded=recorded,
        )
