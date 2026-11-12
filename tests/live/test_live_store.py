"""A2 — the live store's one-change contract, on both implementations.

One change = one transaction: the events, the hash chain, the content blob
and the person projection commit together, and the same suite runs against
the SQLite store and the memory store (TECHSPEC/08 §19.7, §19.10.2–3).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from loft.live.errors import Conflict, StaleVersion
from loft.live.memory import MemoryLiveStore
from loft.live.store import LiveStore
from tools.records import Person


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
