"""The archive's domain record types (docs/coding-standards.md: a group's
members are their own types) — typed, validated, serialisable records for
the identity tables, the proposed queue and the items: Person, Place, Org,
Relationship, Item and the table wrappers. This module IS the object model:
every vocabulary (relationship kinds, date precisions, item types and
statuses) lives here, and ``validate_identity`` / ``Item.from_dict`` are the
single validation seam — a record or item that isn't one of these types was
never written.

One type for a person whether confirmed (in the identity table) or proposed
(awaiting review) — the difference is the ``status`` field, and every record
round-trips the exact JSON the store writes (crash resumption: the archive
is the persisted state, so the classes own the wire format). The classes
are the only place the table invariants live: unique ids, required fields,
closed relationship kinds, every relationship resolves. ``validate_identity``
is what derive calls at publish — a bad table fails loudly instead of
shipping.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass, replace
from datetime import UTC
from typing import Any, Literal, TypeVar, cast

from tools.asset import Asset
from tools.date_mention import DateMention
from tools.dated_fact import PRECISIONS, DatedFact, viable_date
from tools.gone_person import GonePerson
from tools.ref import Ref
from tools.resolution import Resolution
from tools.split_item import SplitItem
from tools.theme import Theme

RELATIONSHIP_KINDS = frozenset({"spouse", "parent", "sibling", "inlaw", "teacher"})

# The date-precision vocabulary lives with the dated fact that carries it
# (tools/dated_fact.py) — PRECISIONS is imported here for the item's own
# date_precision field.
# The place-coordinate granularity: how precisely the stored
# point locates the place. "" = unset (treated as a point); exact = the
# coordinate is the place (street address, surveyed point); street = the
# point is the street/square and the place is on it (the Lark Inn is on
# Market Square — the exact building is not pinned); town/county/region =
# the point is the containing area's centre; country/continent = the point
# is the area's centroid (a mention, never a precise pin). The map draws
# uncertainty at the right size.
PLACE_PRECISIONS = frozenset({"", "exact", "street", "town", "county", "region", "country", "continent"})

# The item vocabulary: the sidecar's closed sets. ``deleted``
# is the tombstone shape (id/type/title/status/reason only). ``event`` is an
# attested happening (a birth, a marriage, a concert a letter mentions) —
# its kind is required and closed.
ITEM_TYPES = frozenset({"letter", "document", "photo", "object", "ephemera", "audio", "video", "story", "event"})
EVENT_KINDS = frozenset({"birth", "marriage", "death", "other"})
ITEM_STATUSES = frozenset({"draft", "catalogued", "deleted"})
TRANSCRIPTION_STATUSES = frozenset({"none", "draft", "confirmed"})

# The one record-id rule: a lowercase letter then letters/digits/hyphens
# (a person, a place, a story — the dataset's ids). Record ids become
# store paths (assets/<id>/, proposed/people/<id>.json) and output
# filenames (avatar-<id>.svg) — anything else could escape the archive root.
# The classes own the rule; archive.py's
# write paths enforce it too.
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

RECORD_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def is_valid_record_id(record_id: str) -> bool:
    return bool(RECORD_ID_RE.fullmatch(record_id))


def _dated(raw: Mapping[str, Any], key: str) -> DatedFact | None:
    """The dated fact a record's field states (dob, dod, a relationship
    date) — None when the field is absent."""
    value = raw.get(key)
    return None if not value else DatedFact.from_dict(value, key)


def _required_value(raw: Mapping[str, Any], key: str, vocab: frozenset[str], label: str) -> str:
    """A required field whose value must be one of the closed vocabulary —
    the standard 'unknown {label}' error names the field."""
    value = _require(raw, key)
    if value not in vocab:
        raise ValueError(f"unknown {label}: {value!r}")
    return value


def _require(raw: Mapping[str, Any], key: str) -> str:
    value = str(raw.get(key, "")).strip()
    if not value:
        raise ValueError(f"missing required field {key!r}")
    return value


# The record statuses (people, places, orgs, and relationships). The
# vocabulary is GEDCOM-flavoured; the meanings are strict:
#   confirmed — actually confirmed, by attestation or the owner's verified word.
#   proposed  — guessed by an AGENT (the import, the AI) — awaiting review.
#   estimated — guessed by a HUMAN who wants it in the database as a guess
#               (the owner's own recollection — GEDCOM's EST qualifier, low
#               confidence). Never promoted to confirmed without a source.
# "estimated" is the only status a person may give their own guess; agents
# must not mark their guesses estimated (they get proposed), and nothing
# reaches confirmed without being confirmed (user).
RECORD_STATUSES = frozenset({"confirmed", "proposed", "estimated"})


def _status(raw: Mapping[str, Any]) -> Literal["confirmed", "proposed", "estimated"]:
    status = str(raw.get("status", "confirmed"))
    if status not in RECORD_STATUSES:
        raise ValueError(f"bad record status: {status!r}")
    return cast(Literal["confirmed", "proposed", "estimated"], status)


TRecord = TypeVar("TRecord")


def _unique_records(  # noqa: UP047  # pyrefly cannot infer PEP-695 T from the Callable argument; the TypeVar infers at each call site
    raw: Mapping[str, Any], key: str, record_type: Callable[[dict[str, Any]], TRecord], label: str
) -> tuple[TRecord, ...]:
    """Parse one identity table's records and enforce unique ids — the
    shared construction of the people/places/orgs/themes/imports tables."""
    records = tuple(record_type(r) for r in raw.get(key, []))
    # the constructor contract: every record class passed here (Person,
    # Place, Org, Theme, Session) carries ``id`` — pyrefly cannot express
    # that bound for frozen dataclasses, so the cast states the proven
    # contract
    ids = [cast(Any, r).id for r in records]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"duplicate {label} ids: {dupes}")
    return records


@dataclass(frozen=True)
class Person:
    """A cast member record — confirmed or proposed, one type. Serializes
    to the identity-table shape; the status appears only when proposed.
    ``dob``/``dod`` are DatedFacts — honest precision, never a fake exact
    date; ``occupations`` are forms attested in the artifacts.
    ``residence`` records where they lived and when — {place, from, to,
    status} — the household rule, modelled as residence events (GEDCOM X
    alignment: a residence is the person's fact, not a place's
    field); a deduction is proposed, never asserted."""

    id: str
    name: str
    aliases: tuple[str, ...] = ()
    email: str | None = None  # the identity seam: a verified Google account
    pronouns: str | None = None
    years: str = "—"
    relation: str = ""
    bio: str = ""
    hue: str | None = None
    dob: DatedFact | None = None
    dod: DatedFact | None = None
    occupations: tuple[str, ...] = ()
    residence: tuple[dict[str, Any], ...] = ()
    status: Literal["confirmed", "proposed", "estimated"] = "confirmed"
    # The estimated record's basis — {text, by, when}: the reviewer's own
    # words, the named person who recalled them, and the date. An estimate
    # without a basis isn't an estimate; the chip renders only what the
    # dataset carries (user).
    basis: dict[str, str] | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Person:
        record_id = _require(raw, "id")
        if not is_valid_record_id(record_id):
            raise ValueError(f"invalid record id: {record_id!r}")

        residence = raw.get("residence") or []
        for entry in residence:
            if not is_valid_record_id(str(entry.get("place", ""))):
                raise ValueError(f"invalid residence place id: {entry!r}")
        email = raw.get("email")
        if email is not None:
            email = str(email).strip().lower()
            if not EMAIL_RE.fullmatch(email):
                raise ValueError(f"invalid email: {email!r}")
        basis = raw.get("basis")
        if basis is not None:
            text = str(basis.get("text", "")).strip()
            if not text:
                raise ValueError(f"invalid basis: {basis!r} — the text is required")
            basis = {
                "text": text,
                "by": str(basis.get("by", "")).strip(),
                "when": str(basis.get("when", "")).strip(),
                **({"note": str(basis["note"]).strip()} if basis.get("note") else {}),
            }
        return cls(
            id=record_id,
            name=_require(raw, "name"),
            aliases=tuple(str(a) for a in (raw.get("aliases") or [])),
            email=email,
            pronouns=raw.get("pronouns"),
            years=str(raw.get("years", "—")),
            relation=str(raw.get("relation", "")),
            bio=str(raw.get("bio", "")),
            hue=raw.get("hue"),
            dob=_dated(raw, "dob"),
            dod=_dated(raw, "dod"),
            occupations=tuple(str(o) for o in (raw.get("occupations") or [])),
            residence=tuple(dict(e) for e in residence),
            status=_status(raw),
            basis=basis,
        )

    def as_proposed(self) -> Person:
        """The same person, marked proposed — the archive's propose seam."""
        return replace(self, status="proposed")

    def as_confirmed(self) -> Person:
        """The same person, confirmed — the archive's promote seam."""
        return replace(self, status="confirmed")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "name": self.name}
        if self.pronouns is not None:
            out["pronouns"] = self.pronouns
        out["aliases"] = list(self.aliases)
        if self.email is not None:
            out["email"] = self.email
        out["years"] = self.years
        out["relation"] = self.relation
        out["bio"] = self.bio
        if self.hue is not None:
            out["hue"] = self.hue
        if self.dob is not None:
            out["dob"] = self.dob.to_dict()
        if self.dod is not None:
            out["dod"] = self.dod.to_dict()
        if self.occupations:
            out["occupations"] = list(self.occupations)
        if self.residence:
            out["residence"] = [dict(e) for e in self.residence]
        if self.status != "confirmed":
            out["status"] = self.status
        if self.basis is not None:
            out["basis"] = dict(self.basis)
        return out


