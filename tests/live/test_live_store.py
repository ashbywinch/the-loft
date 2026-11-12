"""A2 — the live store's one-change contract, on both implementations.

One change = one transaction: the events, the hash chain, the content blob
and the person projection commit together, and the same suite runs against
the SQLite store and the memory store (TECHSPEC/08 §19.7, §19.10.2–3).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from loft.live.errors import Conflict, StaleVersion
from loft.live.items import ContentInput
from loft.live.memory import MemoryLiveStore
from loft.live.store import LiveStore
from tools.records import Item, Org, Person, Place, Relationship
from tools.theme import Theme


@pytest.fixture(params=["sqlite", "memory"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Any]:
    if request.param == "sqlite":
        live = LiveStore.create(tmp_path / "loft.db", app_version="test")
    else:
        live = MemoryLiveStore(app_version="test")
    yield live
    live.close()


def _person(person_id: str = "p-alex", name: str = "Alex Hale") -> Person:
    return Person.from_dict({"id": person_id, "name": name, "status": "confirmed"})


def test_a_create_is_one_event_and_one_row(store: Any) -> None:
    person = _person()
    with store.change(actor="p-editor", note="add Alex") as change:
        saved = change.people.save(person)
    assert saved.version == 1
    assert store.people.require("p-alex").name == "Alex Hale"
    assert len(store.events_for("p-alex")) == 1
    assert store.events_for("p-alex")[0]["event_type"] == "created"
    assert store.verify_chain() == ()


def test_a_supersede_is_the_next_version_and_keeps_the_chain(store: Any) -> None:
    with store.change(actor="p-editor") as change:
        first = change.people.save(_person())
    with store.change(actor="p-editor") as change:
        second = change.people.save(Person.from_dict({"id": "p-alex", "name": "Alexandra Hale"}), base=first.version)
    assert second.version == 2
    assert store.people.require("p-alex").name == "Alexandra Hale"
    assert [e["event_type"] for e in store.events_for("p-alex")] == ["created", "superseded"]
    assert store.verify_chain() == ()


def test_a_stale_base_is_refused_with_the_current_value(store: Any) -> None:
    with store.change(actor="p-editor") as change:
        change.people.save(_person())
    with pytest.raises(StaleVersion) as caught, store.change(actor="p-editor") as change:
        change.people.save(Person.from_dict({"id": "p-alex", "name": "Other"}), base=0)
    assert caught.value.current is not None
    assert store.people.require("p-alex").name == "Alex Hale"


def test_a_failed_change_writes_nothing(store: Any) -> None:
    with pytest.raises(RuntimeError), store.change(actor="p-editor") as change:
        change.people.save(_person())
        raise RuntimeError("boom")
    assert store.people.get("p-alex") is None
    assert store.events_for("p-alex") == []


def test_content_is_create_if_absent_and_round_trips(store: Any) -> None:
    data = b"Ch\xc3\xa8re Maman.\n"
    with store.change(actor="p-editor") as change:
        sha = change.content.put(data, mime="text/plain")
    assert store.content.get(sha) == data
    with store.change(actor="p-editor") as change:
        assert change.content.put(data, mime="text/plain") == sha
    assert store.content.get(sha) == data


def test_a_duplicate_command_application_aborts(store: Any) -> None:
    with store.change(actor="p-editor", command_id="cmd-1") as change:
        change.people.save(_person())
    with pytest.raises(Conflict), store.change(actor="p-editor", command_id="cmd-1") as change:
        change.people.save(_person("p-other", "Other Person"))


def test_rebuild_replays_the_person_projection(store: Any) -> None:
    with store.change(actor="p-editor") as change:
        change.people.save(_person())
    with store.change(actor="p-editor") as change:
        change.people.save(Person.from_dict({"id": "p-alex", "name": "Alexandra Hale"}), base=1)
    store.rebuild_people()
    assert store.people.require("p-alex").name == "Alexandra Hale"
    assert store.people.require("p-alex").version == 2
    assert store.verify_chain() == ()


def test_a_batch_change_is_one_transaction_and_reads_its_writes(store: Any) -> None:
    """TECHSPEC/10 18.12.3: 2,000 saves in one transaction, and the change
    reads its own uncommitted rows; a failure rolls all of them back."""
    with store.change(actor="import") as change:
        for index in range(2_000):
            change.people.save(_person(f"p-batch-{index}", f"Person {index}"))
        assert store.people.require("p-batch-1999").name == "Person 1999"
    assert store.people.require("p-batch-0").version == 1
    with pytest.raises(RuntimeError), store.change(actor="import") as change:
        change.people.save(_person("p-batch-fail", "Never committed"))
        raise RuntimeError("boom")
    assert store.people.get("p-batch-fail") is None


def test_the_identity_collections_round_trip(store: Any) -> None:
    place = Place.from_dict({"id": "pl-london", "name": "London", "lat": 51.5, "lng": -0.18})
    org = Org.from_dict({"id": "org-ministry", "name": "Ministry of Supply", "address": "Ivybridge House"})
    theme = Theme.from_dict({"id": "t-boats", "title": "The boats", "items": [{"id": "object-sunlight"}]})
    edge = Relationship.from_dict(
        {"a": "p-alex", "b": "p-nora", "kind": "parent", "label_a": "father", "label_b": "daughter"}
    )
    with store.change(actor="import") as change:
        change.places.save(place)
        change.orgs.save(org)
        change.themes.save(theme)
        change.relationships.save(edge)
    assert store.places.require("pl-london").name == "London"
    assert store.orgs.require("org-ministry").address == "Ivybridge House"
    assert store.themes.require("t-boats").title == "The boats"
    assert store.relationships.require("rel-p-alex-p-nora-parent").a == "p-alex"
    assert store.verify_chain() == ()
    assert {e["entity_kind"] for e in store.events_for("pl-london", entity_kind="place")} == {"place"}


def test_a_place_supersede_is_versioned_and_stale_is_refused(store: Any) -> None:
    with store.change(actor="import") as change:
        first = change.places.save(Place.from_dict({"id": "pl-london", "name": "London"}))
    with store.change(actor="import") as change:
        second = change.places.save(Place.from_dict({"id": "pl-london", "name": "London, England"}), base=first.version)
    assert second.version == 2
    assert store.places.require("pl-london").name == "London, England"
    with pytest.raises(StaleVersion), store.change(actor="import") as change:
        change.places.save(Place.from_dict({"id": "pl-london", "name": "Stale"}), base=1)


def test_the_event_hash_covers_a_frozen_column_list(store: Any) -> None:
    from loft.live.event import event_hash

    with store.change(actor="p-editor") as change:
        change.people.save(_person())
    event = store.events_for("p-alex")[0]
    assert event["hash"] == event_hash(event)
    # a field outside the frozen list does not enter the hash
    changed = dict(event)
    changed["seq"] = 999
    assert event_hash(changed) == event["hash"]


def _item(
    item_id: str = "story-1",
    *,
    title: str = "A story",
    status: str = "catalogued",
    assets: list[dict[str, str]] | None = None,
    people: list[dict[str, str]] | None = None,
) -> Item:
    raw: dict[str, Any] = {
        "id": item_id,
        "type": "story",
        "title": title,
        "date": "1960",
        "date_precision": "year",
        "status": status,
        "people": people if people is not None else [{"id": "p-alex", "status": "confirmed"}],
        "places": [],
        "themes": [],
        "assets": (
            assets if assets is not None else [{"kind": "story", "file": "story.txt", "caption": "The story, verbatim"}]
        ),
    }
    if status == "deleted":
        raw = {
            "id": item_id,
            "type": "story",
            "title": title,
            "status": "deleted",
            "reason": "test tombstone",
        }
    return Item.from_dict(raw)


def _story() -> tuple[ContentInput, ...]:
    return (ContentInput(kind="story", data=b"The words.\\n", trust="confirmed"),)


def _files() -> dict[str, bytes]:
    return {"story.txt": b"The words.\\n"}


def test_an_item_is_one_event_a_row_its_refs_assets_and_content(store: Any) -> None:
    with store.change(actor="import") as change:
        saved = change.items.save(_item(), content=_story(), files=_files())
    assert saved.version == 1
    item = store.items.require("story-1")
    assert item.title == "A story"
    assert item.version == 1
    assert store.events_for("story-1", entity_kind="item")[0]["event_type"] == "created"
    assert store.verify_chain() == ()


def test_the_item_refs_assets_and_content_read_back(store: Any) -> None:
    with store.change(actor="import") as change:
        change.items.save(_item(), content=_story(), files=_files())
    refs = store.items.refs("story-1")
    assert [(ref.kind, ref.ref_id, ref.status) for ref in refs] == [("person", "p-alex", "confirmed")]
    assert refs[0].basis == {"basis": "knowledge", "confidence": "certain"}
    assets = store.items.assets("story-1")
    assert [(asset.kind, asset.file, asset.caption) for asset in assets] == [
        ("story", "story.txt", "The story, verbatim")
    ]
    record = store.items.asset(assets[0].asset_id)
    assert record is not None
    assert record.sha256 == hashlib.sha256(b"The words.\\n").hexdigest()
    assert record.size == len(b"The words.\\n")
    assert record.kind == "story"
    assert store.items.content_sha("story-1", "story") == record.sha256
    assert store.items.content("story-1", "story") == b"The words.\\n"
    assert [(row.kind, row.trust) for row in store.items.contents("story-1")] == [("story", "confirmed")]


def test_an_item_supersede_is_versioned_and_replaces_the_children(store: Any) -> None:
    with store.change(actor="import") as change:
        change.items.save(_item(), content=_story(), files=_files())
    with store.change(actor="import") as change:
        second = change.items.save(_item(title="A better story", assets=[], people=[]), base=1)
    assert second.version == 2
    assert store.items.require("story-1").title == "A better story"
    assert store.items.refs("story-1") == ()
    assert store.items.assets("story-1") == ()
    assert store.items.contents("story-1") == ()
    assert [e["event_type"] for e in store.events_for("story-1", entity_kind="item")] == ["created", "superseded"]


def test_a_tombstone_is_a_deleted_event_that_keeps_the_row(store: Any) -> None:
    with store.change(actor="import") as change:
        change.items.save(_item(), content=_story(), files=_files())
    with store.change(actor="import") as change:
        change.items.save(_item(status="deleted"), base=1)
    item = store.items.require("story-1")
    assert item.status == "deleted"
    assert item.raw["reason"] == "test tombstone"
    assert [e["event_type"] for e in store.events_for("story-1", entity_kind="item")] == ["created", "deleted"]


def test_a_stale_item_base_is_refused_with_the_current_value(store: Any) -> None:
    with store.change(actor="import") as change:
        change.items.save(_item(), content=_story(), files=_files())
    with pytest.raises(StaleVersion) as caught, store.change(actor="import") as change:
        change.items.save(_item(title="Stale"), base=0)
    assert caught.value.current is not None
    assert store.items.require("story-1").title == "A story"


def test_a_failed_item_change_writes_nothing(store: Any) -> None:
    with pytest.raises(RuntimeError), store.change(actor="import") as change:
        change.items.save(_item(), content=_story(), files=_files())
        raise RuntimeError("boom")
    assert store.items.get("story-1") is None
    assert store.events_for("story-1", entity_kind="item") == []


def test_rebuild_replays_the_item_projection(store: Any) -> None:
    with store.change(actor="import") as change:
        change.items.save(_item(), content=_story(), files=_files())
    with store.change(actor="import") as change:
        change.items.save(_item(title="A better story"), base=1, content=_story(), files=_files())
    store.rebuild_items()
    item = store.items.require("story-1")
    assert item.title == "A better story"
    assert item.version == 2
    assert store.items.content("story-1", "story") == b"The words.\\n"
    assert len(store.items.refs("story-1")) == 1
    assert store.verify_chain() == ()
