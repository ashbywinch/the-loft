"""Tests for the archive library: version resolution, supersession,
tombstones, and the proposed-record queue — all through the append-only store
(MemoryStore fails any in-place edit)."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import override

import pytest

from loft.live.compat import CompatibilityExport
from loft.live.import_identity import sync_from_archive
from loft.live.memory import MemoryLiveStore
from pipeline.identification import Identification
from tools.archive import Archive, ArchiveError
from tools.gone_place import GonePlace
from tools.records import ImportsTable, Item, Person, Place, Session, validate_identity
from tools.store import ImmutableStoreError, MemoryStore, StoreError


def make_archive() -> tuple[Archive, MemoryStore]:
    store = MemoryStore()
    return Archive(store), store


def _item(**overrides: object) -> dict[str, object]:
    """A valid minimal sidecar (the Item record's required shape)
    with per-test overrides."""
    defaults: dict[str, object] = {
        "id": "story-x",
        "type": "story",
        "title": "T",
        "date": "2026-08-01",
        "date_precision": "exact",
        "status": "draft",
        "assets": [],
        "people": [],
        "places": [],
        "themes": [],
    }
    defaults.update(overrides)
    return defaults


def _record(**overrides: object) -> Item:
    """The same sidecar as its Item record — what the archive's API takes
    and returns."""
    return Item.from_dict(_item(**overrides))


def test_content_paths_reject_escaping_ids_and_filenames() -> None:
    """save_file/read_content/read_file_bytes build store paths from caller
    input — an id or filename containing '..' or '/' must be rejected, not
    resolved outside the archive root."""
    archive, store = make_archive()
    with pytest.raises(ArchiveError, match="invalid record id"):
        archive.save_file("../escape", "a.txt", "x")
    with pytest.raises(ArchiveError, match="invalid content filename"):
        archive.save_file("story-x", "../../notes.txt", "x")
    with pytest.raises(ArchiveError, match="invalid content filename"):
        archive.save_file("story-x", "a/b.txt", "x")
    with pytest.raises(ArchiveError, match="invalid content filename"):
        _ = archive.read_content("story-x", "a/../../notes.txt")
    with pytest.raises(ArchiveError, match="invalid record id"):
        _ = archive.read_file_bytes("../escape", "x.jpg")
    assert list(store.files) == []  # nothing was written or read outside


def test_sidecar_read_paths_reject_escaping_ids() -> None:
    """get_item composes 'assets/<id>/item.json' from the caller's id — the
    last read seam still composing a store path from an unvalidated id; a
    crafted id must be rejected, not resolved outside the archive root."""
    archive, _ = make_archive()
    with pytest.raises(ArchiveError, match="invalid record id"):
        _ = archive.get_item("a/../../../tmp")
    with pytest.raises(ArchiveError, match="invalid record id"):
        _ = archive._sidecar_versions("../escape")


def test_corrupt_proposed_record_fails_loudly() -> None:
    """A corrupt proposed file (partial write, hand-edit) must raise at read
    time — silently skipping it hides the corruption and produces a
    confusing dangling-ref failure later."""
    archive, store = make_archive()
    store.write_new("proposed/people/p-bad.json", '{"id": "p-bad"}')  # missing required name
    with pytest.raises(ArchiveError, match="proposed/people/p-bad.json"):
        _ = archive.proposed_people()
    store.write_new("proposed/places/pl-bad.json", "{not json")
    with pytest.raises(ArchiveError, match="proposed/places/pl-bad.json"):
        _ = archive.proposed_places()


def test_reject_also_sees_extraction_matches() -> None:
    """A catalogued story whose chat extraction (kept by the reviewer) matches
    the proposed record references it too — rejecting must fail in the same
    session, not later at publish with a dangling extraction match."""
    archive, store = make_archive()
    archive.propose_person(Person.from_dict({"id": "p-grandma", "name": "Grandma"}))
    archive.save_item(
        Item.from_dict(
            {
                "id": "story-x",
                "type": "story",
                "title": "X",
                "date": "2026-08-03",
                "date_precision": "exact",
                "status": "catalogued",
                "chat": {
                    "extractions": [
                        {"kind": "person", "name": "Grandma", "match": "p-grandma", "bucket": "proposed", "on": True},
                    ]
                },
                "assets": [],
            }
        ),
    )
    with pytest.raises(ArchiveError, match="still reference"):
        archive.reject_proposed_person("p-grandma")
    # an unticked extraction is excluded content — it does not block the reject
    archive2, store2 = make_archive()
    archive2.propose_person(Person.from_dict({"id": "p-grandma", "name": "Grandma"}))
    archive2.save_item(
        Item.from_dict(
            {
                "id": "story-x",
                "type": "story",
                "title": "X",
                "date": "2026-08-03",
                "date_precision": "exact",
                "status": "catalogued",
                "chat": {
                    "extractions": [
                        {"kind": "person", "name": "Grandma", "match": "p-grandma", "bucket": "proposed", "on": False},
                    ]
                },
                "assets": [],
            }
        ),
    )
    archive2.reject_proposed_person("p-grandma")  # no raise


def test_reject_refuses_when_a_catalogued_story_references_the_record() -> None:
    """Rejecting a proposed record that catalogued stories still reference
    would leave dangling refs at publish — refuse loudly at the review
    action instead: relink the stories first, or keep the record."""
    archive, store = make_archive()
    archive.propose_person(Person.from_dict({"id": "p-grandma", "name": "Grandma"}))
    archive.propose_place(Place.from_dict({"id": "pl-yard", "name": "The yard"}))
    archive.save_item(
        Item.from_dict(
            {
                "id": "story-x",
                "type": "story",
                "title": "X",
                "date": "2026-08-03",
                "date_precision": "exact",
                "status": "catalogued",
                "people": [{"id": "p-grandma", "status": "proposed"}],
                "places": [{"id": "pl-yard", "status": "proposed"}],
                "assets": [],
            }
        ),
    )
    with pytest.raises(ArchiveError, match="still reference"):
        archive.reject_proposed_person("p-grandma")
    with pytest.raises(ArchiveError, match="still reference"):
        archive.reject_proposed_place("pl-yard")
    assert store.exists("proposed/people/p-grandma.json")
    assert store.exists("proposed/places/pl-yard.json")


def test_chain_with_missing_base_version_fails_loudly() -> None:
    """A partial sync that loses the base version (item.json) but keeps
    item-2.json must fail loudly — an empty chain would let the item vanish
    from the projection or a fresh v1 be shadowed by the stale higher
    version."""
    archive, store = make_archive()
    store.write_new("assets/story-x/item-2.json", '{"id": "story-x", "title": "Two"}')
    with pytest.raises(ArchiveError, match="gap"):
        _ = archive.get_item("story-x")
    store2, store_mem = make_archive()
    store_mem.write_new("people-2.json", '{"people": [{"id": "p-x", "name": "X"}]}')
    with pytest.raises(ArchiveError, match="gap"):
        _ = store2.get_identity("people")


def test_sidecar_version_gap_fails_loudly() -> None:
    """A lost middle version (a partial Drive sync) must fail loudly, never
    silently serve the older contiguous run."""
    archive, store = make_archive()
    _ = archive.save_item(_record(title="One"))
    _ = archive.save_item(_record(title="Two"))
    _ = archive.save_item(_record(title="Three"))
    store.delete("assets/story-x/item-2.json")  # the middle version is lost
    with pytest.raises(ArchiveError, match="gap"):
        _ = archive.get_item("story-x")


def test_identity_version_gap_fails_loudly() -> None:
    archive, store = make_archive()
    archive.save_identity("people", validate_identity("people", {"people": [{"id": "p-a", "name": "A"}]}))
    archive.save_identity("people", validate_identity("people", {"people": [{"id": "p-b", "name": "B"}]}))
    archive.save_identity("people", validate_identity("people", {"people": [{"id": "p-c", "name": "C"}]}))
    store.delete("people-2.json")  # the middle version is lost
    with pytest.raises(ArchiveError, match="gap"):
        _ = archive.get_identity("people")


def test_save_and_get_resolve_the_sidecar() -> None:
    archive, _ = make_archive()
    _ = archive.save_item(_record(title="One"))
    assert archive.get_item("story-x") == _record(title="One")
    assert archive.get_item("missing") is None


def test_supersession_writes_a_new_version_and_never_edits() -> None:
    archive, store = make_archive()
    _ = archive.save_item(_record(title="One"))
    version = archive.save_item(_record(title="Two"))
    assert version == 2
    # the original is untouched (append-only), the superseding file carries the chain
    assert json.loads(store.read(f"assets/story-x/{Archive.SIDECAR}"))["title"] == "One"
    assert json.loads(store.read("assets/story-x/item-2.json"))["supersedes"] == f"assets/story-x/{Archive.SIDECAR}"
    item = archive.get_item("story-x")
    assert item is not None and item.title == "Two"  # the highest version wins


def test_delete_marks_a_tombstone_instead_of_removing() -> None:
    archive, store = make_archive()
    _ = archive.save_item(_record(title="One"))
    archive.delete_item("story-x", "test fabrication")
    # the files are all still there — nothing was deleted
    assert store.exists(f"assets/story-x/{Archive.SIDECAR}")
    assert store.exists("assets/story-x/item-2.json")
    tombstone = json.loads(store.read("assets/story-x/item-2.json"))
    assert tombstone["status"] == "deleted"
    assert tombstone["reason"] == "test fabrication"
    assert archive.get_item("story-x") is None  # resolved as gone
    assert "story-x" in archive.item_ids()  # the folder still exists


def test_item_ids_lists_every_folder() -> None:
    archive, _ = make_archive()
    _ = archive.save_item(_record(id="b-item"))
    _ = archive.save_item(_record(id="a-item"))
    assert archive.item_ids() == ["a-item", "b-item"]


def test_item_versions_and_one_sidecar_version_read_the_chain() -> None:
    """The migration reads the whole chain, not only the wins — the two
    public reads A4 needs (the contiguous-version rule stays the facade's)."""
    archive, _ = make_archive()
    _ = archive.save_item(_record(title="One"))
    _ = archive.save_item(_record(title="Two"))
    assert archive.item_versions("story-x") == [1, 2]
    assert archive.get_item_version("story-x", 1).title == "One"
    assert archive.get_item_version("story-x", 2).title == "Two"


def test_store_delete_removes_a_file_and_fails_on_missing() -> None:
    """The proposed queue's reject path: a dropped proposal is gone. This is
    the ONE delete on the store — primary content (items, identity tables,
    content files) never uses it: those supersede or tombstone.
    """
    from tools.store import MemoryStore

    store = MemoryStore()
    store.write_new("proposed/places/pl-x.json", "{}")
    assert store.exists("proposed/places/pl-x.json")
    store.delete("proposed/places/pl-x.json")
    assert not store.exists("proposed/places/pl-x.json")
    with pytest.raises(StoreError):
        store.delete("proposed/places/pl-x.json")  # deleting a missing file fails loudly


def test_proposed_records_queue_and_ids() -> None:
    archive, store = make_archive()
    archive.propose_person(Person.from_dict({"id": "p-harper", "name": "Harper"}))
    archive.propose_place(Place.from_dict({"id": "pl-mirosa", "name": "SB Mirosa"}))
    assert archive.proposed_ids() == {"p-harper", "pl-mirosa"}
    assert json.loads(store.read("proposed/people/p-harper.json"))["name"] == "Harper"


def test_duplicate_save_via_archive_still_refuses_in_place_edits() -> None:
    """Even the ORM cannot edit: saving again is a new version, and a direct
    write to an existing file still fails."""
    archive, store = make_archive()
    _ = archive.save_item(_record(id="x", title="One"))
    with pytest.raises(ImmutableStoreError):
        store.write_new(f"assets/x/{Archive.SIDECAR}", "{}")  # the low-level store still guards
    _ = archive.save_item(_record(id="x", title="One again"))
    item = archive.get_item("x")
    assert item is not None and item.title == "One again"


# -- identity tables (people/places/themes — versioned like sidecars) ------


def test_identity_tables_version_like_sidecars() -> None:
    archive, store = make_archive()
    _ = archive.save_identity("people", validate_identity("people", {"people": [{"id": "p-harper", "name": "Harper"}]}))
    version = archive.save_identity(
        "people", validate_identity("people", {"people": [{"id": "p-harper", "name": "Harper"}]})
    )
    assert version == 2
    # the first file is untouched, the superseding file carries the chain
    assert json.loads(store.read("people.json"))["people"][0]["name"] == "Harper"
    assert json.loads(store.read("people-2.json"))["supersedes"] == "people.json"
    table = archive.get_identity("people")
    assert table is not None and table.people[0].name == "Harper"  # highest wins


def test_identity_tables_are_append_only() -> None:
    archive, store = make_archive()
    _ = archive.save_identity("places", validate_identity("places", {"places": []}))
    with pytest.raises(ImmutableStoreError):
        store.write_new("places.json", "{}")  # the low-level store still guards


def test_identity_tables_missing_returns_none() -> None:
    archive, _ = make_archive()
    assert archive.get_identity("themes") is None


def test_re_save_with_content_updates_the_content_entry() -> None:
    """An edit that loads the current sidecar (whose content entry carries the
    versioned name) and re-saves must update that entry, not append a second
    one — otherwise publish would read the stale first entry."""
    archive, store = make_archive()
    _ = archive.save_item(
        _record(title="One"),
        content={"story": "Version one."},
    )
    current = archive.get_item("story-x")
    assert current is not None
    _ = archive.save_item(current, content={"story": "Version two."})
    v2 = json.loads(store.read("assets/story-x/item-2.json"))
    story_entries = [a for a in v2["assets"] if a["kind"] == "story"]
    assert story_entries == [{"kind": "story", "file": "story-2.txt", "caption": "The story, verbatim"}]
    assert archive.read_content("story-x", "story-2.txt") == "Version two."
    assert store.read("assets/story-x/story.txt") == "Version one."  # append-only


def test_save_recovers_after_a_crash_mid_save() -> None:
    """The sidecar is written before the content files: a crash mid-save
    leaves the version advanced (sidecar present, content missing), so the
    next save supersedes and writes a fresh content file. Content-first
    would leave an orphan content file with no sidecar — the next save
    would collide with the same filename and be permanently blocked."""

    class CrashOnSecondWrite(MemoryStore):
        """The first write lands, the second dies — the mid-save crash."""

        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        @override
        def write_new(self, path: str, content: str | bytes) -> None:
            self.calls += 1
            if self.calls == 2:
                raise ImmutableStoreError("simulated crash")
            super().write_new(path, content)

    store = CrashOnSecondWrite()
    archive = Archive(store)
    with pytest.raises(ImmutableStoreError):
        archive.save_item(
            _record(title="One"),
            content={"story": "Version two."},
        )
    # the sidecar landed before the crash — the version advanced and a retry
    # uses a fresh content filename instead of colliding with an orphan
    assert store.exists("assets/story-x/item.json")
    version = archive.save_item(
        _record(title="One"),
        content={"story": "Version two."},
    )
    assert version == 2
    assert store.read("assets/story-x/story-2.txt") == "Version two."
    v2 = json.loads(store.read("assets/story-x/item-2.json"))
    assert {"kind": "story", "file": "story-2.txt", "caption": "The story, verbatim"} in v2["assets"]


def test_unknown_identity_table_fails_fast() -> None:
    archive, _ = make_archive()
    with pytest.raises(ArchiveError):
        _ = archive.get_identity("bogus")


# -- primary content files (story.txt, transcription.txt) ------------------


def test_save_item_with_content_writes_content_file_and_references_it() -> None:
    archive, store = make_archive()
    _ = archive.save_item(
        _record(title="One"),
        content={"story": "We took the dinghy out."},
    )
    # the story is a content file the sidecar references — not a JSON field
    assert store.read("assets/story-x/story.txt") == "We took the dinghy out."
    sidecar = json.loads(store.read(f"assets/story-x/{Archive.SIDECAR}"))
    assert "story" not in sidecar
    assert {"kind": "story", "file": "story.txt", "caption": "The story, verbatim"} in sidecar["assets"]
    assert archive.read_content("story-x", "story.txt") == "We took the dinghy out."


def test_superseded_content_is_a_new_file_never_an_edit() -> None:
    archive, store = make_archive()
    _ = archive.save_item(
        _record(title="One"),
        content={"story": "Version one."},
    )
    _ = archive.save_item(
        _record(title="Two"),
        content={"story": "Version two."},
    )
    # both versions of the story survive (append-only), each referenced by its sidecar
    assert store.read("assets/story-x/story.txt") == "Version one."
    assert store.read("assets/story-x/story-2.txt") == "Version two."
    v2 = json.loads(store.read("assets/story-x/item-2.json"))
    assert v2["supersedes"] == f"assets/story-x/{Archive.SIDECAR}"
    assert {"kind": "story", "file": "story-2.txt", "caption": "The story, verbatim"} in v2["assets"]
    assert archive.read_content("story-x", "story.txt") == "Version one."
    assert archive.read_content("story-x", "story-2.txt") == "Version two."


def test_save_item_without_content_writes_no_content_file() -> None:
    archive, store = make_archive()
    _ = archive.save_item(_record(id="letter-x", type="letter", title="One", status="catalogued"))
    assert not store.exists("assets/letter-x/story.txt")
    assert not store.exists("assets/letter-x/transcription.txt")


def test_empty_content_is_skipped() -> None:
    archive, store = make_archive()
    _ = archive.save_item(
        _record(title="One"),
        content={"story": ""},
    )
    assert not store.exists("assets/story-x/story.txt")


def test_story_with_transcription_keeps_both_content_files() -> None:
    """A story item may carry both its account and a transcription (a
    recorded testimony) — split_content must never drop either."""
    archive, store = make_archive()
    _ = archive.save_item(
        _record(title="One"),
        content={"story": "The account.", "transcription": "The typed record."},
    )
    assert store.read("assets/story-x/story.txt") == "The account."
    assert store.read("assets/story-x/transcription.txt") == "The typed record."
    sidecar = json.loads(store.read(f"assets/story-x/{Archive.SIDECAR}"))
    assert {"kind": "story", "file": "story.txt", "caption": "The story, verbatim"} in sidecar["assets"]
    assert {"kind": "transcription", "file": "transcription.txt", "caption": "The transcription"} in sidecar["assets"]
    assert "story" not in sidecar and "transcription" not in sidecar


def test_re_save_clears_stale_content_entry() -> None:
    """A re-save that omits a content kind (cleared transcription, empty
    story) must strip the old asset entry — otherwise resolved_items keeps
    publishing the previous text forever. The real scenario: the caller
    loads the current sidecar (which carries the old entry) and re-saves
    without that content kind."""
    archive, store = make_archive()
    # v1: save with transcription
    _ = archive.save_item(
        _record(id="letter-x", type="letter", title="X", status="catalogued"),
        content={"transcription": "Version one."},
    )
    # v2: load the current item (carries the old asset entry), re-save
    # without transcription (empty content dict should trigger cleanup)
    current = archive.get_item("letter-x")
    assert current is not None
    _ = archive.save_item(current, content={})
    v2 = json.loads(store.read("assets/letter-x/item-2.json"))
    trans_entries = [a for a in v2["assets"] if a.get("kind") == "transcription"]
    assert trans_entries == [], f"stale transcription entry survived: {trans_entries}"
    # the content file still exists (append-only) — the sidecar just stops referencing it
    assert store.read("assets/letter-x/transcription.txt") == "Version one."


# -- the propose/confirm seam: one Person type, promote supersedes the table --


def test_proposed_records_are_person_records_with_status() -> None:
    """A proposed person is the SAME type as a confirmed one — the
    difference is the status field, serialised in the proposed file
    (proposed and confirmed are states, not types)."""
    archive, store = make_archive()
    archive.propose_person(Person.from_dict({"id": "p-nova", "name": "Nova", "relation": "added from a story"}))
    stored = json.loads(store.read("proposed/people/p-nova.json"))
    assert stored["name"] == "Nova"
    assert stored["status"] == "proposed"
    assert archive.proposed_people()[0].id == "p-nova"


def test_promote_person_supersedes_the_identity_table() -> None:
    archive, store = make_archive()
    archive.save_identity(
        "people", validate_identity("people", {"people": [{"id": "p-a", "name": "A"}], "relationships": []})
    )
    archive.propose_person(Person.from_dict({"id": "p-nova", "name": "Nova", "relation": "added from a story"}))
    version = archive.promote_person("p-nova")
    assert version == 2  # people-2.json supersedes people.json
    table = archive.get_identity("people")
    assert table is not None and [p.id for p in table.people] == ["p-a", "p-nova"]
    assert "status" not in table.people[1].to_dict()  # confirmed in the table — no status field
    # the proposed file stays (append-only); derive skips ids already in the table
    assert store.exists("proposed/people/p-nova.json")


def test_promote_person_missing_raises() -> None:
    archive, _ = make_archive()
    archive.save_identity("people", validate_identity("people", {"people": [], "relationships": []}))
    with pytest.raises(ArchiveError, match="no proposed"):
        archive.promote_person("p-ghost")


def test_promote_person_already_confirmed_raises() -> None:
    archive, _ = make_archive()
    archive.save_identity(
        "people", validate_identity("people", {"people": [{"id": "p-a", "name": "A"}], "relationships": []})
    )
    archive.propose_person(Person.from_dict({"id": "p-a", "name": "A"}))
    with pytest.raises(ArchiveError, match="already"):
        archive.promote_person("p-a")


def test_promote_place_supersedes_places_table() -> None:
    archive, _ = make_archive()
    archive.save_identity("places", validate_identity("places", {"places": [{"id": "pl-a", "name": "A"}]}))
    archive.propose_place(Place.from_dict({"id": "pl-mirosa", "name": "SB Mirosa"}))
    version = archive.promote_place("pl-mirosa")
    assert version == 2
    table = archive.get_identity("places")
    assert table is not None and [p.id for p in table.places] == ["pl-a", "pl-mirosa"]


def test_reject_proposed_place_drops_the_record() -> None:
    """A proposal the review rejects is gone from the queue — a passing
    story mention with no attestation is fiction, not a place entity."""
    archive, store = make_archive()
    archive.propose_place(Place.from_dict({"id": "pl-barges", "name": "the moored barges"}))
    assert archive.proposed_ids() == {"pl-barges"}
    archive.reject_proposed_place("pl-barges")
    assert archive.proposed_ids() == set()
    assert not store.exists("proposed/places/pl-barges.json")
    with pytest.raises(ArchiveError, match="no proposed"):
        archive.reject_proposed_place("pl-barges")  # rejecting twice fails loudly


def test_reject_proposed_person_drops_the_record() -> None:
    archive, _ = make_archive()
    archive.propose_person(Person.from_dict({"id": "p-nova", "name": "Nova"}))
    archive.reject_proposed_person("p-nova")
    assert archive.proposed_ids() == set()
    assert archive.proposed_people() == []


def test_proposed_operations_reject_path_traversal_ids() -> None:
    """A crafted id (../people) must never reach a store path — the
    archive rules say identity tables are never deleted."""
    archive, store = make_archive()
    archive.save_identity("people", validate_identity("people", {"people": [], "relationships": []}))
    for bad in ("../people", "../../people", "p/evil", "p..evil"):
        with pytest.raises(ArchiveError, match="id"):
            archive.reject_proposed_person(bad)
        with pytest.raises(ArchiveError, match="id"):
            archive.reject_proposed_place(bad)
        with pytest.raises(ArchiveError, match="id"):
            archive.promote_person(bad)
        with pytest.raises(ArchiveError, match="id"):
            archive.promote_place(bad)
        with pytest.raises(ArchiveError, match="id"):
            archive.propose_person(Person(id=bad, name="Evil"))
        with pytest.raises(ArchiveError, match="id"):
            archive.propose_place(Place(id=bad, name="Evil"))
        with pytest.raises(ArchiveError, match="id"):
            archive.save_item(Item({"id": bad, "type": "story", "title": "X", "status": "draft", "assets": []}))
        with pytest.raises(ArchiveError, match="id"):
            archive.delete_item(bad, "test")
    # the identity tables are untouched
    assert store.exists("people.json")
    assert not store.exists("people.json.bak")


def test_review_attempts_are_walk_separated() -> None:
    """The sessions' storage: a fresh attempt starts only when
    the last is empty or finished — a mid-walk re-render continues the same
    walk, so the diagnosis never mixes attempts."""
    from tools.archive import Archive
    from tools.store import MemoryStore

    archive = Archive(MemoryStore())
    from tools.records import ReviewDecision

    session = Session.from_dict(
        {
            "id": "import-documents",
            "kind": "import-review",
            "title": "The document import",
            "status": "pending",
            "current": None,
            "attempts": [],
        }
    )
    archive.save_identity("imports", ImportsTable(imports=(session,)))
    archive.save_identity(
        "people", validate_identity("people", {"people": [{"id": "p-a", "name": "A", "status": "proposed"}]})
    )

    assert archive.start_review_attempt("import-documents") == 0  # the first walk
    assert archive.start_review_attempt("import-documents") == 0  # a mid-walk re-render: same attempt
    archive.record_review_message("import-documents", "user", "hello", "2026-08-09")
    archive.record_review_message("import-documents", "user", "again", "2026-08-09")
    session = archive.get_review_session("import-documents")
    assert session is not None
    assert len(session.attempts) == 1
    assert len(session.attempts[0].messages) == 2  # the same walk accumulates

    # a finished walk (its last decision completed the session) starts fresh
    archive.record_review_decision(
        "import-documents",
        ReviewDecision(person_id="p-a", decision="pending", when="2026-08-09", last=True),
    )
    assert archive.start_review_attempt("import-documents") == 1  # the new walk
    session = archive.get_review_session("import-documents")
    assert session is not None
    assert len(session.attempts) == 2
    assert session.attempts[1].messages == ()  # the fresh walk's conversation
    assert session.current is None  # the last decision cleared the resume point


def test_ensure_import_session_is_atomic_and_idempotent() -> None:
    """_ensure_import_session must read, check, and write atomically
    under the archive's lock (through the _mutate_identity seam) —
    outside the lock, two concurrent cold starts compute the same next
    version and the append-only store refuses the second. A repeat call
    writes nothing."""
    archive, _ = make_archive()
    assert archive.get_review_session("import-documents") is None
    archive._ensure_import_session()
    session = archive.get_review_session("import-documents")
    assert session is not None
    assert session.status == "pending"
    assert len(archive._identity_versions("imports")) == 1
    # a second call (a second capture, a concurrent cold start) writes
    # NOTHING — no new version, no duplicate session
    archive._ensure_import_session()
    assert len(archive._identity_versions("imports")) == 1
    session = archive.get_review_session("import-documents")
    assert session is not None
    assert len(session.attempts) == 0


def test_identity_saves_serialize_concurrent_writers() -> None:
    """The review flow records the user's line and the assistant's line
    while the app's fire-and-forget message records land — the write
    seam serializes the read-compute-write with the process-wide lock:
    every writer reads AFTER the previous writer's write, so no collision
    and no lost update. A retry-on-collision was rejected because
    re-writing a stale snapshot would silently drop the concurrent
    writer's change."""
    import threading

    store = MemoryStore()
    archive = Archive(store)
    archive.save_identity("imports", validate_identity("imports", {"imports": []}))
    errors: list[Exception] = []

    def writer(prefix: str) -> None:
        try:
            for i in range(15):
                # the ATOMIC seam — the read must sit inside the lock; the
                # get_identity-then-save_identity pattern this test used
                # could lose a concurrent writer's update
                def apply(table: ImportsTable | None, _i: int = i) -> ImportsTable:
                    current = table or ImportsTable(imports=())
                    session = Session(id=f"{prefix}-{_i}", title=f"{prefix}-{_i}")
                    return replace(current, imports=current.imports + (session,))

                archive._mutate_identity("imports", apply)
        except Exception as e:  # noqa: BLE001 — the test reports every failure
            errors.append(e)

    a = threading.Thread(target=writer, args=("a",))
    b = threading.Thread(target=writer, args=("b",))
    a.start()
    b.start()
    a.join()
    b.join()
    assert not errors
    latest = archive.get_identity("imports")
    assert latest is not None
    ids = [s.id for s in latest.imports]
    # every write landed exactly once — no collision crash, no lost update
    assert len(ids) == 30
    assert all(f"a-{i}" in ids and f"b-{i}" in ids for i in range(15))


def test_a_later_determination_supersedes_an_earlier_one() -> None:
    """Every review determination is applied to the record as it stands — the
    archive is append-only, so a second determination supersedes the first and
    nothing is dismissed as stale (2026-10-21, user). A determination that
    leaves the record identical writes NO new version (byte-identical versions
    would clutter the chain the PRD calls the troubleshooting record), and one
    for an id the table does not hold changes nothing."""
    store = MemoryStore()
    archive = Archive(store)
    archive.save_identity(
        "people", validate_identity("people", {"people": [{"id": "p-x", "name": "X"}], "relationships": []})
    )
    before = archive.get_identity("people")
    assert before is not None
    assert len(archive._identity_versions("people")) == 1
    # p-x is already confirmed: confirming writes nothing, the determination stands
    assert archive.resolve_person("p-x", "attested", None) == before.record("p-x")
    assert len(archive._identity_versions("people")) == 1  # nothing written
    archive.resolve_person("p-x", "pending", None)
    assert len(archive._identity_versions("people")) == 1  # a keep changes nothing
    # a later determination supersedes the confirmation
    estimated = archive.resolve_person("p-x", "estimated", {"text": "she told me so"})
    assert isinstance(estimated, Person) and estimated.status == "estimated"
    assert len(archive._identity_versions("people")) == 2
    # …and a delete supersedes that
    assert archive.resolve_person("p-x", "delete", None) is not None
    table = archive.get_identity("people")
    assert table is not None and not table.has("p-x")
    assert len(archive._identity_versions("people")) == 3
    # an id the table never held: nothing to apply, nothing written
    assert archive.resolve_person("p-nope", "delete", None) is None
    assert len(archive._identity_versions("people")) == 3


def test_concurrent_message_recording_loses_nothing() -> None:
    """record_review_message must read the imports table under the lock —
    the lock covers the read, not just the version computation: two
    concurrent recordings computing from the same snapshot would let the
    second supersede the first, a lost line in the transcript. The
    mutation helper holds the lock across read, mutate, and write."""
    import threading

    store = MemoryStore()
    archive = Archive(store)
    archive.save_identity(
        "imports",
        validate_identity(
            "imports",
            {
                "imports": [
                    {
                        "id": "import-documents",
                        "title": "The document import",
                        "status": "pending",
                        "attempts": [{"started": "2026-08-10", "messages": [], "decisions": []}],
                    }
                ]
            },
        ),
    )
    errors: list[Exception] = []

    def writer(prefix: str) -> None:
        try:
            for i in range(15):
                archive.record_review_message("import-documents", "user", f"{prefix}-{i}", "2026-08-10")
        except Exception as e:  # noqa: BLE001 — the test reports every failure
            errors.append(e)

    a = threading.Thread(target=writer, args=("a",))
    b = threading.Thread(target=writer, args=("b",))
    a.start()
    b.start()
    a.join()
    b.join()
    assert not errors
    session = archive.get_review_session("import-documents")
    assert session is not None
    attempt = session.current_attempt()
    assert attempt is not None
    texts = [m.text for m in attempt.messages]
    # every recorded line landed exactly once — no collision crash, no lost
    # update from a stale snapshot
    assert len(texts) == 30
    assert all(f"a-{i}" in texts and f"b-{i}" in texts for i in range(15))


def test_an_agreed_document_becomes_an_item_with_its_transcription() -> None:
    """The reviewed document mints an item dated to the document, its
    transcription a content file of that item (the model's `transcription`
    kind, versioned with the sidecar)."""
    archive, store = make_archive()
    item = archive.agree_document(
        title="A letter from Peg",
        date="1975-03-01",
        date_precision="exact",
        text="Dear Mum,\nwe arrived.",
    )
    assert item.id == "doc-1975-03-01"
    assert item.type == "document" and item.status == "catalogued"
    assert item.title == "A letter from Peg" and item.date == "1975-03-01"
    sidecar = json.loads(store.read("assets/doc-1975-03-01/item.json"))
    assert sidecar["assets"] == [{"kind": "transcription", "file": "transcription.txt", "caption": "The transcription"}]
    assert store.read("assets/doc-1975-03-01/transcription.txt") == "Dear Mum,\nwe arrived."


def test_a_second_document_of_the_same_date_gets_its_own_id() -> None:
    archive, _ = make_archive()
    first = archive.agree_document(title="One", date="1975-03-01", date_precision="exact", text="a")
    second = archive.agree_document(title="Two", date="1975-03-01", date_precision="exact", text="b")
    assert (first.id, second.id) == ("doc-1975-03-01", "doc-1975-03-01-2")


def test_re_agreeing_supersedes_the_item_it_became() -> None:
    """A corrected document supersedes its own item — the next version of the
    same id, never a second item for one document."""
    archive, store = make_archive()
    item = archive.agree_document(title="A letter", date="1975-03-01", date_precision="exact", text="first")
    archive.agree_document(
        title="A letter from Peg",
        date="1975-03-01",
        date_precision="exact",
        text="corrected",
        item_id=item.id,
    )
    assert archive.item_ids() == ["doc-1975-03-01"]
    superseded = archive.get_item(item.id)
    assert superseded is not None and superseded.title == "A letter from Peg"
    assert store.read("assets/doc-1975-03-01/transcription-2.txt") == "corrected"


def test_an_agreed_document_needs_a_title_and_a_viable_date() -> None:
    archive, _ = make_archive()
    with pytest.raises(ArchiveError, match="needs a title"):
        archive.agree_document(title="  ", date="1975-03-01", date_precision="exact", text="a")
    with pytest.raises(ArchiveError, match="date is not parseable"):
        archive.agree_document(title="A letter", date="1975-99-99", date_precision="exact", text="a")


# -- identification (stages 7-8): a document's entities and their decisions --


def _identified_archive() -> tuple[Archive, MemoryStore]:
    """An archive with the identity tables and one agreed document."""
    archive, store = make_archive()
    archive.save_identity(
        "people", validate_identity("people", {"people": [{"id": "p-fern", "name": "Fern"}], "relationships": []})
    )
    archive.save_identity("places", validate_identity("places", {"places": []}))
    _ = archive.agree_document(title="A letter", date="1971-05-01", date_precision="exact", text="Dear Fern,")
    return archive, store


def _proposal() -> Identification:
    """One identified document: a standing person and a fresh place."""
    return Identification(
        item_id="doc-1971-05-01",
        people=(Person.from_dict({"id": "p-fern", "name": "Fern"}),),
        places=(
            Place.from_dict(
                {
                    "id": "pl-seascale",
                    "name": "Seascale",
                    "status": "proposed",
                    "note": "Mentioned in A letter — location unknown.",
                }
            ),
        ),
    )


def test_identification_writes_proposed_refs_and_new_records() -> None:
    """Stage 7's answer lands on the document (one proposed ref per mention),
    in the identity tables (a new record proposed inside the table it would
    join — never a queue of its own), and as the item's read flag, so the
    document is never read twice for the same review."""
    archive, _ = _identified_archive()

    item = archive.record_identification(_proposal())

    assert [ref.to_dict() for ref in item.people_refs] == [{"id": "p-fern", "status": "proposed"}]
    assert [ref.to_dict() for ref in item.place_refs] == [{"id": "pl-seascale", "status": "proposed"}]
    assert item.identified is True
    stored = archive.get_item("doc-1971-05-01")
    assert stored is not None and stored.identified is True  # persisted, not just in the answer
    places = archive.get_identity("places")
    assert places is not None
    proposed = places.record("pl-seascale")
    assert proposed is not None and proposed.status == "proposed"
    people = archive.get_identity("people")
    assert people is not None
    # a standing record is never rewritten as a proposal
    fern = people.record("p-fern")
    assert fern is not None and fern.status == "confirmed"


def test_identification_keeps_an_existing_link_and_its_status() -> None:
    """A document that already names someone keeps that link: the pass adds
    the entities it reads and never downgrades a confirmed link to a
    proposal (a pre-existing archive's links survive the first read)."""
    archive, _ = _identified_archive()
    item = archive.get_item("doc-1971-05-01")
    assert item is not None
    sidecar = dict(item.to_dict())
    sidecar["people"] = [{"id": "p-fern", "status": "confirmed"}]
    archive.save_item(Item(sidecar))

    read = archive.record_identification(_proposal())

    links = {ref.id: ref.status for ref in read.people_refs}
    assert links == {"p-fern": "confirmed"}  # the existing link wins
    assert [ref.id for ref in read.place_refs] == ["pl-seascale"]  # the new one is added


def test_attested_confirms_the_record_and_the_documents_mention() -> None:
    archive, _ = _identified_archive()
    _ = archive.record_identification(_proposal())

    record = archive.decide_identification("doc-1971-05-01", "place", "pl-seascale", "attested")

    assert isinstance(record, Place) and record.status == "confirmed"
    item = archive.get_item("doc-1971-05-01")
    assert item is not None and item.place_refs[0].status == "confirmed"
    places = archive.get_identity("places")
    assert places is not None
    confirmed = places.record("pl-seascale")
    assert confirmed is not None and confirmed.status == "confirmed"


def test_an_estimated_mention_records_the_familys_words() -> None:
    archive, _ = _identified_archive()
    _ = archive.record_identification(_proposal())
    basis = {"text": "we spent summers there", "by": "Alex", "when": "2026-10-29"}

    record = archive.decide_identification("doc-1971-05-01", "place", "pl-seascale", "estimated", basis)

    assert isinstance(record, Place) and record.status == "estimated"
    assert record.basis == basis
    item = archive.get_item("doc-1971-05-01")
    assert item is not None and item.place_refs[0].status == "estimated"


def test_deleting_a_mention_drops_an_unreferenced_proposal() -> None:
    archive, _ = _identified_archive()
    _ = archive.record_identification(_proposal())

    gone = archive.decide_identification("doc-1971-05-01", "place", "pl-seascale", "delete")

    assert isinstance(gone, GonePlace) and gone.id == "pl-seascale"
    item = archive.get_item("doc-1971-05-01")
    assert item is not None and item.place_refs == ()
    places = archive.get_identity("places")
    assert places is not None and places.record("pl-seascale") is None


def test_deleting_a_mention_never_deletes_a_confirmed_person() -> None:
    """The mention is the document's link, not the person: deleting it
    removes the link and leaves the family member alone."""
    archive, _ = _identified_archive()
    _ = archive.record_identification(_proposal())

    kept = archive.decide_identification("doc-1971-05-01", "person", "p-fern", "delete")

    assert isinstance(kept, Person) and kept.id == "p-fern"
    item = archive.get_item("doc-1971-05-01")
    assert item is not None and item.people_refs == ()
    people = archive.get_identity("people")
    assert people is not None and people.record("p-fern") is not None


def test_a_confirmed_person_stays_a_fact_when_the_mention_is_guessed() -> None:
    """A guess is the reviewer's uncertainty about the DOCUMENT's mention; a
    person the archive already holds as confirmed is never downgraded."""
    archive, _ = _identified_archive()
    _ = archive.record_identification(_proposal())

    record = archive.decide_identification(
        "doc-1971-05-01", "person", "p-fern", "estimated", {"text": "I think so", "by": "Alex", "when": "2026-10-29"}
    )

    assert isinstance(record, Person) and record.status == "confirmed"
    item = archive.get_item("doc-1971-05-01")
    assert item is not None and item.people_refs[0].status == "confirmed"


def test_deleting_a_mention_keeps_a_proposal_another_item_still_names() -> None:
    """One document's delete is not the whole archive's: a proposal another
    item still links stays proposed for that review."""
    archive, _ = _identified_archive()
    _ = archive.record_identification(_proposal())
    archive.save_item(
        Item.from_dict(
            _item(
                id="doc-1972-01-01",
                type="document",
                title="Another letter",
                date="1972-01-01",
                status="catalogued",
                places=[{"id": "pl-seascale", "status": "proposed"}],
            )
        )
    )

    kept = archive.decide_identification("doc-1971-05-01", "place", "pl-seascale", "delete")

    assert isinstance(kept, Place) and kept.status == "proposed"
    places = archive.get_identity("places")
    assert places is not None and places.record("pl-seascale") is not None
    item = archive.get_item("doc-1971-05-01")
    assert item is not None and item.place_refs == ()


def test_pending_changes_nothing() -> None:
    archive, store = _identified_archive()
    _ = archive.record_identification(_proposal())
    before = store.read("assets/doc-1971-05-01/item-2.json")

    record = archive.decide_identification("doc-1971-05-01", "place", "pl-seascale", "pending")

    assert isinstance(record, Place) and record.status == "proposed"
    assert store.read("assets/doc-1971-05-01/item-2.json") == before  # no new version, nothing rewritten


def test_deciding_an_unknown_entity_returns_none() -> None:
    archive, _ = _identified_archive()
    assert archive.decide_identification("doc-1971-05-01", "person", "p-ghost", "attested") is None


# -- B1: the identity half writes through the live store ---------------------


def _live_archive() -> tuple[Archive, MemoryStore, MemoryLiveStore]:
    """The identified archive with its identity surface flipped to a live
    store and the compatibility exporter bound (REWRITE-PLAN B1)."""
    archive, store = _identified_archive()
    live = MemoryLiveStore(app_version="test")
    archive.bind_identity_service(live.identities, CompatibilityExport(live, archive).write)
    sync_from_archive(live, archive)
    return archive, store, live


def test_a_live_identification_writes_the_proposals_through_the_service() -> None:
    archive, _, live = _live_archive()
    item = archive.record_identification(_proposal())
    assert item.identified is True
    seascale = live.places.require("pl-seascale")
    assert isinstance(seascale, Place) and seascale.status == "proposed"
    fern = live.people.require("p-fern")
    assert fern.status == "confirmed"  # a standing record is never rewritten
    table = archive.get_identity("places")
    assert table is not None and table.record("pl-seascale") is not None  # the compat export ran
    assert live.verify_chain() == ()


def test_a_live_identification_decision_writes_the_record_and_the_compat_table() -> None:
    archive, _, live = _live_archive()
    _ = archive.record_identification(_proposal())
    record = archive.decide_identification("doc-1971-05-01", "place", "pl-seascale", "attested", actor="p-fern")
    assert isinstance(record, Place) and record.status == "confirmed"
    stored = live.places.require("pl-seascale")
    assert isinstance(stored, Place) and stored.status == "confirmed"
    table = archive.get_identity("places")
    assert table is not None
    exported = table.record("pl-seascale")
    assert exported is not None and exported.status == "confirmed"
    item = archive.get_item("doc-1971-05-01")
    assert item is not None and item.place_refs[0].status == "confirmed"


def test_a_live_identification_delete_ends_the_proposal_through_the_service() -> None:
    archive, _, live = _live_archive()
    _ = archive.record_identification(_proposal())
    record = archive.decide_identification("doc-1971-05-01", "place", "pl-seascale", "delete", actor="p-fern")
    assert isinstance(record, GonePlace)
    stored = live.places.require("pl-seascale")
    assert isinstance(stored, Place) and stored.status == "rejected"  # the row stays in the log
    table = archive.get_identity("places")
    assert table is not None and table.record("pl-seascale") is None  # excluded from the old table