@dataclass(frozen=True)
class Place:
    """A place record — confirmed or proposed, one type (same seam as
    Person). Coordinates stay null until they are known; the note is honest
    provenance, never padding. ``address`` is the written form (house name,
    street, town). Households live on the people as residence events
    (GEDCOM X alignment), not on the place."""

    id: str
    name: str
    aliases: tuple[str, ...] = ()
    note: str = ""
    precision: str = ""
    lat: float | None = None
    lng: float | None = None
    x: int | None = None
    y: int | None = None
    address: str = ""
    status: Literal["confirmed", "proposed", "estimated"] = "confirmed"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Place:
        place_id = _require(raw, "id")
        if not is_valid_record_id(place_id):
            raise ValueError(f"invalid record id: {place_id!r}")
        precision = str(raw.get("precision", ""))
        if precision not in PLACE_PRECISIONS:
            raise ValueError(f"unknown place precision: {precision!r}")
        return cls(
            id=place_id,
            name=_require(raw, "name"),
            aliases=tuple(str(a) for a in (raw.get("aliases") or [])),
            note=str(raw.get("note", "")),
            precision=str(raw.get("precision", "")),
            lat=raw.get("lat"),
            lng=raw.get("lng"),
            x=raw.get("x"),
            y=raw.get("y"),
            address=str(raw.get("address", "")),
            status=_status(raw),
        )

    def as_proposed(self) -> Place:
        return replace(self, status="proposed")

    def as_confirmed(self) -> Place:
        return replace(self, status="confirmed")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "name": self.name}
        if self.aliases:
            out["aliases"] = list(self.aliases)
        out["note"] = self.note
        out["precision"] = self.precision
        out.update(lat=self.lat, lng=self.lng, x=self.x, y=self.y)
        if self.address:
            out["address"] = self.address
        if self.status != "confirmed":
            out["status"] = self.status
        return out


