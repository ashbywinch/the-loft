"""Tests for the archive's domain record types (tools/records.py): typed,
validated, serialisable — the same JSON shape the store writes and reads,
with the invariants the raw-dict tables were missing (2026-08-05)."""

from __future__ import annotations

import pytest

from tools.records import Item, Org, OrgsTable, PeopleTable, Person, Place, PlacesTable, Relationship, validate_identity


def test_place_rejects_escaping_record_id() -> None:
    """The record-id rule applies to every record the classes parse — Place
    ids may derive filenames in future paths (proposed/<id>.json exists
    today), so a crafted id fails parse like a person's does (2026-08-05
    bot review)."""
    with pytest.raises(ValueError, match="invalid record id"):
        Place.from_dict({"id": "../evil", "name": "Evil"})
    with pytest.raises(ValueError, match="invalid record id"):
        PlacesTable.from_dict({"places": [{"id": "a/b", "name": "X"}]})


def test_person_rejects_escaping_record_id() -> None:
    """The record id is the wire format's one filename source (avatar-<id>.svg,
    proposed/<id>.json) — a crafted id must fail parse, never reach a store
    path (2026-08-05 bot review, security)."""
    with pytest.raises(ValueError, match="invalid record id"):
        Person.from_dict({"id": "../../evil", "name": "Evil"})
    with pytest.raises(ValueError, match="invalid record id"):
        PeopleTable.from_dict({"people": [{"id": "a/../b", "name": "X"}], "relationships": []})
    with pytest.raises(ValueError, match="invalid record id"):
        PeopleTable.from_dict(
            {"people": [{"id": "p-ok", "name": "X"}, {"id": "P-Bad", "name": "Y"}], "relationships": []}
        )


def test_person_round_trip_confirmed_omits_status() -> None:
    """A confirmed cast member's record keeps the identity-table shape —
    status is the default, never serialized."""
    raw = {
        "id": "p-nora",
        "name": "Nora Hale",
        "pronouns": "she/her",
        "aliases": ["Mum"],
        "years": "—",
        "relation": "the letters' writer",
        "bio": "Viola player.",
        "hue": "amber",
    }
    assert Person.from_dict(raw).to_dict() == raw


def test_person_proposed_serializes_status() -> None:
    person = Person.from_dict({"id": "p-nova", "name": "Nova", "relation": "added from a story"})
    assert person.status == "confirmed"
    proposed = person.as_proposed()
    assert proposed.status == "proposed"
    assert proposed.to_dict()["status"] == "proposed"
    assert person.as_proposed().as_confirmed().to_dict() == person.to_dict()


def test_person_requires_id_and_name() -> None:
    with pytest.raises(ValueError, match="id"):
        Person.from_dict({"name": "No id"})
    with pytest.raises(ValueError, match="name"):
        Person.from_dict({"id": "p-x", "name": ""})


def test_relationship_validates_kind() -> None:
    Relationship.from_dict({"a": "p-a", "b": "p-b", "kind": "spouse", "label_a": "spouse", "label_b": "spouse"})
    with pytest.raises(ValueError, match="kind"):
        Relationship.from_dict({"a": "p-a", "b": "p-b", "kind": "pet", "label_a": "", "label_b": ""})


def test_people_table_rejects_duplicate_ids() -> None:
    raw = {"people": [{"id": "p-a", "name": "A"}, {"id": "p-a", "name": "A again"}], "relationships": []}
    with pytest.raises(ValueError, match="duplicate"):
        PeopleTable.from_dict(raw)


def test_people_table_rejects_dangling_relationship() -> None:
    raw = {
        "people": [{"id": "p-a", "name": "A"}],
        "relationships": [{"a": "p-a", "b": "p-ghost", "kind": "spouse", "label_a": "spouse", "label_b": "spouse"}],
    }
    with pytest.raises(ValueError, match="p-ghost"):
        PeopleTable.from_dict(raw)


def test_people_table_round_trip_strips_supersedes() -> None:
    raw = {"people": [{"id": "p-a", "name": "A"}], "relationships": [], "supersedes": "people.json"}
    table = PeopleTable.from_dict(raw).to_dict()
    assert "supersedes" not in table
    assert table["people"] == [
        {"id": "p-a", "name": "A", "aliases": [], "years": "—", "relation": "", "bio": ""}
    ]  # canonical record shape
    assert table["relationships"] == []


