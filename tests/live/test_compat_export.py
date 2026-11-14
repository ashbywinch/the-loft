"""B1 — the compatibility exporter writes the old-shape identity tables.

TECHSPEC/08 §19.4 / REWRITE-PLAN B1: after an identity write the old readers
must see no difference, so the exporter rewrites `people.json` (with its
relationships), `places.json`, `orgs.json` and `themes.json` in the archive's
own append-only, versioned form. `estimated` is a rendering: a confirmed
record with a recollection basis exports as the old `estimated` status.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loft.live.compat import CompatibilityExport
from loft.live.import_identity import sync_identities
from loft.live.store import LiveStore
from tools.archive import Archive
from tools.records import Org, OrgsTable, PeopleTable, Person, Place, PlacesTable, Relationship, ThemesTable
from tools.store import DiskStore, MemoryStore
from tools.theme import Theme


def _store(tmp_path: Path) -> LiveStore:
    return LiveStore.create(tmp_path / "loft.db", app_version="test")


def _export(store: LiveStore, archive: Archive) -> CompatibilityExport:
    return CompatibilityExport(store, archive)


def _seed(store: LiveStore) -> None:
    confirmed = Person.from_dict({"id": "p-alex", "name": "Alex Hale", "aliases": ["Alex"]})
    estimated = Person.from_dict(
        {
            "id": "p-nora",
            "name": "Nora Hale",
            "status": "confirmed",
            "basis": {
                "basis": "recollection",
                "confidence": "possible",
                "text": "Grandma used to say so.",
                "by": "Alex",
                "when": "2026-08-09",
            },
        }
    )
    proposed = Person.from_dict({"id": "p-judith", "name": "Pearl Whitlock", "status": "proposed"})
    rejected = Person.from_dict({"id": "p-nope", "name": "Not A Person", "status": "rejected"})
    with store.change(actor="import") as change:
        for person in (confirmed, estimated, proposed, rejected):
            change.people.save(person)
        change.places.save(Place.from_dict({"id": "pl-marlock", "name": "Marlock", "lat": 51.5}))
        change.places.save(Place.from_dict({"id": "pl-barges", "name": "the barges", "status": "proposed"}))
        change.orgs.save(Org.from_dict({"id": "org-ministry", "name": "Ministry of Supply"}))
        change.themes.save(Theme.from_dict({"id": "t-boats", "title": "The boats"}))
        change.relationships.save(
            Relationship.from_dict(
                {"a": "p-alex", "b": "p-nora", "kind": "spouse", "label_a": "spouse", "label_b": "spouse"}
            )
        )
        change.relationships.save(
            Relationship.from_dict(
                {
                    "a": "p-nora",
                    "b": "p-judith",
                    "kind": "parent",
                    "label_a": "mother",
                    "label_b": "daughter",
                    "status": "estimated",
                }
            )
        )
        change.relationships.save(
            Relationship.from_dict({"a": "p-alex", "b": "p-judith", "kind": "parent", "status": "proposed"})
        )


def test_the_exported_people_table_is_the_old_shape(tmp_path: Path) -> None:
    store = _store(tmp_path)
    archive = Archive(MemoryStore())
    try:
        _seed(store)
        written = _export(store, archive).write()
    finally:
        store.close()
    assert set(written) == {"people", "places", "orgs", "themes"}
    table = PeopleTable.from_dict(json.loads(archive.store.read("people.json")))
    by_id = {person.id: person for person in table.people}
    assert by_id["p-alex"].to_dict() == {
        "id": "p-alex",
        "name": "Alex Hale",
        "aliases": ["Alex"],
        "years": "—",
        "relation": "",
        "bio": "",
    }
    assert by_id["p-nora"].status == "estimated"
    assert by_id["p-nora"].basis == {"text": "Grandma used to say so.", "by": "Alex", "when": "2026-08-09"}
    assert by_id["p-judith"].status == "proposed"
    assert "p-nope" not in by_id  # a rejected proposal is excluded from browse
    edges = {(edge.a, edge.b, edge.kind): edge for edge in table.relationships}
    assert edges[("p-alex", "p-nora", "spouse")].status is None  # an asserted edge stays asserted
    assert edges[("p-nora", "p-judith", "parent")].status == "estimated"
    assert edges[("p-alex", "p-judith", "parent")].status == "proposed"


def test_the_exported_places_orgs_and_themes_are_the_old_shape(tmp_path: Path) -> None:
    store = _store(tmp_path)
    archive = Archive(MemoryStore())
    try:
        _seed(store)
        _export(store, archive).write()
    finally:
        store.close()
    places = PlacesTable.from_dict(json.loads(archive.store.read("places.json")))
    assert {(place.id, place.status) for place in places.places} == {
        ("pl-marlock", "confirmed"),
        ("pl-barges", "proposed"),
    }
    london = places.record("pl-marlock")
    assert london is not None and "status" not in london.to_dict()
    orgs = OrgsTable.from_dict(json.loads(archive.store.read("orgs.json")))
    assert orgs.orgs[0].to_dict() == {"id": "org-ministry", "name": "Ministry of Supply"}
    themes = ThemesTable.from_dict(json.loads(archive.store.read("themes.json")))
    assert themes.themes[0].to_dict() == {"id": "t-boats", "title": "The boats"}


def test_an_unchanged_store_writes_no_new_version(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store_files = MemoryStore()
    archive = Archive(store_files)
    try:
        _seed(store)
        exporter = _export(store, archive)
        assert exporter.write() == ("people", "places", "orgs", "themes")
        # a second export with no change is a no-op: no byte-identical version
        assert exporter.write() == ()
        assert not store_files.exists("people-2.json")
    finally:
        store.close()


def test_a_change_appends_a_version_that_supersedes_the_last(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store_files = MemoryStore()
    archive = Archive(store_files)
    try:
        _seed(store)
        exporter = _export(store, archive)
        exporter.write()
        store.identities.confirm_person("p-judith", actor="p-editor")
        assert exporter.write() == ("people",)
        latest = json.loads(store_files.read("people-2.json"))
        assert latest["supersedes"] == "people.json"
        confirmed = PeopleTable.from_dict(latest).record("p-judith")
        assert confirmed is not None and confirmed.status == "confirmed"
        first = PeopleTable.from_dict(json.loads(store_files.read("people.json")))
        proposed = first.record("p-judith")
        assert proposed is not None and proposed.status == "proposed"  # the first version is untouched
    finally:
        store.close()


def test_the_proposed_queue_files_are_written_for_proposed_records(tmp_path: Path) -> None:
    """B3b: a proposal is a row in the identity table, but the old readers
    still list `proposed/people|places/` — the exporter writes one file per
    proposed row, in the old record shape."""
    store = _store(tmp_path)
    store_files = MemoryStore()
    archive = Archive(store_files)
    try:
        _seed(store)
        _export(store, archive).write()
    finally:
        store.close()
    assert store_files.list("proposed") == ["proposed/people/p-judith.json", "proposed/places/pl-barges.json"]
    proposed = json.loads(store_files.read("proposed/people/p-judith.json"))
    assert proposed["status"] == "proposed"
    assert proposed["name"] == "Pearl Whitlock"


def test_the_queue_keeps_a_promoted_file_and_removes_a_rejected_one(tmp_path: Path) -> None:
    """The old queue is append-only: a promoted record keeps the file it was
    queued with. A rejected row, and a row the review deleted, lose theirs —
    the one delete the old store performed."""
    store = _store(tmp_path)
    store_files = MemoryStore()
    archive = Archive(store_files)
    try:
        _seed(store)
        for record_id in ("p-alex", "p-nope", "p-gone"):
            store_files.write_new(
                f"proposed/people/{record_id}.json",
                json.dumps({"id": record_id, "name": record_id, "status": "proposed"}),
            )
        _export(store, archive).write()
    finally:
        store.close()
    assert store_files.exists("proposed/people/p-alex.json")  # confirmed: the file stays
    assert store_files.exists("proposed/people/p-judith.json")  # proposed: written
    assert not store_files.exists("proposed/people/p-nope.json")  # rejected: removed
    assert not store_files.exists("proposed/people/p-gone.json")  # the row is gone: removed


def test_the_queue_export_leaves_a_file_that_is_not_a_record_alone(tmp_path: Path) -> None:
    """The sweep removes queue records only — a stray note a person left in
    the directory is theirs, not the exporter's."""
    store = _store(tmp_path)
    store_files = MemoryStore()
    archive = Archive(store_files)
    try:
        _seed(store)
        store_files.write_new("proposed/people/README.txt", "notes")
        _export(store, archive).write()
    finally:
        store.close()
    assert store_files.read("proposed/people/README.txt") == "notes"