@dataclass(frozen=True)
class Relationship:
    """A directed family edge: label_a is what B is to A. The kinds are
    closed — the tree and the person pages branch on them. A spouse edge may
    carry the marriage date ({date, precision}, the dated-fact shape). The
    optional status distinguishes the import's proposals from a link the
    owner has put in themselves (user): proposed = awaiting
    review, confirmed = the owner's call. A missing status is an asserted
    edge with no review seam."""

    a: str
    b: str
    kind: str
    label_a: str
    label_b: str
    date: DatedFact | None = None
    status: Literal["confirmed", "proposed", "estimated"] | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Relationship:
        kind = str(raw.get("kind", ""))
        if kind not in RELATIONSHIP_KINDS:
            raise ValueError(f"unknown relationship kind: {kind!r}")
        status = raw.get("status")
        if status is not None and status not in RECORD_STATUSES:
            raise ValueError(f"bad relationship status: {status!r}")
        return cls(
            a=_require(raw, "a"),
            b=_require(raw, "b"),
            kind=kind,
            label_a=str(raw.get("label_a", "")),
            label_b=str(raw.get("label_b", "")),
            date=_dated(raw, "date"),
            status=status,
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "a": self.a,
            "b": self.b,
            "kind": self.kind,
            "label_a": self.label_a,
            "label_b": self.label_b,
        }
        if self.date is not None:
            out["date"] = self.date.to_dict()
        if self.status is not None:
            out["status"] = self.status
        return out