def test_place_round_trip_with_status() -> None:
    proposed = Place.from_dict({"id": "pl-x", "name": "X", "status": "proposed", "lat": None})
    assert proposed.status == "proposed"
    assert proposed.to_dict()["status"] == "proposed"
    confirmed = Place.from_dict({"id": "pl-x", "name": "X"})
    assert "status" not in confirmed.to_dict()


def test_places_table_rejects_duplicate_ids() -> None:
    raw = {"places": [{"id": "pl-a", "name": "A"}, {"id": "pl-a", "name": "A again"}]}
    with pytest.raises(ValueError, match="duplicate"):
        validate_identity("places", raw)


def test_place_precision_round_trip() -> None:
    """The structured precision field (country/continent) survives the
    Place round-trip — vague places must never be presented as exact on
    the map (PRD §19.7, 2026-08-05 bot review)."""
    raw = {
        "id": "pl-tornia",
        "name": "Tornia",
        "note": "Where Harper and Dale lived.",
        "precision": "country",
        "lat": 39.0,
        "lng": 35.0,
        "x": 96,
        "y": 12,
    }
    result = Place.from_dict(raw).to_dict()
    assert result["precision"] == "country"
    assert result["note"] == "Where Harper and Dale lived."
    default = Place.from_dict({"id": "pl-x", "name": "X"})
    assert default.to_dict()["precision"] == ""
    default = Place.from_dict({"id": "pl-x", "name": "X", "precision": ""})
    assert default.to_dict()["precision"] == ""


def test_place_precision_is_a_closed_vocabulary() -> None:
    # An imperfectly specified place must carry an honest granularity —
    # "town" for a building known to be somewhere in a settlement (the
    # Lark Inn), never a made-up value the renderer can't understand
    # (2026-08-05).
    for precision in ("exact", "street", "town", "county", "region", "country", "continent"):
        place = Place.from_dict({"id": "pl-x", "name": "X", "precision": precision})
        assert place.to_dict()["precision"] == precision
    with pytest.raises(ValueError, match="precision"):
        Place.from_dict({"id": "pl-x", "name": "X", "precision": "banana"})


def test_validate_identity_rejects_bad_people_table() -> None:
    raw = {
        "people": [{"id": "p-a", "name": "A"}],
        "relationships": [{"a": "p-a", "b": "p-ghost", "kind": "spouse", "label_a": "x", "label_b": "y"}],
    }
    with pytest.raises(ValueError, match="p-ghost"):
        validate_identity("people", raw)


def test_person_round_trip_with_dates_and_occupations() -> None:
    """dob/dod carry honest precision; occupations are attested forms — all
    survive the wire format (2026-08-05 import interview)."""
    raw = {
        "id": "p-fern",
        "name": "Fern Voss",
        "aliases": ["Fern", "Fern Kendall"],
        "years": "—",
        "relation": "",
        "bio": "",
        "dob": {"date": "1904-03-19", "precision": "exact"},
        "dod": {"date": "1988-06-04", "precision": "exact"},
        "occupations": ["tallow chandler"],
    }
    assert Person.from_dict(raw).to_dict() == raw
    bare = Person.from_dict({"id": "p-x", "name": "X"})
    assert "dob" not in bare.to_dict() and "occupations" not in bare.to_dict()


def test_person_round_trip_with_residence() -> None:
    """Residence is a person fact — {place, from, to, status} — the GEDCOM X
    alignment for the household rule (2026-08-05); a deduction is proposed."""
    raw = {
        "id": "p-miles",
        "name": "Miles Hale",
        "aliases": [],
        "years": "—",
        "relation": "",
        "bio": "",
        "residence": [
            {"place": "pl-marlock", "from": "1973", "to": "1973", "status": "confirmed"},
            {"place": "pl-dunhollow", "from": "1949", "to": "1949", "status": "proposed"},
        ],
    }
    assert Person.from_dict(raw).to_dict() == raw
    bare = Person.from_dict({"id": "p-x", "name": "X"})
    assert "residence" not in bare.to_dict()