def test_the_queue_export_is_idempotent_and_reports_what_it_touched(tmp_path: Path) -> None:
    """A second pass writes nothing — the queue is append-only and the sweep
    finds nothing to remove."""
    store = _store(tmp_path)
    store_files = MemoryStore()
    archive = Archive(store_files)
    try:
        _seed(store)
        queue = _export(store, archive).queue
        assert queue.write() == ("proposed/people/p-judith.json", "proposed/places/pl-barges.json")
        assert queue.write() == ()
    finally:
        store.close()


def test_an_empty_store_writes_empty_tables(tmp_path: Path) -> None:
    store = _store(tmp_path)
    archive = Archive(MemoryStore())
    try:
        assert _export(store, archive).write() == ("people", "places", "orgs", "themes")
    finally:
        store.close()
    assert json.loads(archive.store.read("people.json")) == {"people": [], "relationships": []}
    assert json.loads(archive.store.read("places.json")) == {"places": []}


def test_the_exporter_reports_the_tables_it_could_not_build(tmp_path: Path) -> None:
    """A record the old reader cannot parse must fail loudly, never write a
    half table — the compatibility export is a contract, not a best effort."""
    store = _store(tmp_path)
    with store.change(actor="import") as change:
        change.people.save(Person.from_dict({"id": "p-alex", "name": "Alex Hale"}))
        change.relationships.save(Relationship.from_dict({"a": "p-alex", "b": "p-ghost", "kind": "sibling"}))
    archive = Archive(MemoryStore())
    try:
        with pytest.raises(ValueError, match="unknown person"):
            _export(store, archive).write()
    finally:
        store.close()
    assert not archive.store.exists("people.json")


