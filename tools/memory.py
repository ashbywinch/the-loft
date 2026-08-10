"""Memory — the AI assessment of a contribution and the story it becomes.

Two phases (docs/MEMORIES.md): the client closes the account open-endedly
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
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, Protocol, cast

import dateparser

from tools.ai_client import AIClientError, json_object

KINDS = ("person", "place", "theme", "item")
BUCKETS = ("proposed", "question", "unresolved")
FACT_KINDS = ("dob", "event_date", "age")
PRECISIONS = ("exact", "month", "year", "approx")
MAX_QUESTIONS = 5
MAX_SUGGESTIONS = 3
MAX_ASSESS_ATTEMPTS = 3


class ChatClient(Protocol):
    """The model seam — satisfied by AIClient and by test doubles."""

    def chat(self, system: str, user: str) -> str: ...


_SYSTEM_PROMPT = f"""\
You are the contribution assistant for a private family archive. A contributor \
has told a story about something in the archive. Your job is ONE assessment: \
(1) a suggested title; (2) the people, places, themes and artifacts the story \
is ABOUT, matched against the standing knowledge — proposing links the narrator \
verifies in the review, never asserting identity you cannot ground; (3) any dates, \
dates of birth and ages the account states, asserted as structured facts; \
(4) up to {MAX_QUESTIONS} questions for genuinely missing detail that matters.

Extraction rules. Link an entity only when the story is about it — a passing \
mention is not a link. A name that merely shares a name or alias with someone \
in the standing knowledge is NOT a match: the narrator's own "Dad", "Mum", \
"Aunt Nora", a neighbour, a different family — same name, different person. \
Those stay unresolved (match null). A kinship term ("Dad", "Mum", "Aunt X", \
"Grandma") names the WRITER's own relative — it never matches someone merely \
because that person's record carries the alias; without the writer's own \
family evidenced in the account, it stays unresolved (2026-08-05). Ask a question only when it is genuinely \
ambiguous which person is meant. When in doubt between a link and a mention, \
choose unresolved — a false link is worse than no link — the narrator would rather see a \
question than a wrong match. Never guess an identity: an unnamed \
or ambiguous person is a question or left unresolved. A person mentioned near \
a place is not automatically at that place. Presence must be plausible for \
the story's time. \
For a name that is not in the standing knowledge but is clearly a person or \
place, still list it with "match": null and bucket "proposed" — it becomes a \
new proposed record the narrator verifies in the review. Artifacts (items) are linked by \
title; an artifact the story mentions that is not in the catalog stays \
"unresolved" — never create artifact records. Bucket meanings: "proposed" = \
a confident link worth one review tap; "question" = genuinely ambiguous, \
needs a question; "unresolved" = leave as plain text.

