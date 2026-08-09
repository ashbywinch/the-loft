"""The archive's domain record types (docs/coding-standards.md: a group's
members are their own types) — typed, validated, serialisable records for
the identity tables, the proposed queue and the items: Person, Place, Org,
Relationship, Item and the table wrappers. This module IS the object model:
every vocabulary (relationship kinds, date precisions, item types and
statuses) lives here, and ``validate_identity`` / ``Item.from_dict`` are the
single validation seam — a record or item that isn't one of these types was
never written (2026-08-05: the Item record closed the gap — items were raw
dicts whose shape lived only in the docs).

One type for a person whether confirmed (in the identity table) or proposed
(awaiting review) — the difference is the ``status`` field, and every record
round-trips the exact JSON the store writes (crash resumption: the archive
is the persisted state, so the classes own the wire format). The classes
are the only place the table invariants live: unique ids, required fields,
closed relationship kinds, every relationship resolves. ``validate_identity``
is what derive calls at publish — a bad table fails loudly instead of
shipping (2026-08-05: the raw-dict tables had none of these guards).
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, replace
from datetime import UTC
from typing import Any, Literal, cast

RELATIONSHIP_KINDS = frozenset({"spouse", "parent", "sibling", "inlaw", "teacher"})

# The date-precision vocabulary (2026-08-05, GEDCOM alignment): exact /
# month / year express granularity (a year-only date is exact at year
# granularity, never uncertainty); approx = about; before / after / between
# carry bounds the artifacts actually state ("Aft. 1881", "Bet. 1880-1881").
# ``between`` carries the upper bound in date2.
PRECISIONS = frozenset({"exact", "month", "year", "approx", "before", "after", "between"})

# The place-coordinate granularity (2026-08-05): how precisely the stored
# point locates the place. "" = unset (treated as a point); exact = the
# coordinate is the place (street address, surveyed point); street = the
# point is the street/square and the place is on it (the Lark Inn is on
# Market Square — the exact building is not pinned); town/county/region =
# the point is the containing area's centre; country/continent = the point
# is the area's centroid (a mention, never a precise pin). The map draws
# uncertainty at the right size.
PLACE_PRECISIONS = frozenset({"", "exact", "street", "town", "county", "region", "country", "continent"})

# The item vocabulary (2026-08-05): the sidecar's closed sets. ``deleted``
# is the tombstone shape (id/type/title/status/reason only). ``event`` is an
# attested happening (a birth, a marriage, a concert a letter mentions) —
# its kind is required and closed (2026-08-05).
ITEM_TYPES = frozenset({"letter", "document", "photo", "object", "ephemera", "audio", "video", "story", "event"})
EVENT_KINDS = frozenset({"birth", "marriage", "death", "other"})
ITEM_STATUSES = frozenset({"draft", "catalogued", "deleted"})
TRANSCRIPTION_STATUSES = frozenset({"none", "draft", "confirmed"})

# The one record-id rule: a lowercase letter then letters/digits/hyphens
# (a person, a place, a story — the dataset's ids). Record ids become
# store paths (assets/<id>/, proposed/people/<id>.json) and output
# filenames (avatar-<id>.svg) — anything else could escape the archive root
# (2026-08-05 bot review, security). The classes own the rule; archive.py's
# write paths enforce it too.
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

RECORD_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def is_valid_record_id(record_id: str) -> bool:
    return bool(RECORD_ID_RE.fullmatch(record_id))


def _viable_date(value: str) -> bool:
    """A real calendar date in the archive's flexible forms: YYYY,
    YYYY-MM, or YYYY-MM-DD with valid month and day — 2026-99-99 and
    2026-02-31 are not dates. The granularity stays the precision's
    business; the form just has to be true (2026-08-06 review)."""
    m = re.fullmatch(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", value)
    if not m:
        return False
    month, day = m.group(2), m.group(3)
    if month and not 1 <= int(month) <= 12:
        return False
    if day:
        try:
            datetime.date(int(m.group(1)), int(month), int(day))
        except ValueError:
            return False
    return True


def _require(raw: dict[str, Any], key: str) -> str:
    value = str(raw.get(key, "")).strip()
    if not value:
        raise ValueError(f"missing required field {key!r}")
    return value


def _parse_dated(value: Any, key: str) -> dict[str, str] | None:
    """A dated fact: {date, precision, date2?} — the person dob/dod shape,
    shared with relationship dates (a marriage's date rides the spouse edge,
    2026-08-05). None when the field is absent; raises on a malformed one."""
    if not value:
        return None
    date_str = str(value.get("date", "")).strip()
    if not date_str:
        raise ValueError(f"{key} needs a date")
    if not _viable_date(date_str):
        raise ValueError(f"{key} has an impossible date {date_str!r}")  # 2026-99-99 is not a date (review, 2026-08-07)
    precision = str(value.get("precision", "exact"))
    if precision not in PRECISIONS:
        raise ValueError(f"{key} has unknown precision {precision!r}")
    out = {"date": date_str, "precision": precision}
    if precision == "between":
        date2 = str(value.get("date2", "")).strip()
        if not date2:
            raise ValueError(f"{key} with precision 'between' needs date2")
        if not _viable_date(date2):
            raise ValueError(f"{key} has an impossible date {date2!r}")
        out["date2"] = date2
    return out


# The record statuses (people, places, orgs, and — since 2026-08-08 —
# relationships). The vocabulary is GEDCOM-flavoured; the meanings are strict:
#   confirmed — actually confirmed, by attestation or the owner's verified word.
#   proposed  — guessed by an AGENT (the import, the AI) — awaiting review.
#   estimated — guessed by a HUMAN who wants it in the database as a guess
#               (the owner's own recollection — GEDCOM's EST qualifier, low
#               confidence). Never promoted to confirmed without a source.
# "estimated" is the only status a person may give their own guess; agents
# must not mark their guesses estimated (they get proposed), and nothing
# reaches confirmed without being confirmed (user, 2026-08-08).
RECORD_STATUSES = frozenset({"confirmed", "proposed", "estimated"})


def _status(raw: dict[str, Any]) -> Literal["confirmed", "proposed", "estimated"]:
    status = str(raw.get("status", "confirmed"))
    if status not in RECORD_STATUSES:
        raise ValueError(f"bad record status: {status!r}")
    return cast(Literal["confirmed", "proposed", "estimated"], status)


@dataclass(frozen=True)
class Person:
    """A cast member record — confirmed or proposed, one type. Serializes
    to the identity-table shape; the status appears only when proposed.
    ``dob``/``dod`` are {date, precision} — honest precision, never a fake
    exact date; ``occupations`` are forms attested in the artifacts.
    ``residence`` records where they lived and when — {place, from, to,
    status} — the household rule, modelled as residence events (GEDCOM X
    alignment, 2026-08-05: a residence is the person's fact, not a place's
    field); a deduction is proposed, never asserted."""

    id: str
    name: str
    aliases: tuple[str, ...] = ()
    email: str | None = None  # the identity seam (2026-08-06): a verified Google account
    pronouns: str | None = None
    years: str = "—"
    relation: str = ""
    bio: str = ""
    hue: str | None = None
    dob: dict[str, str] | None = None
    dod: dict[str, str] | None = None
    occupations: tuple[str, ...] = ()
    residence: tuple[dict[str, Any], ...] = ()
    status: Literal["confirmed", "proposed", "estimated"] = "confirmed"
    # The estimated record's basis — {text, by, when}: the reviewer's own
    # words, the named person who recalled them, and the date. An estimate
    # without a basis isn't an estimate; the chip renders only what the
    # dataset carries (user, 2026-08-09).
    basis: dict[str, str] | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Person:
        record_id = _require(raw, "id")
        if not is_valid_record_id(record_id):
            raise ValueError(f"invalid record id: {record_id!r}")

        def _date_field(key: str) -> dict[str, str] | None:
            return _parse_dated(raw.get(key), key)

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
            dob=_date_field("dob"),
            dod=_date_field("dod"),
            occupations=tuple(str(o) for o in (raw.get("occupations") or [])),
            residence=tuple(dict(e) for e in residence),
            status=_status(raw),
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
            out["dob"] = self.dob
        if self.dod is not None:
            out["dod"] = self.dod
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
    (GEDCOM X alignment, 2026-08-05), not on the place."""

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
        out["lat"] = self.lat
        out["lng"] = self.lng
        out["x"] = self.x
        out["y"] = self.y
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
    owner has put in themselves (user, 2026-08-08): proposed = awaiting
    review, confirmed = the owner's call. A missing status is an asserted
    edge with no review seam."""

    a: str
    b: str
    kind: str
    label_a: str
    label_b: str
    date: dict[str, str] | None = None
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
            date=_parse_dated(raw.get("date"), "relationship date"),
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
            out["date"] = self.date
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
        people = tuple(Person.from_dict(p) for p in raw.get("people", []))
        ids = [p.id for p in people]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"duplicate person ids: {dupes}")
        relationships = tuple(Relationship.from_dict(r) for r in raw.get("relationships", []))
        known = set(ids)
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


@dataclass(frozen=True)
class PlacesTable:
    """The places identity table — unique ids, required fields."""

    places: tuple[Place, ...]
    supersedes: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PlacesTable:
        places = tuple(Place.from_dict(p) for p in raw.get("places", []))
        ids = [p.id for p in places]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"duplicate place ids: {dupes}")
        return cls(places=places, supersedes=raw.get("supersedes"))

    def to_dict(self) -> dict[str, Any]:
        return {"places": [p.to_dict() for p in self.places]}


@dataclass(frozen=True)
class Org:
    """An organisation record — the third identity kind (docs/IMPORT-PRD.md
    §2.4): institutions the family engaged with (the Ministry of Supply,
    the Halifax Building Society). Same seam as Person/Place: confirmed in
    the identity table or proposed, one type. ``address`` and ``branch``
    are the written forms — an org's address is the org's, never a place
    record (2026-08-05 import interview)."""

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
        orgs = tuple(Org.from_dict(o) for o in raw.get("orgs", []))
        ids = [o.id for o in orgs]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"duplicate org ids: {dupes}")
        return cls(orgs=orgs, supersedes=raw.get("supersedes"))

    def to_dict(self) -> dict[str, Any]:
        return {"orgs": [o.to_dict() for o in self.orgs]}


@dataclass(frozen=True)
class Message:
    """One line of the review conversation — what the family saw. The
    assistant's lines also carry their THINKING: the model's raw verdict,
    verbatim. Both persist, and both go back to the model on every later
    call — the model always sees the whole conversation including its own
    reasoning (2026-08-09, user: the flow misunderstood because the model
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
    (2026-08-09; the decision vocabulary is not the status vocabulary:
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
            decision=decision,  # type: ignore[arg-type]
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
    never mixes walks (2026-08-09: the accumulated-mess fix)."""

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
    sessions' API (2026-08-09, user: "restructure how we store the
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
class ReviewContext:
    """The archive's attested facts the review's investigation reads — the
    people (deaths, relations), the recorded items' stories, and the
    family edges. The Knowledge's converted models drop the deaths and the
    stories, so the investigation reads the raw projection through this
    type (2026-08-09; coding-standards: groups that travel together are a
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
        return bool(self.raw.get("sensitive", False))

    @property
    def story(self) -> str:
        return str(self.raw.get("story", ""))

    @property
    def people_refs(self) -> list[dict[str, Any]]:
        return list(self.raw.get("people") or [])

    @property
    def place_refs(self) -> list[dict[str, Any]]:
        return list(self.raw.get("places") or [])

    @property
    def org_refs(self) -> list[dict[str, Any]]:
        return list(self.raw.get("orgs") or [])

    @property
    def item_refs(self) -> list[dict[str, Any]]:
        return list(self.raw.get("items") or [])

    @property
    def theme_refs(self) -> list[dict[str, Any]]:
        return list(self.raw.get("themes") or [])

    @property
    def date_mentions(self) -> list[dict[str, Any]]:
        return list(self.raw.get("date_mentions") or [])

    @property
    def assets(self) -> list[dict[str, Any]]:
        return list(self.raw.get("assets") or [])

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Item:
        """Validate a sidecar; raise ValueError on any invariant break."""
        item = cls(dict(raw))
        record_id = _require(raw, "id")
        if not is_valid_record_id(record_id):
            raise ValueError(f"invalid record id: {record_id!r}")
        item_type = _require(raw, "type")
        if item_type not in ITEM_TYPES:
            raise ValueError(f"unknown item type: {item_type!r}")
        status = _require(raw, "status")
        if status not in ITEM_STATUSES:
            raise ValueError(f"unknown item status: {status!r}")
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
        precision = _require(raw, "date_precision")
        if precision not in PRECISIONS:
            raise ValueError(f"unknown date precision: {precision!r}")
        if not _viable_date(str(raw.get("date", ""))):
            # fail loudly at the write seam — an item with no viable date is
            # invisible or misdated everywhere (2026-08-06); the whole form
            # must parse, not just the year prefix: 2026-99-99 is not a date
            # (review, 2026-08-06)
            raise ValueError(f"date is not parseable: {raw.get('date')!r}")
        if precision == "between" and not _viable_date(str(raw.get("date2", ""))):
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
        clarification = raw.get("clarification")
        if clarification is not None:
            if not isinstance(clarification, bool):
                raise ValueError("clarification must be a boolean")
            if item_type != "story":
                raise ValueError("only a story can be a clarification fragment")
            if not (raw.get("people") or raw.get("items")):
                raise ValueError("a clarification fragment must name what it attests (people or items)")
        reflection = raw.get("reflection")
        if reflection is not None:
            if not isinstance(reflection, bool):
                raise ValueError("reflection must be a boolean")
            if item_type != "story":
                raise ValueError("only a story can be a reflection")
            if clarification:
                raise ValueError("a story is a clarification or a reflection, not both")
            if not (raw.get("people") or raw.get("places")):
                raise ValueError("a reflection must mention someone or somewhere (people or places)")
        evidence = raw.get("evidence")
        if evidence is not None:
            if not isinstance(evidence, bool):
                raise ValueError("evidence must be a boolean")
            if item_type == "story":
                raise ValueError("a story is never evidence — accounts, fragments and reflections are")
            if not (raw.get("people") or raw.get("places") or raw.get("items")):
                raise ValueError("an evidence record must attest someone or somewhere (people, places or items)")
        return item

    def to_dict(self) -> dict[str, Any]:
        return dict(self.raw)


def _validate_refs(refs: Any, label: str) -> None:
    """Refs (people/places/themes/orgs/items) are {id, status?, date?} entries.
    Any ref may carry an involvement date — when THAT entity's involvement
    with the item happened, for long-lived documents written into over time
    (a family record's entries, a guest book's signatures, a logbook's
    boats; 2026-08-06)."""
    for ref in refs or []:
        if not str(ref.get("id", "")).strip():
            raise ValueError(f"{label} ref missing id: {ref!r}")
        status = ref.get("status")
        if status not in (None, "proposed", "confirmed"):
            raise ValueError(f"{label} ref has bad status: {ref!r}")
        if ref.get("date") is not None:
            _parse_dated(ref.get("date"), f"{label} ref date")


def _validate_assets(assets: Any) -> None:
    for asset in assets or []:
        if not str(asset.get("kind", "")).strip() or not str(asset.get("file", "")).strip():
            raise ValueError(f"asset needs kind and file: {asset!r}")


def _validate_date_mentions(mentions: Any) -> None:
    for mention in mentions or []:
        if not str(mention.get("date", "")).strip():
            raise ValueError(f"date_mention missing date: {mention!r}")
        precision = mention.get("precision", "exact")
        if precision not in PRECISIONS:
            raise ValueError(f"date_mention has unknown precision: {mention!r}")


def validate_identity(name: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Validate one identity table and return its projection shape —
    ``supersedes`` stripped (the chain is archive-internal, not content).
    Raises ValueError on any invariant break; derive wraps it as a
    DeriveError so a bad table fails publish loudly."""
    if name == "people":
        return PeopleTable.from_dict(raw).to_dict()
    if name == "places":
        return PlacesTable.from_dict(raw).to_dict()
    if name == "orgs":
        return OrgsTable.from_dict(raw).to_dict()
    if name == "themes":
        themes = raw.get("themes", [])
        ids = [str(t.get("id", "")) for t in themes]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"duplicate theme ids: {dupes}")
        for theme in themes:
            if not str(theme.get("id", "")).strip() or not str(theme.get("title", "")).strip():
                raise ValueError("theme records need id and title")
        return {"themes": themes}
    raise ValueError(f"unknown identity table: {name}")