def test_person_rejects_invalid_residence_place_id() -> None:
    with pytest.raises(ValueError, match="residence"):
        Person.from_dict({"id": "p-x", "name": "X", "residence": [{"place": "a/b", "from": "", "to": ""}]})


def test_person_dates_support_bound_precisions() -> None:
    """before / after / between carry the bounds the artifacts actually
    state ("Aft. 1881", "Bet. 1880-1881") — GEDCOM 7 alignment (2026-08-05);
    between needs date2, and the wire format omits it otherwise."""
    raw = {
        "id": "p-x",
        "name": "X",
        "aliases": [],
        "years": "—",
        "relation": "",
        "bio": "",
        "dob": {"date": "1917", "precision": "after"},
        "dod": {"date": "1880", "date2": "1881", "precision": "between"},
    }
    assert Person.from_dict(raw).to_dict() == raw
    exact = Person.from_dict({"id": "p-y", "name": "Y", "dob": {"date": "1871-01-07", "precision": "exact"}})
    assert "date2" not in exact.to_dict()["dob"]
    with pytest.raises(ValueError, match="between"):
        Person.from_dict({"id": "p-z", "name": "Z", "dob": {"date": "1880", "precision": "between"}})
    with pytest.raises(ValueError, match="precision"):
        Person.from_dict({"id": "p-z", "name": "Z", "dob": {"date": "1880", "precision": "whenever"}})


def test_org_round_trip_and_table() -> None:
    """Organisations are the third identity kind — with the org's own
    address (never a place record), same seam as people/places."""
    raw = {
        "orgs": [
            {
                "id": "org-ministry-of-supply",
                "name": "Ministry of Supply",
                "address": "Ivybridge House, Adam Street, Aldgate W.C.2",
            }
        ]
    }
    assert OrgsTable.from_dict(raw).to_dict() == raw
    with pytest.raises(ValueError, match="duplicate"):
        OrgsTable.from_dict({"orgs": [{"id": "org-x", "name": "X"}, {"id": "org-x", "name": "X again"}]})


def test_org_proposed_status_round_trip() -> None:
    org = Org.from_dict({"id": "org-x", "name": "X"}).as_proposed()
    assert org.to_dict()["status"] == "proposed"
    assert org.as_confirmed().to_dict().get("status") is None


def test_validate_identity_supports_orgs() -> None:
    out = validate_identity("orgs", {"orgs": [{"id": "org-x", "name": "X"}], "supersedes": "orgs.json"})
    assert "supersedes" not in out
    assert out == {"orgs": [{"id": "org-x", "name": "X"}]}


def test_item_round_trip_is_verbatim() -> None:
    """The Item record validates and reads the sidecar verbatim — unknown
    fields pass through untouched; validation never rewrites history."""
    raw = {
        "id": "letter-x",
        "type": "letter",
        "title": "X",
        "date": "1949-02-04",
        "date_precision": "exact",
        "description": "",
        "story": "",
        "people": [{"id": "p-owen", "status": "confirmed"}],
        "places": [],
        "themes": [],
        "orgs": [{"id": "org-ministry", "status": "confirmed"}],
        "items": [{"id": "object-y", "status": "proposed"}],
        "date_mentions": [{"date": "1949-01-27", "precision": "exact", "note": "the submission"}],
        "transcription_status": "draft",
        "sensitive": False,
        "status": "catalogued",
        "assets": [{"kind": "page", "file": "page-1.jpg", "caption": ""}],
        "created": "2026-08-05",
        "chat": {"kind": "capture"},
    }
    item = Item.from_dict(raw)
    assert item.to_dict() == raw
    assert item.id == "letter-x" and item.type == "letter" and item.status == "catalogued"
    assert item.people_refs == [{"id": "p-owen", "status": "confirmed"}]
    assert item.assets == [{"kind": "page", "file": "page-1.jpg", "caption": ""}]