@dataclass(frozen=True)
class PeopleTable:
    """The people identity table: people + relationships, validated — unique
    ids, every relationship resolves, kinds closed. ``supersedes`` is
    archive-internal and never part of the projection shape."""

    people: tuple[Person, ...]
    relationships: tuple[Relationship, ...]
    supersedes: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PeopleTable:
        people = _unique_records(raw, key="people", record_type=Person.from_dict, label="person")
        relationships = tuple(Relationship.from_dict(r) for r in raw.get("relationships", []))
        known = {p.id for p in people}
        for rel in relationships:
            for end in (rel.a, rel.b):
                if end not in known:
                    raise ValueError(f"relationship {rel.kind} references unknown person {end}")
        return cls(people=people, relationships=relationships, supersedes=raw.get("supersedes"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "people": [p.to_dict() for p in self.people],
            "relationships": [r.to_dict() for r in self.relationships],
        }

    def has(self, person_id: str) -> bool:
        """Is this id in the table?"""
        return any(p.id == person_id for p in self.people)

    def record(self, person_id: str) -> Person | None:
        """The table's record for one id, or None — the id is the identity."""
        return next((p for p in self.people if p.id == person_id), None)

    def with_record(self, person: Person) -> PeopleTable:
        """The table with *person* replacing their own record — or appended
        when the id is new."""
        if self.has(person.id):
            return replace(self, people=tuple(person if p.id == person.id else p for p in self.people))
        return replace(self, people=self.people + (person,))

    def dismissed(self, person_id: str) -> PeopleTable:
        """The table without *person_id* or their relationships — a missing or
        non-proposed person fails loudly (a double dismiss is an error, never
        a silent no-op)."""
        person = self.record(person_id)
        # a missing person is an error to raise, never a silent stand-in
        if person is None:
            raise KeyError(f"no person {person_id}")
        if person.status != "proposed":
            raise ValueError(f"{person_id} is not proposed — dismiss only removes pending people")
        return replace(
            self,
            people=tuple(p for p in self.people if p.id != person_id),
            relationships=tuple(r for r in self.relationships if r.a != person_id and r.b != person_id),
        )

    def resolved(self, person_id: str, decision: str, basis: dict[str, str] | None) -> tuple[PeopleTable, Resolution]:
        """The table after one review disposition, and the verdict on it. The
        decision vocabulary is NOT the status vocabulary — ``confirm`` is a
        status, never an action: ``attested`` -> confirmed (the reviewer's own
        verified word); ``estimated`` -> the status estimated with the recorded
        basis; ``pending`` -> the import's guess stays proposed, nothing
        changes; ``delete`` -> the person leaves the table."""
        person = self.record(person_id)
        if person is None:
            # a duplicate delete (double-tap, two devices) finds the person
            # already removed — that is the already-resolved state, never an
            # error
            return self, Resolution()
        if person.status != "proposed":
            # the queue never holds resolved people — a stale decision is a
            # state, not an error: the person stays as they are
            return self, Resolution(person=person)
        if decision == "pending":
            return self, Resolution(person=person, attested=True)
        if decision == "delete":
            return self.dismissed(person_id), Resolution(person=GonePerson(person_id), changed=True, attested=True)
        if decision == "estimated":
            if basis is None or not str(basis.get("text", "")).strip():
                raise ValueError(f"estimated needs a basis: {person_id}")
            updated = replace(person, status="estimated", basis=basis)
            return self.with_record(updated), Resolution(person=updated, changed=True, attested=True)
        if decision == "attested":
            updated = person.as_confirmed()
            return self.with_record(updated), Resolution(person=updated, changed=True, attested=True)
        raise ValueError(f"unknown decision: {decision!r}")


@dataclass(frozen=True)
class PlacesTable:
    """The places identity table — unique ids, required fields."""

    places: tuple[Place, ...]
    supersedes: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PlacesTable:
        return cls(
            places=_unique_records(raw, key="places", record_type=Place.from_dict, label="place"),
            supersedes=raw.get("supersedes"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"places": [p.to_dict() for p in self.places]}

    def has(self, place_id: str) -> bool:
        """Is this id in the table?"""
        return any(p.id == place_id for p in self.places)

    def with_record(self, place: Place) -> PlacesTable:
        """The table with *place* replacing its own record — or appended when
        the id is new."""
        if self.has(place.id):
            return replace(self, places=tuple(place if p.id == place.id else p for p in self.places))
        return replace(self, places=self.places + (place,))


@dataclass(frozen=True)
class Org:
    """An organisation record — the third identity kind (docs/PRD/IMPORT-PRD.md
    §2.4): institutions the family engaged with (the Ministry of Supply,
    the Halifax Building Society). Same seam as Person/Place: confirmed in
    the identity table or proposed, one type. ``address`` and ``branch``
    are the written forms — an org's address is the org's, never a place
    record."""

    id: str
    name: str
    aliases: tuple[str, ...] = ()
    address: str = ""
    branch: str = ""
    note: str = ""
    status: Literal["confirmed", "proposed", "estimated"] = "confirmed"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Org:
        org_id = _require(raw, "id")
        if not is_valid_record_id(org_id):
            raise ValueError(f"invalid record id: {org_id!r}")
        return cls(
            id=org_id,
            name=_require(raw, "name"),
            aliases=tuple(str(a) for a in (raw.get("aliases") or [])),
            address=str(raw.get("address", "")),
            branch=str(raw.get("branch", "")),
            note=str(raw.get("note", "")),
            status=_status(raw),
        )

    def as_proposed(self) -> Org:
        return replace(self, status="proposed")

    def as_confirmed(self) -> Org:
        return replace(self, status="confirmed")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "name": self.name}
        if self.aliases:
            out["aliases"] = list(self.aliases)
        if self.address:
            out["address"] = self.address
        if self.branch:
            out["branch"] = self.branch
        if self.note:
            out["note"] = self.note
        if self.status != "confirmed":
            out["status"] = self.status
        return out


@dataclass(frozen=True)
class OrgsTable:
    """The organisations identity table — unique ids, required fields."""

    orgs: tuple[Org, ...]
    supersedes: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> OrgsTable:
        return cls(
            orgs=_unique_records(raw, key="orgs", record_type=Org.from_dict, label="org"),
            supersedes=raw.get("supersedes"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"orgs": [o.to_dict() for o in self.orgs]}


@dataclass(frozen=True)
class ThemesTable:
    """The themes identity table — the curator's arrangements: unique ids,
    every record named. The records themselves are carried verbatim (a
    theme is the curator's editorial object)."""

    themes: tuple[Theme, ...] = ()
    supersedes: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ThemesTable:
        return cls(
            themes=_unique_records(raw, key="themes", record_type=Theme.from_dict, label="theme"),
            supersedes=raw.get("supersedes"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"themes": [t.to_dict() for t in self.themes]}


@dataclass(frozen=True)
class Message:
    """One line of the review conversation — what the family saw. The
    assistant's lines also carry their THINKING: the model's raw verdict,
    verbatim. Both persist, and both go back to the model on every later
    call — the model always sees the whole conversation including its own
    reasoning (user: the flow misunderstood because the model
    couldn't see that an answer was re-answering an earlier question)."""

    role: Literal["user", "assistant"]
    text: str
    when: str
    thinking: str | None = None  # the raw verdict, assistant turns only

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Message:
        role = str(raw.get("role", ""))
        if role not in ("user", "assistant"):
            raise ValueError(f"unknown message role: {role!r}")
        return cls(
            role=role,
            text=str(raw.get("text", "")),
            when=str(raw.get("when", "")),
            thinking=raw.get("thinking"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"role": self.role, "text": self.text, "when": self.when}
        if self.thinking is not None:
            out["thinking"] = self.thinking
        return out


@dataclass(frozen=True)
class ReviewDecision:
    """A review's outcome — the person, the disposition, and the basis
    (the decision vocabulary is not the status vocabulary:
    attested / estimated / pending / delete)."""

    person_id: str
    decision: Literal["attested", "estimated", "pending", "delete"]
    when: str
    basis: dict[str, Any] | None = None
    last: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ReviewDecision:
        decision = str(raw.get("decision", ""))
        if decision not in ("attested", "estimated", "pending", "delete"):
            raise ValueError(f"unknown review decision: {decision!r}")
        return cls(
            person_id=_require(raw, "person_id"),
            decision=cast(Literal["attested", "estimated", "pending", "delete"], decision),
            when=str(raw.get("when", "")),
            basis=raw.get("basis"),
            last=bool(raw.get("last")),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"person_id": self.person_id, "decision": self.decision, "when": self.when}
        if self.basis is not None:
            out["basis"] = self.basis
        if self.last:
            out["last"] = True
        return out


@dataclass(frozen=True)
class Attempt:
    """One walk of an import review — the conversation (the messages the
    family saw) and the outcomes of that walk, separated so a diagnosis
    never mixes walks."""

    started: str
    messages: tuple[Message, ...] = ()
    decisions: tuple[ReviewDecision, ...] = ()

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Attempt:
        return cls(
            started=str(raw.get("started", "")),
            messages=tuple(Message.from_dict(m) for m in (raw.get("messages") or [])),
            decisions=tuple(ReviewDecision.from_dict(d) for d in (raw.get("decisions") or [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "started": self.started,
            "messages": [m.to_dict() for m in self.messages],
            "decisions": [d.to_dict() for d in self.decisions],
        }

    @property
    def finished(self) -> bool:
        """A walk with a conversation whose last decision completed the
        session."""
        return bool(self.messages) and any(d.last for d in self.decisions)


@dataclass(frozen=True)
class Session:
    """An import-review session — the lifecycle at a glance: the status,
    the resume point (``current``), and one attempt per walk. The archive's
    sessions' API (user: "restructure how we store the
    sessions so it's more obvious to fresh agents; extend the API to cover
    them") — the class owns the wire format and the invariants: a new
    attempt starts only when the last is empty or finished; a decision
    advances the resume point. The transcript is the MESSAGES — the
    assistant's words are server-built and shown verbatim, so a loaded
    transcript is what the family saw."""

    id: str
    title: str
    kind: str = "import-review"
    status: Literal["pending", "reviewed"] = "pending"
    current: str | None = None
    attempts: tuple[Attempt, ...] = ()

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Session:
        session_id = _require(raw, "id")
        if not is_valid_record_id(session_id):
            raise ValueError(f"invalid record id: {session_id!r}")
        status = str(raw.get("status", "pending"))
        if status not in ("pending", "reviewed"):
            raise ValueError(f"unknown session status: {status!r}")
        return cls(
            id=session_id,
            kind=str(raw.get("kind", "import-review")),
            title=_require(raw, "title"),
            status=status,
            current=raw.get("current"),
            attempts=tuple(Attempt.from_dict(a) for a in (raw.get("attempts") or [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "current": self.current,
            "attempts": [a.to_dict() for a in self.attempts],
        }

    def current_attempt(self) -> Attempt | None:
        return self.attempts[-1] if self.attempts else None

    def completed(self) -> Session:
        """The session is done — nothing left to review."""
        return replace(self, status="reviewed")

    def start_attempt(self) -> Session:
        """Begin a new walk — only when the last is empty or finished, so a
        mid-walk re-render continues the same attempt."""
        last = self.current_attempt()
        if last is None or last.finished:
            return replace(self, attempts=self.attempts + (Attempt(started=datetime.datetime.now(UTC).isoformat()),))
        return self

    def add_message(
        self, role: Literal["user", "assistant"], text: str, when: str, thinking: str | None = None
    ) -> Session:
        """Append one spoken line to the current attempt's conversation —
        the line the family saw, verbatim. The assistant's lines may carry
        their raw verdict as the thinking."""
        last = self.current_attempt() or Attempt(started=datetime.datetime.now(UTC).isoformat())
        updated = replace(last, messages=last.messages + (Message(role=role, text=text, when=when, thinking=thinking),))
        attempts = self.attempts[:-1] + (updated,) if self.attempts else (updated,)
        return replace(self, attempts=attempts)

    def add_decision(self, decision: ReviewDecision) -> Session:
        """Record a review outcome — it advances the resume point; the last
        decision clears it."""
        last = self.current_attempt() or Attempt(started=datetime.datetime.now(UTC).isoformat())
        updated = replace(last, decisions=last.decisions + (decision,))
        attempts = self.attempts[:-1] + (updated,) if self.attempts else (updated,)
        current = None if decision.last else decision.person_id
        return replace(self, attempts=attempts, current=current)


@dataclass(frozen=True)
class ImportsTable:
    """The import-session table — one record per import walk: the review's
    sessions, unique by id."""

    imports: tuple[Session, ...] = ()
    supersedes: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ImportsTable:
        return cls(
            imports=_unique_records(raw, key="imports", record_type=Session.from_dict, label="import session"),
            supersedes=raw.get("supersedes"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"imports": [s.to_dict() for s in self.imports]}

    def has(self, session_id: str) -> bool:
        """Is this session already in the table?"""
        return any(s.id == session_id for s in self.imports)

    def with_session(self, session: Session) -> ImportsTable:
        """The table with *session* present — an existing record with the same
        id is replaced in place (the id is the identity), never duplicated."""
        if self.has(session.id):
            return replace(self, imports=tuple(session if s.id == session.id else s for s in self.imports))
        return replace(self, imports=self.imports + (session,))

    def completed(self) -> ImportsTable:
        """Every pending session done — the import is finished."""
        return replace(self, imports=tuple(s.completed() if s.status == "pending" else s for s in self.imports))


@dataclass(frozen=True)
class ReviewContext:
    """The archive's attested facts the review's investigation reads — the
    people (deaths, relations), the recorded items' stories, and the
    family edges. The Knowledge's converted models drop the deaths and the
    stories, so the investigation reads the raw projection through this
    type (coding-standards: groups that travel together are a
    type)."""

    people: tuple[Person, ...]
    items: tuple[dict[str, Any], ...]
    relationships: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ReviewQueue:
    """The review's pending links — the proposed people awaiting a
    decision, and the already-placed count (the reconcile-first view; the
    queue never holds resolved people)."""

    pending: tuple[Person, ...]
    already: int


# The item's primary content, held outside the sidecar (docs/TECHSPEC.md
# §3): a story is story.txt, a letter or document's transcription is
# transcription.txt. Content files version with their sidecar: v1 ->
# story.txt, v2 -> story-2.txt, … (append-only).
CONTENT_FILES: dict[str, str] = {"story": "story.txt", "transcription": "transcription.txt"}
CONTENT_CAPTIONS: dict[str, str] = {"story": "The story, verbatim", "transcription": "The transcription"}


def _capture_transcription(sidecar: MutableMapping[str, Any], content: dict[str, str]) -> None:
    """Move the transcription out of the sidecar — it is primary content,
    not metadata — and, when present, keep it as a content file."""
    transcription = sidecar.pop("transcription", "") or ""
    if transcription:
        content["transcription"] = transcription


def split_content(item: Item) -> SplitItem:
    """Separate primary content from metadata at the write seam (capture,
    import): the story text (story-type items) and the transcription
    (letters/documents) become content files; descriptions — the story field
    on photos and objects — stay as metadata. Returns the item's sidecar and
    its content files; feed both to ``Archive.save_item``. The inverse of
    the derive engine's embedding (tools/derive.py)."""
    sidecar = dict(item.raw)
    content: dict[str, str] = {}
    item_type = sidecar["type"]
    if item_type == "story":
        story = sidecar.pop("story", "") or ""
        if story:
            content["story"] = story
        _capture_transcription(sidecar, content)  # a recorded testimony with a transcription keeps it
    elif item_type in ("letter", "document"):
        _capture_transcription(sidecar, content)
    else:  # photo, object — the story field is a description, keep it
        sidecar.pop("transcription", None)
    return SplitItem(sidecar=Item(sidecar), content=content)


def _story_flag(raw: Mapping[str, Any], item_type: str, key: str, story_message: str, allow_story: bool) -> Any:
    """One story flag (clarification, reflection, evidence): absent or a
    boolean, and the flag's own story rule must hold — the write seam
    fails loudly on anything else."""
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    if (item_type == "story") != allow_story:
        raise ValueError(story_message)
    return value


@dataclass(frozen=True)
class Item:
    """An archive item — the sidecar wire format (letter, document, photo,
    object, story, ...), the identity records' sibling. The whole object
    model lives in this module: validated at the write seam
    (archive.save_item), with typed accessors over the verbatim sidecar —
    a developer reads the model here, and validation never rewrites history
    (``to_dict`` is exactly the dict that was validated).

    Required: id, type, title, date, date_precision, status, assets,
    people, places, themes. A tombstone (``status: deleted``) carries only
    id/type/title/status/reason. Unknown fields pass through untouched."""

    raw: dict[str, Any]

    # -- typed accessors for the known vocabulary --------------------------
    @property
    def id(self) -> str:
        return str(self.raw.get("id", ""))

    @property
    def type(self) -> str:
        return str(self.raw.get("type", ""))

    @property
    def title(self) -> str:
        return str(self.raw.get("title", ""))

    @property
    def date(self) -> str:
        return str(self.raw.get("date", ""))

    @property
    def date_precision(self) -> str:
        return str(self.raw.get("date_precision", ""))

    @property
    def status(self) -> str:
        return str(self.raw.get("status", ""))

    @property
    def sensitive(self) -> bool:
        return bool(self.raw.get("sensitive"))

    @property
    def people_refs(self) -> tuple[Ref, ...]:
        return _refs(self.raw, "people")

    @property
    def place_refs(self) -> tuple[Ref, ...]:
        return _refs(self.raw, "places")

    @property
    def org_refs(self) -> tuple[Ref, ...]:
        return _refs(self.raw, "orgs")

    @property
    def item_refs(self) -> tuple[Ref, ...]:
        return _refs(self.raw, "items")

    @property
    def theme_refs(self) -> tuple[Ref, ...]:
        return _refs(self.raw, "themes")

    @property
    def date_mentions(self) -> tuple[DateMention, ...]:
        return tuple(DateMention.from_dict(m) for m in self.raw.get("date_mentions") or [])

    @property
    def assets(self) -> tuple[Asset, ...]:
        return tuple(Asset.from_dict(a) for a in self.raw.get("assets") or [])

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Item:
        """Validate a sidecar; raise ValueError on any invariant break."""
        item = cls(dict(raw))
        record_id = _require(raw, "id")
        if not is_valid_record_id(record_id):
            raise ValueError(f"invalid record id: {record_id!r}")
        item_type = _required_value(raw, key="type", vocab=ITEM_TYPES, label="item type")
        status = _required_value(raw, key="status", vocab=ITEM_STATUSES, label="item status")
        if status == "deleted":  # the tombstone shape — nothing else required
            return item
        if item_type == "event":
            kind = str(raw.get("kind", "")).strip()
            if not kind:
                raise ValueError("an event item needs a kind (birth|marriage|death|other)")
            if kind not in EVENT_KINDS:
                raise ValueError(f"unknown event kind: {kind!r}")
        _require(raw, "title")
        _require(raw, "date")
        precision = _required_value(raw, key="date_precision", vocab=PRECISIONS, label="date precision")
        if not viable_date(str(raw.get("date", ""))):
            # fail loudly at the write seam — an item with no viable date is
            # invisible or misdated everywhere; the whole form
            # must parse, not just the year prefix: 2026-99-99 is not a date
            raise ValueError(f"date is not parseable: {raw.get('date')!r}")
        if precision == "between" and not viable_date(str(raw.get("date2", ""))):
            raise ValueError(f"date2 is not parseable: {raw.get('date2')!r}")
        _validate_refs(raw.get("people"), "people")
        _validate_refs(raw.get("places"), "places")
        _validate_refs(raw.get("orgs"), "orgs")
        _validate_refs(raw.get("themes"), "themes")
        _validate_refs(raw.get("items"), "items")
        _validate_assets(raw.get("assets"))
        for source in raw.get("sources") or []:
            url = str(source.get("url", "")).strip()
            if not url.startswith(("http://", "https://")):
                raise ValueError(f"source needs an http(s) url: {source!r}")
            if not str(source.get("accessed", "")).strip():
                raise ValueError(f"source needs an access date: {source!r}")
        _validate_date_mentions(raw.get("date_mentions"))
        transcription_status = raw.get("transcription_status")
        if transcription_status not in (None, "") and transcription_status not in TRANSCRIPTION_STATUSES:
            raise ValueError(f"unknown transcription_status: {transcription_status!r}")
        sensitive = raw.get("sensitive")
        if sensitive is not None and not isinstance(sensitive, bool):
            raise ValueError("sensitive must be a boolean")
        clarification = _story_flag(
            raw,
            item_type,
            key="clarification",
            story_message="only a story can be a clarification fragment",
            allow_story=True,
        )
        if clarification is not None and not (raw.get("people") or raw.get("items")):
            raise ValueError("a clarification fragment must name what it attests (people or items)")
        reflection = _story_flag(
            raw, item_type, key="reflection", story_message="only a story can be a reflection", allow_story=True
        )
        if reflection is not None:
            if clarification:
                raise ValueError("a story is a clarification or a reflection, not both")
            if not (raw.get("people") or raw.get("places")):
                raise ValueError("a reflection must mention someone or somewhere (people or places)")
        evidence = _story_flag(
            raw,
            item_type,
            key="evidence",
            story_message="a story is never evidence — accounts, fragments and reflections are",
            allow_story=False,
        )
        if evidence is not None and not (raw.get("people") or raw.get("places") or raw.get("items")):
            raise ValueError("an evidence record must attest someone or somewhere (people, places or items)")
        return item

    @classmethod
    def tombstone(cls, item_id: str, reason: str, current: Item | None = None) -> Item:
        """The tombstone that supersedes a deleted item — the marker shape
        (id/type/title/status/reason only; the old files stay forever).
        ``current`` is the item as it stands, so its own type and title
        survive the delete; a missing item falls back to the archive's own
        words."""
        item_type = current.type if current is not None else "item"
        title = current.title if current is not None and current.title else item_id
        return cls({"id": item_id, "type": item_type, "title": title, "status": "deleted", "reason": reason})

    def to_dict(self) -> dict[str, Any]:
        return dict(self.raw)


def _refs(raw: Mapping[str, Any], kind: str) -> tuple[Ref, ...]:
    """The item's refs of one kind, typed — the accessors' one construction."""
    return tuple(Ref.from_dict(r, kind) for r in raw.get(kind) or [])


def _validate_refs(refs: Any, label: str) -> None:
    """Refs (people/places/themes/orgs/items) are {id, status?, date?} entries.
    Any ref may carry an involvement date — when THAT entity's involvement
    with the item happened, for long-lived documents written into over time
    (a family record's entries, a guest book's signatures, a logbook's
    boats)."""
    for ref in refs or []:
        Ref.from_dict(ref, label)


def _validate_assets(assets: Any) -> None:
    for asset in assets or []:
        Asset.from_dict(asset)


def _validate_date_mentions(mentions: Any) -> None:
    for mention in mentions or []:
        DateMention.from_dict(mention)


IdentityTable = PeopleTable | PlacesTable | OrgsTable | ThemesTable | ImportsTable


# The identity tables, by the name the archive's store knows them by — one
# typed record per name, the publish seam's dispatch.
_IDENTITY_TABLES: tuple[tuple[str, type[IdentityTable]], ...] = (
    ("people", PeopleTable),
    ("places", PlacesTable),
    ("orgs", OrgsTable),
    ("themes", ThemesTable),
    ("imports", ImportsTable),
)


def validate_identity(name: str, table: Mapping[str, Any]) -> IdentityTable:
    """Parse one identity table's wire record, validated — the publish
    seam's one entry (``supersedes`` is dropped: the chain is
    archive-internal, not content). Raises ValueError on any invariant
    break; derive wraps it as a DeriveError so a bad table fails publish
    loudly."""
    record = dict(table)
    for table_name, table_type in _IDENTITY_TABLES:
        if table_name == name:
            return table_type.from_dict(record)
    raise ValueError(f"unknown identity table: {name}")