Fact rules. Assert every date, date of birth and age the account STATES, as \
facts. "kind": "dob" for a date of birth (entity = the person's id when you \
can match them to the standing knowledge, else null), "event_date" for when \
the events happened, "age" for an age the narrator gives about themselves. \
Quote the exact phrase as "text"; give the best "value" (ISO: a full date \
must be YYYY-MM-DD, a month YYYY-MM, a year YYYY — never a phrase, which \
would lose its day; or \
an integer for an age) and an honest "precision" (exact | month | year | \
approx). Incomplete forms ("the summer of 1979", "born in 1979") get what is \
there. If a phrase makes no sense as a date at all, "value": null. NEVER \
invent a date the account does not state.

Question rules. Ask only what is missing and matters; at most {MAX_QUESTIONS}; \
every question is skippable and nothing is required. Ask for: the event date; \
who was actually present; the identity of unnamed people; place precision \
("the old ford" — which one?); the connection of a narrator not in the \
standing knowledge (unless the story makes it obvious). A specific artifact \
the story names that is not in the catalog — a particular boat, object, or \
document — deserves a question asking about it ("Tell me more about the \
artifact you mentioned"): that is how its archive page gets built. Never \
bias toward one kind of artifact: a boat is no more worthy than a letter, a \
photograph, or a tool. Same for a named \
person or place not in the standing knowledge that matters to the story. \
A question that needs a date carries "type": "date" — the narrator answers \
it in their own words — and "date_kind": "dob" when asking for a date of \
birth, else "event". A question asking who was there carries "type": \
"people" — the narrator can name several, so its "suggestions" are the \
likely people and the flow lets them pick any number. For each question \
include up to {MAX_SUGGESTIONS} short \
"suggestions" the narrator can tap instead of typing; suggestions must be \
plausible for this narrator — never a date before their birth (their date of \
birth is in the standing knowledge or in the facts), and consistent with \
their stated age and with the story's stated time. Do not ask for a date \
the account already states (assert it as a fact instead); if you have \
asserted a date of birth and an age for the narrator, the year is computable \
(dob + age) — do not ask for it. Dates of birth are asked politely, never \
required, and only when they would disambiguate presence or date a story.

Never ask what the account or the archive already answers. If nothing is \
missing, "questions" is an empty list.

Respond with ONLY this JSON: {{"title": string, "extractions": [{{"kind": \
"person|place|theme|item", "name": string, "match": "<id>"|null, "bucket": \
"proposed|question|unresolved", "reason": string}}], "facts": [{{"kind": \
"dob|event_date|age", "entity": "<person id>"|null, "text": "<verbatim \
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


def _review(
    client: ChatClient,
    anchor: dict[str, str],
    who: str,
    account: str,
    knowledge: Knowledge,
    assessment: dict[str, Any],
) -> list[str]:
    """A second, cheap model pass reviews the assessment for rule violations
    (mentions linked, impossible matches, redundant questions). Returns the
    violations to feed back — empty means the assessment stands."""
    user = "\n\n".join(
        [
            _anchor_line(anchor),
            f"Contributor: {who or 'unknown'}",
            f"The story (verbatim):\n{account}",
            "Standing knowledge:\n" + knowledge.render(),
            "The assessor's output to review:\n" + json.dumps(assessment, ensure_ascii=False),
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


@dataclass(frozen=True)
class Person:
    """A cast member as the assessment sees them — one of the Knowledge
    records (docs/coding-standards.md: a group's members are their own
    types, never a repeat of dict[str, Any])."""

    id: str
    name: str
    aliases: tuple[str, ...] = ()
    dob: str | None = None
    status: str = "confirmed"  # the projection carries "proposed" for queued records

    def matches(self, name: str) -> bool:
        """Name or alias, case-insensitive — the one way a person is named."""
        wanted = str(name).strip().lower()
        return bool(wanted) and (
            self.name.strip().lower() == wanted or any(str(a).strip().lower() == wanted for a in self.aliases)
        )

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Person:
        return cls(
            id=str(raw["id"]),
            name=str(raw.get("name", "")),
            aliases=tuple(str(a) for a in (raw.get("aliases") or [])),
            dob=raw.get("dob"),
            status=str(raw.get("status", "confirmed")),
        )

    @classmethod
    def proposed(cls, name: str, existing: set[str]) -> dict[str, Any]:
        """The archive record for a person the story introduces — proposed,
        never confirmed (docs/MEMORIES.md)."""
        return {
            "id": _unique_id("p", _slug(name), existing),
            "name": name.strip(),
            "aliases": [],
            "years": "—",
            "relation": "added from a story",
            "bio": "",
            "hue": "amber",
        }


@dataclass(frozen=True)
class Place:
    """A place as the assessment sees it."""

    id: str
    name: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Place:
        return cls(id=str(raw["id"]), name=str(raw.get("name", "")))

    @classmethod
    def proposed(cls, name: str, existing: set[str]) -> dict[str, Any]:
        """The archive record for a place the story introduces — proposed,
        location unknown (docs/MEMORIES.md)."""
        return {
            "id": _unique_id("pl", _slug(name), existing),
            "name": name.strip(),
            "note": "Added from a story — location unknown.",
            "lat": None,
            "lng": None,
            "x": None,
            "y": None,
        }


@dataclass(frozen=True)
class Theme:
    """A curated theme as the assessment sees it."""

    id: str
    title: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Theme:
        return cls(id=str(raw["id"]), title=str(raw.get("title", "")))


@dataclass(frozen=True)
class Item:
    """An artifact (or any catalog item) as the assessment sees it."""

    id: str
    title: str
    type: str = ""
    status: str = ""  # catalogued | draft — the projection carries it; the
    # story-confirm invariant needs it (2026-08-05)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Item:
        return cls(
            id=str(raw["id"]),
            title=str(raw.get("title", "")),
            type=str(raw.get("type", "")),
            status=str(raw.get("status", "")),
        )


def _person_of(raw: Person | dict[str, Any]) -> Person:
    return raw if isinstance(raw, Person) else Person.from_dict(raw)


def _place_of(raw: Place | dict[str, Any]) -> Place:
    return raw if isinstance(raw, Place) else Place.from_dict(raw)


def _theme_of(raw: Theme | dict[str, Any]) -> Theme:
    return raw if isinstance(raw, Theme) else Theme.from_dict(raw)


def _item_of(raw: Item | dict[str, Any]) -> Item:
    return raw if isinstance(raw, Item) else Item.from_dict(raw)


@dataclass(frozen=True)
class Knowledge:
    """The standing archive an assessment works against — one object, one
    name, one home for the invariant (docs/coding-standards.md: groups that
    travel together are a type, never repeated parallel parameters). The
    projection's plain dicts are normalized once, here, into typed records
    that carry their own behavior — the members are never re-parsed by the
    callers."""

    people: tuple[Person, ...] = ()
    places: tuple[Place, ...] = ()
    themes: tuple[Theme, ...] = ()
    items: tuple[Item, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "people", tuple(_person_of(p) for p in self.people))
        object.__setattr__(self, "places", tuple(_place_of(p) for p in self.places))
        object.__setattr__(self, "themes", tuple(_theme_of(t) for t in self.themes))
        object.__setattr__(self, "items", tuple(_item_of(i) for i in self.items))

    @classmethod
    def from_projection(
        cls,
        people: Iterable[Person | dict[str, Any]],
        places: Iterable[Place | dict[str, Any]],
        themes: Iterable[Theme | dict[str, Any]],
        items: Iterable[Item | dict[str, Any]],
    ) -> Knowledge:
        """The typed view of the projection — the one conversion point for
        the server's plain dicts (docs/coding-standards.md: members are
        typed records; callers never re-parse them)."""
        return cls(
            people=tuple(_person_of(p) for p in people),
            places=tuple(_place_of(p) for p in places),
            themes=tuple(_theme_of(t) for t in themes),
            items=tuple(_item_of(i) for i in items),
        )

    def speaker_for(self, who: str) -> str | None:
        """Match the contributor's self-name against the cast (name or alias)."""
        wanted = who.strip()
        if not wanted:
            return None
        for person in self.people:
            if person.matches(wanted):
                return person.id
        return None

    def narrator_dob(self, speaker_id: str | None) -> str | None:
        """The narrator's date of birth from the standing knowledge, when the
        cast records it — used to keep suggestions plausible (a quick reply
        is never a date before the narrator was born)."""
        if not speaker_id:
            return None
        for person in self.people:
            if person.id == speaker_id and person.dob:
                return person.dob
        return None

    def render(self) -> str:
        """Compact render of the cast/places/themes/items for the model
        prompt."""
        lines = ["People:"]
        for p in self.people:
            info = [f"  {p.id} — {p.name}"]
            if p.aliases:
                info.append(f"(aliases: {', '.join(p.aliases)})")
            if p.dob:
                info.append(f"(born {p.dob})")
            lines.append(" ".join(info))
        lines.append("Places:")
        for pl in self.places:
            lines.append(f"  {pl.id} — {pl.name}")
        lines.append("Themes:")
        for t in self.themes:
            lines.append(f"  {t.id} — {t.title}")
        lines.append("Artifacts:")
        for it in self.items:
            lines.append(f"  {it.id} — {it.title} ({it.type})")
        return "\n".join(lines)


def _anchor_line(anchor: dict[str, str]) -> str:
    kind = anchor.get("kind", "item")
    label = anchor.get("name") or anchor.get("id") or "an item in the archive"
    return f"Anchor (where the contributor started): {kind} — {label}"


def _locale_date_order() -> str:
    """The archive's date order for ambiguous numerics. Default DMY (the
    family is British); LOFT_LOCALE (e.g. en_US) overrides — locale is
    respected when reading dates (docs/MEMORIES.md)."""
    locale = os.environ.get("LOFT_LOCALE", "en_GB")
    return "MDY" if locale.lower().startswith("en_us") else "DMY"


def _normalize_date_fact(value: Any, precision: Any) -> tuple[str | None, str | None]:
    """Validate a model-asserted date with the real parser: dateparser parses
    the asserted VALUE (locale-aware, incomplete forms allowed); the verbatim
    text is provenance, never parsed. A value the parser cannot make sense of
    becomes (None, None) — a person resolves.
    """
    if precision not in PRECISIONS:
        precision = None
    if not isinstance(value, str) or not value.strip():
        return None, None
    # strip a hedge word ("around/circa/about 1965") — token stripping, not a
    # date parser
    phrase = re.sub(r"^(?:around|circa|about)\s+", "", value.strip(), flags=re.IGNORECASE)
    # ISO shapes are unambiguous — the stdlib parses them (locale-free);
    # anything else ("15/09/1981", "July 1979", "1979") goes to the
    # locale-aware parser
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", phrase):
            parsed = datetime.strptime(phrase, "%Y-%m-%d")
        elif re.fullmatch(r"\d{4}-\d{2}", phrase):
            parsed = datetime.strptime(phrase, "%Y-%m")
        elif re.fullmatch(r"\d{4}", phrase):
            parsed = datetime.strptime(phrase, "%Y")
        else:
            parsed = dateparser.parse(
                phrase,
                settings={
                    "DATE_ORDER": _locale_date_order(),
                    "PREFER_DAY_OF_MONTH": "first",
                    "PREFER_DATES_FROM": "past",
                },
            )
    except ValueError, OverflowError:
        parsed = None
    if parsed is None:
        return None, None
    year = parsed.year
    # precision is demoted to what the VALUE's shape actually supports — an
    # over-claimed "exact" on a bare year must never pin an invented day
    # (PRD §6; reviewer, 2026-08-03). ISO shapes decide by shape; a non-ISO
    # phrase is probed against a far-off base — a stable parse means the
    # value names its own parts, an unstable one means the parser filled
    # them in (demote to the year the parse proved).
    if precision == "exact":
        # an exact day is only provable from a full ISO value; a non-ISO
        # phrase ("July 1979", "31 July 1979") can never claim one — a
        # month-only phrase must not become 1979-07-01 (reviewer, 2026-08-03;
        # PRD §6: never fabricate a date part)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", phrase):
            return f"{year:04d}-{parsed.month:02d}-{parsed.day:02d}", "exact"
        if re.fullmatch(r"\d{4}-\d{2}", phrase):
            return f"{year:04d}-{parsed.month:02d}", "month"
        if re.fullmatch(r"\d{4}", phrase):
            return f"{year:04d}", "year"  # a bare year is a year — the stdlib's Jan-1 is not a real date
        if _stable_parse(phrase, parsed):
            return f"{year:04d}-{parsed.month:02d}", "month"
        return f"{year:04d}", "year"
    if precision == "month":
        if re.fullmatch(r"\d{4}-\d{2}", phrase):
            return f"{year:04d}-{parsed.month:02d}", "month"
        if re.fullmatch(r"\d{4}", phrase):
            return f"{year:04d}", "year"
        if _stable_parse(phrase, parsed):
            return f"{year:04d}-{parsed.month:02d}", "month"
        return f"{year:04d}", "year"
    return f"{year:04d}", precision or "year"


_FAR_BASE = datetime(1600, 1, 1)  # far enough that injected parts must shift


def _stable_parse(phrase: str, parsed: datetime) -> bool:
    """Does the phrase name its own parts? Re-parse against a far-off base —
    a bare "1963" picks up the base's month/day and shifts; a full
    "15/09/1981" is unchanged. This is the library's own behaviour, never a
    hand-rolled parser (docs/coding-standards.md)."""
    probe = dateparser.parse(
        phrase,
        settings={
            "DATE_ORDER": _locale_date_order(),
            "PREFER_DAY_OF_MONTH": "first",
            "PREFER_DATES_FROM": "past",
            "RELATIVE_BASE": _FAR_BASE,
        },
    )
    return probe is not None and (probe.year, probe.month, probe.day) == (parsed.year, parsed.month, parsed.day)


def _normalize_age_fact(value: Any, precision: Any) -> tuple[int | None, str | None]:
    try:
        age = int(value)
    except TypeError, ValueError:
        return None, None
    if not 0 < age < 110:
        return None, None
    return age, precision if precision in PRECISIONS else "approx"


def _validate_facts(raw: Any) -> list[dict[str, Any]]:
    """Structural cleaning + library validation of the model's fact list."""
    if not isinstance(raw, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for fact in raw:
        if not isinstance(fact, dict):
            continue
        kind = fact.get("kind")
        if kind not in FACT_KINDS:
            continue
        text = fact.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        entry: dict[str, Any] = {"kind": kind, "text": text.strip()[:300]}
        entity = fact.get("entity")
        entry["entity"] = str(entity)[:64] if entity else None
        if kind == "age":
            age, precision = _normalize_age_fact(fact.get("value"), fact.get("precision"))
            if age is None:
                continue
            entry["value"], entry["precision"] = age, precision
        else:
            value, precision = _normalize_date_fact(fact.get("value"), fact.get("precision"))
            entry["value"], entry["precision"] = value, precision
        cleaned.append(entry)
    return cleaned


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


def _suggestion_year(s: str) -> int | None:
    """A suggestion's year via the real parser — never a hand-rolled date
    parser. Phrases the parser cannot date are kept (None). Only two bounded
    token strips precede the parser: a hedge word ("around/about/circa") and
    a season lead-in ("the summer of 1960" -> "1960"); a bare decade token
    ("the 1960s") the parser mis-reads is taken at its decade start."""
    phrase = re.sub(r"^(?:around|circa|about)\s+", "", s.strip(), flags=re.IGNORECASE)
    phrase = re.sub(
        r"^(?:the\s+)?(?:summer|spring|autumn|fall|winter)\s+of\s+",
        "",
        phrase,
        flags=re.IGNORECASE,
    )
    decade = re.fullmatch(r"(?:19|20)\d{2}s", phrase, flags=re.IGNORECASE)
    if decade:
        return int(phrase[:4])
    try:
        parsed = dateparser.parse(
            phrase,
            settings={"DATE_ORDER": _locale_date_order(), "PREFER_DATES_FROM": "past"},
        )
    except ValueError, OverflowError:
        return None
    return parsed.year if parsed else None


def _filter_implausible_suggestions(assessment: dict[str, Any], who: str, knowledge: Knowledge) -> dict[str, Any]:
    """Deterministic guard on date-question suggestions (docs/coding-
    standards.md: deterministic checks beat model judgment): never offer a
    year before the narrator was born — their dob is in the assessment's
    facts or the standing knowledge. Suggestions the parser cannot date are
    kept; dob questions (the date is being asked) are never filtered."""
    questions = assessment.get("questions", [])
    if not questions:
        return assessment
    speaker_id = knowledge.speaker_for(who)
    dob_value: str | None = None
    for fact in assessment.get("facts", []):
        if fact.get("kind") != "dob" or not fact.get("value"):
            continue
        entity = fact.get("entity")
        if entity in (None, speaker_id):
            dob_value = fact["value"]
            break
    if not dob_value:
        dob_value = knowledge.narrator_dob(speaker_id)
    if not dob_value:
        return assessment
    try:
        dob_year = int(str(dob_value)[:4])
    except TypeError, ValueError:
        return assessment
    filtered = []
    for q in questions:
        if q.get("type") != "date" or q.get("date_kind") == "dob" or not q.get("suggestions"):
            filtered.append(q)
            continue
        kept = [s for s in q["suggestions"] if (year := _suggestion_year(s)) is None or year >= dob_year]
        filtered.append({**q, "suggestions": kept})
    return {**assessment, "questions": filtered}


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


def resolve_pending_facts(client: ChatClient | None, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill the date facts the narrator answered in their own words: a fact
    with kind dob/event_date, verbatim text and no value yet goes to the
    model to assert value and precision; the library validates both
    (docs/coding-standards.md: the model asserts, the library parses). An
    answer the model or the parser cannot date stays null — a person's word
    resolves it. Never runs without a client (an offline save keeps the
    fact pending)."""
    pending = [
        f
        for f in facts
        if f.get("kind") in ("dob", "event_date")
        and isinstance(f.get("text"), str)
        and f["text"].strip()
        and not f.get("value")
    ]
    if not pending or client is None:
        return list(facts)
    try:
        raw = client.chat(
            _PENDING_FACT_PROMPT,
            json.dumps(
                [{"kind": f.get("kind"), "text": f["text"].strip()[:300]} for f in pending],
                ensure_ascii=False,
            ),
        )
        parsed = json_object(raw)
        answers = parsed.get("answers") if isinstance(parsed, dict) else None
        if not isinstance(answers, list):
            return list(facts)
    except AIClientError:
        return list(facts)
    by_text = {
        str(p.get("text", "")).strip(): p for p in answers if isinstance(p, dict) and isinstance(p.get("text"), str)
    }
    out: list[dict[str, Any]] = []
    for fact in facts:
        if fact not in pending or fact["text"].strip() not in by_text:
            out.append(fact)
            continue
        candidate = by_text[fact["text"].strip()]
        value, precision = _normalize_date_fact(candidate.get("value"), candidate.get("precision"))
        if value:
            out.append({**fact, "value": value, "precision": precision})
        else:
            out.append(fact)
    return out


def _date_question_asked(assessment: dict[str, Any]) -> bool:
    for q in assessment.get("questions", []):
        if q.get("type") == "date":
            return True
        text = str(q.get("text", "")).lower()
        if any(w in text for w in _DATE_ASK_WORDS):
            return True
    return False


def _deterministic_violations(assessment: dict[str, Any], who: str, knowledge: Knowledge) -> list[str]:
    """Rule violations checkable in code — no model judgment needed. These
    feed the same redo-with-feedback loop as the reviewer's findings."""
    violations: list[str] = []
    if who.strip() and knowledge.speaker_for(who) is None:
        questions = " ".join(q.get("text", "") for q in assessment.get("questions", [])).lower()
        if not any(w in questions for w in ("connect", "related", "relationship", "family")):
            violations.append(
                "the narrator is not in the standing knowledge and no question asks "
                "how they are connected to the family"
            )
    facts = assessment.get("facts", [])
    ages = [f for f in facts if f.get("kind") == "age" and isinstance(f.get("value"), int)]
    if ages:
        speaker_id = knowledge.speaker_for(who)
        known_dob = knowledge.narrator_dob(speaker_id)
        dob_in_facts = any(f.get("kind") == "dob" and f.get("value") for f in facts)
        if known_dob or dob_in_facts:
            if _date_question_asked(assessment):
                violations.append(
                    "a date question is asked although the year is computable from the narrator's date of birth and age"
                )
        elif not _date_question_asked(assessment):
            violations.append(
                "the account gave an age and no date of birth is known or stated — ask "
                "politely for the date of birth or the year"
            )
    # the events date must be the narrator's, never the telling day — the
    # model fabricating today as the event date is exactly how the moment
    # card came to serve "0 years ago this week" (2026-08-05). A date equal
    # to the telling day is only legitimate when the narrator's own words
    # stated it (a diary-style entry that really happened that day) — the
    # verbatim is the discriminator: a fabricated date has no narrator text.
    event_dates = [f for f in facts if f.get("kind") == "event_date" and f.get("value")]
    known_dob = knowledge.narrator_dob(knowledge.speaker_for(who))
    dob_in_facts = any(f.get("kind") == "dob" and f.get("value") for f in facts)
    if event_dates:
        today = date.today().isoformat()
        todayish = ("today", "tonight", "this morning", "this evening", "this week", "just now", "now", "earlier today")
        for f in event_dates:
            value = str(f.get("value"))
            if value in (today, today[:7], today[:4]):
                # legitimate only when the narrator's own words said so — a
                # diary-style entry that really happened that day. The
                # verbatim is the discriminator: "Today" / the date itself
                # in the answer, never a fabricated value with no such words.
                verbatim = str(f.get("text") or "").strip().lower()
                if value.lower() not in verbatim and not any(w in verbatim for w in todayish):
                    violations.append(
                        "the events date is the telling day and the narrator never stated it — a "
                        "fabrication; quote the date from the account itself or ask the narrator a "
                        "non-skippable question for the events date"
                    )
                    break
    elif not (ages and (known_dob or dob_in_facts)):
        # no events date and nothing to derive one from — the narrator must
        # provide it (the story's date is the events' date, never recorded)
        if not any(
            q.get("type") == "date" and q.get("date_kind") == "event" and q.get("skippable") is False
            for q in assessment.get("questions", [])
        ):
            violations.append(
                "no events date is established — ask the narrator a non-skippable date "
                "question for when the events happened"
            )
    # a new artifact the story names deserves a "tell me more" question —
    # checkable in code from the extractions (item, no match)
    new_items = [ex for ex in assessment.get("extractions", []) if ex.get("kind") == "item" and not ex.get("match")]
    if new_items:
        questions = " ".join(q.get("text", "") for q in assessment.get("questions", [])).lower()
        if not any(ex.get("name", "").strip().lower() and ex["name"].strip().lower() in questions for ex in new_items):
            violations.append(
                "a specific new artifact is named in the story and no question asks about it "
                '("tell me more" — that is how its archive page gets built)'
            )
    return violations


# A bare kinship term names the writer's own relative — never a match to a
# person record merely because that record carries the alias. The model
# defaulted "Dad" to the only Dad-aliased person despite the prompt rule
# (eval: kinship-term-not-an-archive-alias, 2026-08-05), so the code strips
# the match deterministically: writer-relative resolution is a later seam
# (option C), not the model's guess (docs/coding-standards.md — deterministic
# checks beat model judgment).
_KINSHIP_TERMS = frozenset(
    {
        "dad",
        "daddy",
        "father",
        "mum",
        "mummy",
        "mom",
        "mother",
        "mam",
        "grandma",
        "granny",
        "gran",
        "nana",
        "nanny",
        "grandad",
        "granddad",
        "grandpa",
        "grandfather",
        "grandmother",
        "aunt",
        "aunty",
        "auntie",
        "uncle",
        "sister",
        "brother",
        "cousin",
    }
)


def _strip_kinship_matches(assessment: dict[str, Any]) -> dict[str, Any]:
    """A person extraction whose name is a bare kinship term ('Dad', 'Mum',
    'Aunt') never keeps a match — the term is the writer's own relative, and
    matching it to a record the archive happens to alias is a misattribution.
    The extraction survives (match null) so the unnamed relative can be
    proposed for the writer to identify."""
    extractions = []
    for ex in assessment.get("extractions", []):
        if ex.get("kind") == "person" and str(ex.get("name", "")).strip().lower() in _KINSHIP_TERMS:
            ex = {**ex, "match": None}
        extractions.append(ex)
    return {**assessment, "extractions": extractions}


def assess(
    client: ChatClient,
    *,
    anchor: dict[str, str],
    who: str,
    account: str,
    knowledge: Knowledge,
) -> dict[str, Any]:
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
    assessment: dict[str, Any] = {}
    for attempt in range(MAX_ASSESS_ATTEMPTS):
        try:
            raw = client.chat(_SYSTEM_PROMPT, user)
            parsed = json_object(raw)
        except AIClientError as e:
            raise ElicitationError(f"assessment failed: {e}") from e
        assessment = _validate_assessment(parsed)
        if attempt >= MAX_ASSESS_ATTEMPTS - 1:
            break  # last attempt: accept the best effort
        violations = _deterministic_violations(assessment, who, knowledge)
        violations += _review(client, anchor, who, account, knowledge, assessment)
        if not violations:
            break
        user = (
            user
            + "\n\nA reviewer found these problems in your assessment. Fix them and re-respond "
            + "with the corrected assessment JSON:\n- "
            + "\n- ".join(violations)
        )
    return _strip_kinship_matches(_filter_implausible_suggestions(assessment, who, knowledge))


def _validate_assessment(parsed: Any) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        raise ElicitationError(f"assessment is not an object: {parsed!r}")
    title = parsed.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ElicitationError("assessment missing a title")
    extractions = parsed.get("extractions", [])
    if not isinstance(extractions, list):
        raise ElicitationError("assessment extractions are not a list")
    cleaned: list[dict[str, Any]] = []
    for ex in extractions:
        if not isinstance(ex, dict):
            continue
        kind, name = ex.get("kind"), ex.get("name")
        if kind not in KINDS or not isinstance(name, str) or not name.strip():
            continue
        bucket = ex.get("bucket") if ex.get("bucket") in BUCKETS else "unresolved"
        match = ex.get("match") if isinstance(ex.get("match"), str) else None
        reason = str(ex.get("reason", ""))
        cleaned.append({"kind": kind, "name": name.strip(), "match": match, "bucket": bucket, "reason": reason})
    questions = parsed.get("questions", [])
    if not isinstance(questions, list):
        raise ElicitationError("assessment questions are not a list")
    q_cleaned: list[dict[str, Any]] = []
    for q in questions[:MAX_QUESTIONS]:
        if isinstance(q, dict) and isinstance(q.get("text"), str) and q["text"].strip():
            raw_suggestions = q.get("suggestions", [])
            suggestions = [
                str(s).strip()[:60]
                for s in (raw_suggestions if isinstance(raw_suggestions, list) else [])
                if isinstance(s, str) and s.strip()
            ][:MAX_SUGGESTIONS]
            q_type = q.get("type") if q.get("type") in ("date", "people") else None
            q_cleaned.append(
                {
                    "text": q["text"].strip(),
                    "why": str(q.get("why", "")),
                    "skippable": q.get("skippable", True) is not False,
                    "suggestions": suggestions,
                    "type": q_type,
                    "date_kind": q.get("date_kind") if q_type == "date" else None,
                }
            )
    return {
        "title": title.strip(),
        "extractions": cleaned,
        "facts": _validate_facts(parsed.get("facts", [])),
        "questions": q_cleaned,
    }


# ---------------------------------------------------------------------------
# build_story — the narrator-approved draft becomes a canonical story item
# ---------------------------------------------------------------------------


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:40] or "new"


def _unique_id(prefix: str, slug: str, existing: set[str]) -> str:
    candidate = f"{prefix}-{slug}"
    if candidate not in existing:
        return candidate
    n = 2
    while f"{candidate}-{n}" in existing:
        n += 1
    return f"{candidate}-{n}"


def _dedupe_refs(refs: list[Ref]) -> list[Ref]:
    """Keep the first ref per entity id — a proposed link is one link."""
    seen: set[str] = set()
    out: list[Ref] = []
    for ref in refs:
        if ref.id in seen:
            continue
        seen.add(ref.id)
        out.append(ref)
    return out


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
class Ref:
    """One link a story carries to an entity — ``confirmed`` means the
    narrator verified it in the review; ``proposed`` awaits a tap
    (TECH-SPEC §16.4)."""

    id: str
    status: Literal["confirmed", "proposed"]


@dataclass(frozen=True)
class Story:
    """A story contribution as the capture flow's domain object
    (docs/MEMORIES.md): the sidecar's shape with typed links. The
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
        anchor: dict[str, str],
        extractions: list[dict[str, Any]],
        knowledge: Knowledge,
        verified: bool,
        all_ids: set[str],
    ) -> tuple[list[Ref], list[Ref], list[Ref], list[Ref], list[dict[str, Any]], list[dict[str, Any]]]:
        """The story's links from the narrator-approved assessment: the
        anchor and the kept extractions become refs (one per entity), and
        newly introduced people/places mint proposed records. A verified
        (catalogued) story confirms item links only to catalogued
        artifacts — a link to a still-draft artifact stays proposed until
        the artifact is catalogued, so confirming a story never leaves a
        dangling object."""
        ref_status = "confirmed" if verified else "proposed"
        people_refs: list[Ref] = []
        places_refs: list[Ref] = []
        themes_refs: list[Ref] = []
        items_refs: list[Ref] = []
        new_people: list[dict[str, Any]] = []
        new_places: list[dict[str, Any]] = []
        person_ids = {p.id for p in knowledge.people}
        place_ids = {pl.id for pl in knowledge.places}
        theme_ids = {t.id for t in knowledge.themes}
        item_ids = {it.id for it in knowledge.items}
        by_item = {it.id: it for it in knowledge.items}

        # the page the narrator started from is their own aboutness evidence
        anchor_kind = anchor.get("kind", "item")
        anchor_id = anchor.get("id")
        if anchor_kind == "person" and anchor_id:
            people_refs.append(Ref(anchor_id, ref_status))
        elif anchor_kind == "place" and anchor_id:
            places_refs.append(Ref(anchor_id, ref_status))
        elif anchor_kind == "theme" and anchor_id:
            themes_refs.append(Ref(anchor_id, ref_status))

        for ex in extractions:
            ex_kind = ex.get("kind")
            name = ex.get("name", "").strip()
            match = ex.get("match")
            if ex_kind == "person":
                if match and match in person_ids:
                    people_refs.append(Ref(match, ref_status))
                elif name:
                    # reuse a standing cast member by name/alias before minting —
                    # a fresh id per story mention fragments the cast (2026-08-05
                    # bot review, the person analog of the place name-dedup). A
                    # bare kinship term is the writer's own relative, never a
                    # cast alias — it stays proposed for the writer to identify
                    # (the kinship filter's strip must stay effective).
                    existing = None
                    if name.strip().lower() not in _KINSHIP_TERMS:
                        existing = next((p for p in knowledge.people if p.matches(name)), None)
                    else:
                        # a kinship term never resolves to a CONFIRMED cast
                        # member — that alias could be the wrong relative
                        # (writer-relative resolution is the option-C task) —
                        # but two stories mentioning the same "Grandma" must
                        # share ONE proposed record: a fresh proposed id per
                        # story makes the projection's name-dedup drop the
                        # second mint, and its story's ref then dangles at
                        # publish (2026-08-05 bot review).
                        existing = next(
                            (p for p in knowledge.people if p.status == "proposed" and p.matches(name)), None
                        )
                    if existing is not None:
                        people_refs.append(Ref(existing.id, ref_status))
                    else:
                        person = Person.proposed(name, all_ids)
                        all_ids.add(person["id"])
                        new_people.append(person)
                        people_refs.append(Ref(person["id"], ref_status))
            elif ex_kind == "place":
                if match and match in place_ids:
                    places_refs.append(Ref(match, ref_status))
                elif name:
                    # reuse a standing place by name before minting — a fresh id
                    # per story mention multiplies one place into many (the
                    # moored-barges ×3, 2026-08-05)
                    existing = next(
                        (pl for pl in knowledge.places if pl.name.strip().lower() == name.lower()),
                        None,
                    )
                    if existing is not None:
                        places_refs.append(Ref(existing.id, ref_status))
                    else:
                        place = Place.proposed(name, all_ids)
                        all_ids.add(place["id"])
                        new_places.append(place)
                        places_refs.append(Ref(place["id"], ref_status))
            elif ex_kind == "theme" and match and match in theme_ids:
                # themes are curated arrangements — proposed only, never auto-created
                themes_refs.append(Ref(match, ref_status))
            elif ex_kind == "item" and match and match in item_ids:
                # artifacts are linked by title; a mention without a catalog
                # match stays unresolved — never auto-create artifact records
                status = ref_status
                if ref_status == "confirmed" and by_item[match].status == "draft":
                    # a draft artifact is hidden from everyone but its owner —
                    # a confirmed link to it would dangle; it stays proposed
                    # until the artifact is catalogued (2026-08-05)
                    status = "proposed"
                items_refs.append(Ref(match, status))

        # one ref per entity — the anchor and an extraction may name the same one
        return (
            _dedupe_refs(people_refs),
            _dedupe_refs(places_refs),
            _dedupe_refs(themes_refs),
            _dedupe_refs(items_refs),
            new_people,
            new_places,
        )

    def to_sidecar(self) -> dict[str, Any]:
        """The archive sidecar the capture server writes — the app and the
        tests read this shape."""
        return {
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
            "people": [{"id": r.id, "status": r.status} for r in self.people],
            "places": [{"id": r.id, "status": r.status} for r in self.places],
            "themes": [{"id": r.id, "status": r.status} for r in self.themes],
            "items": [{"id": r.id, "status": r.status} for r in self.items],
            "facts": [f.to_dict() for f in self.facts],
            "sensitive": False,
            "status": self.status,
            "assets": [],
            "created": self.recorded,
            "created_at": datetime.now().isoformat(timespec="seconds"),  # the recent feed's tie-break
        }


def _next_story_id(recorded: str, existing: set[str]) -> str:
    prefix = f"story-{recorded}"
    n = 1
    while f"{prefix}-{n:02d}" in existing:
        n += 1
    return f"{prefix}-{n:02d}"


def build_story(
    *,
    anchor: dict[str, str],
    who: str,
    title: str,
    account: str,
    extractions: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    knowledge: Knowledge,
    existing_ids: set[str],
    recorded: str | None = None,
    status: str = "draft",
    story_id: str | None = None,
    chat: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Turn the narrator-approved draft into (story, new_people, new_places).

    Pure: the caller writes the sidecar and the proposed records through the
    append-only store. The operator verifies the AI's guesses in the same
    flow (docs/MEMORIES.md): a completed, reviewed save is
    ``catalogued`` with ``confirmed`` refs; an abandoned one is ``draft``
    with ``proposed`` refs. Facts decide the dates: an asserted event date
    wins; a date of birth plus an age derives the events year (dob + age,
    arithmetic only); a dob the narrator asserts in answer to a direct
    question is confirmed, one merely stated in prose is proposed
    (docs/MEMORIES.md — no hand-coded date parsers).
    """
    verified = status == "catalogued"
    recorded = recorded or date.today().isoformat()
    # an ongoing draft keeps ONE id through its life: the client's auto-saves
    # and the final save supersede the same story in place (append-only —
    # every version stays, the newest wins; docs/TECH-SPEC.md §3). A fresh
    # save without an id mints the next story id.
    story_id = story_id or _next_story_id(recorded, existing_ids)
    speaker_id = knowledge.speaker_for(who)

    # facts decide the story's date and the dob proposals
    story_facts: list[Fact] = []
    event_date: str | None = None
    event_precision: str | None = None
    dob: str | None = None
    ages: list[int] = []
    for fact in facts:
        kind = fact.get("kind")
        if kind == "event_date" and fact.get("value"):
            event_date, event_precision = fact["value"], fact.get("precision") or "year"
        elif kind == "dob":
            if fact.get("value"):
                dob = fact["value"]
            # the fact is recorded whether or not it could be parsed — a
            # phrase the parser rejected still needs a person's word
            story_facts.append(
                Fact(
                    kind="dob",
                    entity=fact.get("entity") or speaker_id,
                    text=fact.get("text", ""),
                    value=fact.get("value"),
                    precision=fact.get("precision"),
                    status="confirmed" if fact.get("status") == "confirmed" else "proposed",
                    source=(
                        "the narrator's own answer" if fact.get("status") == "confirmed" else "stated in the account"
                    ),
                )
            )
        elif kind == "age" and isinstance(fact.get("value"), int):
            ages.append(fact["value"])

    if event_date:
        event_year, event_precision = event_date, event_precision or "year"
    elif dob and ages:
        # arithmetic only — the parsing was the library's and the model's
        event_year, event_precision = str(int(dob[:4]) + max(ages)), "approx"
    else:
        # no events date was ever asserted — the story cannot be saved. The
        # old fallback dated the story by its recording day, which the
        # moment card then served as an anniversary ("0 years ago this
        # week"); the flow must make the narrator provide the events date
        # (2026-08-05). The recorded day is `recorded`, never `date`.
        raise ValueError(
            "no events date was established — the narrator must provide one "
            "(the story's date is the events' date, never the telling day)"
        )

    # the links: built by the Story domain object, which enforces the
    # invariant that a catalogued story never confirms a link to an
    # artifact the reader cannot see (a draft item stays proposed)
    anchor_kind = anchor.get("kind", "item")
    anchor_id = anchor.get("id")
    all_ids = set(existing_ids) | {p.id for p in knowledge.people}
    all_ids |= {pl.id for pl in knowledge.places} | {t.id for t in knowledge.themes}
    people_refs, places_refs, themes_refs, items_refs, new_people, new_places = Story.refs_from_assessment(
        anchor=anchor,
        extractions=extractions,
        knowledge=knowledge,
        verified=verified,
        all_ids=all_ids,
    )

    speaker = speaker_id
    if not speaker:
        speaker_person = Person.proposed(who.strip() or "Guest", all_ids)
        if dob:
            speaker_person["dob"] = dob  # the new record carries what was offered
        all_ids.add(speaker_person["id"])
        new_people.append(speaker_person)
        speaker = speaker_person["id"]

    story = Story(
        story_id=story_id,
        title=title.strip() or f"A story about {anchor.get('name') or 'the archive'}",
        date=event_year,
        date_precision=event_precision,
        recorded=recorded,
        description="",
        story=account.strip(),
        transcription="",
        told_by=speaker,
        comment_on=anchor_id if anchor_kind == "item" else None,
        chat=chat,
        source=f"Site contribution, {recorded}",
        people=tuple(people_refs),
        places=tuple(places_refs),
        themes=tuple(themes_refs),
        items=tuple(items_refs),
        facts=tuple(story_facts),
        status=status,
    )
    return story.to_sidecar(), new_people, new_places


class Memory:
    """The narrator's capture flow — a memory (story, clarification,
    reflection) captured in the narrator's own words. The UI's word is
    memory ("Add a memory"); the code uses the same word (2026-08-06).
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
        anchor: dict[str, str],
        who: str,
        account: str,
    ) -> dict[str, Any]:
        """Run the model over the finished account — {title, extractions,
        facts, questions}, validated and self-corrected."""
        return assess(self.client, anchor=anchor, who=who, account=account, knowledge=self.knowledge)

    def build_story(
        self,
        *,
        anchor: dict[str, str],
        who: str,
        title: str,
        account: str,
        extractions: list[dict[str, Any]],
        facts: list[dict[str, Any]],
        existing_ids: set[str],
        recorded: str | None = None,
        status: str = "draft",
        story_id: str | None = None,
        chat: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        """Turn the narrator-approved draft into (story, new_people, new_places)."""
        return build_story(
            anchor=anchor,
            who=who,
            title=title,
            account=account,
            extractions=extractions,
            facts=facts,
            knowledge=self.knowledge,
            existing_ids=existing_ids,
            recorded=recorded,
            status=status,
            story_id=story_id,
            chat=chat,
        )