def test_item_requires_core_fields() -> None:
    base = {
        "id": "letter-x",
        "type": "letter",
        "title": "X",
        "date": "1949-02-04",
        "date_precision": "exact",
        "status": "catalogued",
        "assets": [],
        "people": [],
        "places": [],
        "themes": [],
    }
    Item.from_dict(base)  # valid
    for key in ("type", "title", "date", "date_precision", "status"):
        broken = dict(base, **{key: ""})
        with pytest.raises(ValueError, match="required"):
            Item.from_dict(broken)
    with pytest.raises(ValueError, match="type"):
        Item.from_dict(dict(base, type="novel"))
    with pytest.raises(ValueError, match="precision"):
        Item.from_dict(dict(base, date_precision="whenever"))
    with pytest.raises(ValueError, match="parseable"):
        Item.from_dict(dict(base, date="not-a-date"))


def test_item_tombstone_shape() -> None:
    Item.from_dict({"id": "letter-x", "type": "letter", "title": "X", "status": "deleted", "reason": "gone"})
    with pytest.raises(ValueError, match="status"):
        Item.from_dict({"id": "letter-x", "type": "letter", "title": "X", "status": "gone"})


def _event_item(**overrides: object) -> dict[str, object]:
    return {
        "id": "event-x",
        "type": "event",
        "title": "The family concert",
        "date": "1949-06-01",
        "date_precision": "exact",
        "status": "catalogued",
        "assets": [],
        "people": [{"id": "p-owen", "status": "confirmed"}],
        "places": [],
        "themes": [],
        **overrides,
    }


def test_event_item_requires_a_kind() -> None:
    # An event item is an attested happening (a birth, a marriage, a concert
    # mentioned in a letter) — the kind is its identity, required and closed.
    with pytest.raises(ValueError, match="needs a kind"):
        Item.from_dict(_event_item())
    with pytest.raises(ValueError, match="unknown event kind"):
        Item.from_dict(_event_item(kind="baptism"))


def test_event_item_round_trips_with_kind() -> None:
    item = Item.from_dict(_event_item(kind="birth"))
    assert item.to_dict()["kind"] == "birth"
    assert item.type == "event"


def test_item_sources_are_validated() -> None:
    # A web-page document names its sources with URLs and the access date —
    # the reader can click through and see how old the capture is.
    base = _event_item()
    base.update({"type": "document", "title": "A web page", "sources": []})
    ok = Item.from_dict(
        dict(
            base,
            sources=[
                {"url": "https://www.upperedenhistory.org.uk/BluePlaques/bp6.htm", "accessed": "2026-08-05"},
            ],
        )
    )
    assert ok.to_dict()["sources"][0]["url"].startswith("https://")
    with pytest.raises(ValueError, match="source"):
        Item.from_dict(dict(base, sources=[{"accessed": "2026-08-05"}]))  # no url
    with pytest.raises(ValueError, match="source"):
        Item.from_dict(dict(base, sources=[{"url": "not-a-url", "accessed": "2026-08-05"}]))
    with pytest.raises(ValueError, match="access"):
        Item.from_dict(dict(base, sources=[{"url": "https://example.com"}]))  # no access date


def test_clarification_flag_is_validated() -> None:
    # A clarification fragment ("yes BF means Owen") is a story-shaped record
    # that attests a person or item — it is not an event and must name its
    # target (2026-08-06).
    base = _event_item()
    base.update({"type": "story", "title": "BF", "items": [{"id": "letter-1977", "status": "confirmed"}]})
    item = Item.from_dict(dict(base, clarification=True))
    assert item.to_dict()["clarification"] is True
    with pytest.raises(ValueError, match="clarification"):
        Item.from_dict(dict(base, clarification="yes"))
    # a clarification without a target clarifies nothing
    with pytest.raises(ValueError, match="clarification"):
        Item.from_dict(dict(base, clarification=True, people=[], items=[]))
    # the flag belongs on stories, not artifacts
    letter = dict(base, type="letter", title="L")
    with pytest.raises(ValueError, match="story"):
        Item.from_dict(dict(letter, clarification=True))


def test_people_refs_may_carry_an_involvement_date() -> None:
    # An item that spans time (a family record written into over five
    # generations) involves different people at different dates — the ref
    # states when THAT person's involvement happened (2026-08-06). The
    # person's page and the person-filtered timeline place the item by it.
    base = _event_item()
    base.update({"type": "document", "title": "The family record", "date": "1868-03-20", "date_precision": "exact"})
    item = Item.from_dict(
        dict(
            base,
            people=[
                {"id": "p-isabella", "status": "confirmed", "date": {"date": "1868-03-20", "precision": "exact"}},
                {"id": "p-nora", "status": "confirmed", "date": {"date": "1947-05-11", "precision": "exact"}},
            ],
        )
    )
    assert item.to_dict()["people"][1]["date"] == {"date": "1947-05-11", "precision": "exact"}
    with pytest.raises(ValueError, match="date"):
        Item.from_dict(dict(base, people=[{"id": "p-x", "date": {"precision": "exact"}}]))