def test_sync_identities_catches_up_and_never_regresses(tmp_path: Path) -> None:
    """The flip starts with an import of the surface's records the old path
    wrote since — and a record the DB already holds is never overwritten."""
    old = tmp_path / "archive"
    old.mkdir()
    archive = Archive(DiskStore(old))
    proposed = Person.from_dict({"id": "p-alex", "name": "Alex Hale", "status": "proposed"})
    confirmed = Person.from_dict({"id": "p-nora", "name": "Nora Hale"})
    archive.save_identity("people", PeopleTable(people=(proposed, confirmed), relationships=()))
    for name in ("places", "orgs", "themes"):
        archive.save_identity(
            name, {"places": PlacesTable(places=()), "orgs": OrgsTable(orgs=()), "themes": ThemesTable(themes=())}[name]
        )
    store = _store(tmp_path)
    try:
        first = sync_identities(store, old)
        assert first.counts["people"] == 2
        assert store.people.require("p-alex").status == "proposed"
        # the family confirms Alex through the service …
        store.identities.confirm_person("p-alex", actor="p-editor")
        # … then the old path writes a new proposal into the file table
        newcomer = Person.from_dict({"id": "p-robin", "name": "Robin Hale", "status": "proposed"})
        archive.save_identity(
            "people", PeopleTable(people=(proposed.as_confirmed(), confirmed, newcomer), relationships=())
        )
        second = sync_identities(store, old)
        assert second.operations == ("person p-robin",)
        assert store.people.require("p-alex").status == "confirmed"  # the newer DB record survives
        assert store.people.require("p-robin").status == "proposed"
        assert sync_identities(store, old).operations == ()
        assert store.verify_chain() == ()
    finally:
        store.close()