def test_evidence_flag_is_validated() -> None:  # A found record — a web capture, a directory page — is evidence ABOUT
    # the family, not a family happening: it renders on the pages it attests,
    # never on the timeline (2026-08-06, the recognition principle).
    base = _event_item()
    base.update({"type": "document", "title": "A web page", "places": [{"id": "pl-x", "status": "confirmed"}]})
    item = Item.from_dict(dict(base, evidence=True))
    assert item.to_dict()["evidence"] is True
    with pytest.raises(ValueError, match="evidence"):
        Item.from_dict(dict(base, evidence="yes"))
    # evidence must attest somewhere to render
    with pytest.raises(ValueError, match="evidence"):
        Item.from_dict(dict(base, evidence=True, people=[], places=[], items=[]))
    # a story is an account/fragment/reflection — never evidence
    with pytest.raises(ValueError, match="story"):
        Item.from_dict(dict(base, type="story", evidence=True, places=[{"id": "pl-x"}]))


def test_reflection_flag_is_validated() -> None:
    # A reflection is the narrator's perspective — it has no events' date
    # other than the telling day and renders on the people/places it
    # mentions (2026-08-06). Same shape as a clarification: flag on story.
    base = _event_item()
    base.update({"type": "story", "title": "Meeting her", "people": [{"id": "p-nora", "status": "confirmed"}]})
    item = Item.from_dict(dict(base, reflection=True))
    assert item.to_dict()["reflection"] is True
    with pytest.raises(ValueError, match="reflection"):
        Item.from_dict(dict(base, reflection="yes"))
    # a reflection must mention somewhere to render
    with pytest.raises(ValueError, match="reflection"):
        Item.from_dict(dict(base, reflection=True, people=[], places=[]))
    # a fragment and a reflection are different kinds of non-story
    with pytest.raises(ValueError, match="clarification"):
        Item.from_dict(dict(base, clarification=True, reflection=True))


def test_relationship_accepts_an_optional_date() -> None:
    # A spouse edge may carry the marriage date — the timeline derives the
    # marriage event from it (2026-08-05).
    rel = Relationship.from_dict(
        {
            "a": "p-a",
            "b": "p-b",
            "kind": "spouse",
            "label_a": "spouse",
            "label_b": "spouse",
            "date": {"date": "1888-06-20", "precision": "exact"},
        }
    )
    assert rel.to_dict()["date"] == {"date": "1888-06-20", "precision": "exact"}


def test_relationship_carries_the_owner_status() -> None:
    # The statuses are strict (2026-08-08, user): proposed = guessed by an
    # agent; estimated = guessed by a human, in the DB as a guess (GEDCOM's
    # EST); confirmed = actually confirmed. A missing status round-trips as
    # absent.
    rel = Relationship.from_dict(
        {
            "a": "p-cecil",
            "b": "p-judith",
            "kind": "parent",
            "label_a": "child",
            "label_b": "parent",
            "status": "estimated",
        }
    )
    assert rel.to_dict()["status"] == "estimated"
    plain = Relationship.from_dict({"a": "p-a", "b": "p-b", "kind": "spouse", "label_a": "spouse", "label_b": "spouse"})
    assert "status" not in plain.to_dict()
    with pytest.raises(ValueError):
        Relationship.from_dict(
            {"a": "p-a", "b": "p-b", "kind": "spouse", "label_a": "", "label_b": "", "status": "wat"}
        )


def test_relationship_date_precision_is_closed() -> None:
    with pytest.raises(ValueError, match="precision"):
        Relationship.from_dict(
            {
                "a": "p-a",
                "b": "p-b",
                "kind": "spouse",
                "label_a": "spouse",
                "label_b": "spouse",
                "date": {"date": "1888", "precision": "whenever"},
            }
        )
    with pytest.raises(ValueError, match="date"):
        Relationship.from_dict(
            {
                "a": "p-a",
                "b": "p-b",
                "kind": "spouse",
                "label_a": "spouse",
                "label_b": "spouse",
                "date": {"precision": "exact"},
            }
        )


def test_item_rejects_bad_refs_assets_and_transcription_status() -> None:
    base = {
        "id": "letter-x",
        "type": "letter",
        "title": "X",
        "date": "1949-02-04",
        "date_precision": "exact",
        "status": "catalogued",
        "assets": [],
        "people": [],
        "places": [],
        "themes": [],
    }
    with pytest.raises(ValueError, match="missing id"):
        Item.from_dict(dict(base, people=[{"status": "confirmed"}]))
    with pytest.raises(ValueError, match="bad status"):
        Item.from_dict(dict(base, orgs=[{"id": "org-x", "status": "maybe"}]))
    with pytest.raises(ValueError, match="kind and file"):
        Item.from_dict(dict(base, assets=[{"kind": "page"}]))
    with pytest.raises(ValueError, match="transcription_status"):
        Item.from_dict(dict(base, transcription_status="final"))


def test_event_tombstone_needs_no_kind() -> None:
    """A tombstone carries only id/type/title/status/reason — an event
    tombstone must not require a kind (2026-08-06 review)."""
    Item.from_dict({"id": "event-x", "type": "event", "title": "X", "status": "deleted", "reason": "gone"})
    with pytest.raises(ValueError, match="needs a kind"):
        Item.from_dict(dict(_event_item(), status="catalogued"))  # live events still need one


def test_date_validation_rejects_garbage_forms() -> None:
    """The write seam checks the whole date, not the year prefix — 2026-99-99
    and 2026-02-31 are not dates (2026-08-06 review)."""
    base = {
        "id": "letter-x",
        "type": "letter",
        "title": "A letter",
        "date_precision": "exact",
        "status": "catalogued",
        "assets": [],
        "people": [],
        "places": [],
        "themes": [],
    }
    for bad in ("2026-99-99", "2026-13-01", "2026-02-31", "circa 1900", "1900-01-01-extra"):
        with pytest.raises(ValueError, match="not parseable"):
            Item.from_dict({**base, "date": bad})
    with pytest.raises(ValueError, match="date2 is not parseable"):
        Item.from_dict({**base, "date": "1880", "date_precision": "between", "date2": "2026-99-99"})
    # the flexible forms the archive legitimately uses stay accepted
    for good in ("1901", "1901-01", "1969-08-10", "1868-03-20"):
        Item.from_dict({**base, "date": good})


def test_person_seam_rejects_impossible_dates() -> None:
    """The person seam validates the date itself, not just the precision —
    2026-99-99 must fail at write time, not crash the GEDCOM export later
    (review, 2026-08-07)."""
    with pytest.raises(ValueError, match="impossible date"):
        Person.from_dict({"id": "p-x", "name": "X", "dob": {"date": "2026-99-99", "precision": "exact"}})
    with pytest.raises(ValueError, match="impossible date"):
        Person.from_dict(
            {"id": "p-x", "name": "X", "dob": {"date": "1900", "precision": "between", "date2": "2026-02-31"}}
        )
    with pytest.raises(ValueError, match="impossible date"):
        Person.from_dict({"id": "p-x", "name": "X", "dod": {"date": "2026-13-01", "precision": "exact"}})
    # the flexible forms stay accepted
    Person.from_dict({"id": "p-x", "name": "X", "dob": {"date": "1871-01-07", "precision": "exact"}})


def test_person_email_is_validated_and_normalised() -> None:
    """The identity seam: a person's Google account email — lowercase,
    shape-checked at the write seam (2026-08-06)."""
    person = Person.from_dict({"id": "p-alex", "name": "Alex Hale", "email": "Alex.Hale@Example.COM "})
    assert person.email == "alex.hale@example.com"
    for bad in ("not-an-email", "missing@tld", "@nowhere"):
        with pytest.raises(ValueError, match="invalid email"):
            Person.from_dict({"id": "p-x", "name": "X", "email": bad})
    assert Person.from_dict({"id": "p-x", "name": "X"}).email is None
