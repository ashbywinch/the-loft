"""B1 — the identity surface writes through the service (TECHSPEC/08 §19.4).

The ported identity scenarios: the archive's confirm/resolve/reject/promote
verbs and the review's four determinations, now one `Change` per action. The
suite runs on both stores, so the SQLite store and the memory store must agree
(TECHSPEC/08 §19.7).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from loft.live.errors import Conflict, NotFound, StaleVersion
from loft.live.memory import MemoryLiveStore
from loft.live.store import LiveStore
from tools.records import GonePerson, Item, Person, Place, Relationship
from tools.theme import Theme


@pytest.fixture(params=["sqlite", "memory"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Any]:
    if request.param == "sqlite":
        live = LiveStore.create(tmp_path / "loft.db", app_version="test")
    else:
        live = MemoryLiveStore(app_version="test")
    yield live
    live.close()


def _person(person_id: str = "p-alex", name: str = "Alex Hale", *, status: str = "confirmed") -> Person:
    return Person.from_dict({"id": person_id, "name": name, "status": status})


def _place(place_id: str = "pl-marlock", name: str = "Marlock", *, status: str = "confirmed") -> Place:
    return Place.from_dict({"id": place_id, "name": name, "status": status})


def _seed(store: Any, *records: Any) -> None:
    with store.change(actor="import") as change:
        for record in records:
            if isinstance(record, Person):
                change.people.save(record)
            elif isinstance(record, Place):
                change.places.save(record)
            elif isinstance(record, Theme):
                change.themes.save(record)


def _edge(a: str, b: str, kind: str = "spouse") -> Relationship:
    return Relationship.from_dict({"a": a, "b": b, "kind": kind, "label_a": "spouse", "label_b": "spouse"})


def _item(item_id: str = "letter-1", people: list[dict[str, str]] | None = None) -> Item:
    return Item.from_dict(
        {
            "id": item_id,
            "type": "letter",
            "title": "A letter",
            "date": "1960",
            "date_precision": "year",
            "status": "catalogued",
            "people": people if people is not None else [{"id": "p-alex", "status": "proposed"}],
            "places": [],
        }
    )


# -- confirm (ported from tests/test_archive.py) ----------------------------


def test_confirm_a_proposal_is_one_supersede(store: Any) -> None:
    _seed(store, _person(status="proposed"), _place())
    before = len(store.events_for("p-alex"))
    confirmed = store.identities.confirm_person("p-alex", actor="p-editor")
    assert confirmed.status == "confirmed"
    assert confirmed.version == 2
    events = store.events_for("p-alex")[before:]
    assert [event["event_type"] for event in events] == ["superseded"]
    assert len({event["change_id"] for event in events}) == 1
    assert store.people.require("p-alex").status == "confirmed"
    assert store.verify_chain() == ()


def test_confirm_pins_the_relation_the_review_settled(store: Any) -> None:
    _seed(store, _person(status="proposed"))
    confirmed = store.identities.confirm_person("p-alex", relation="first cousin once removed", actor="p-editor")
    assert confirmed.relation == "first cousin once removed"
    assert store.people.require("p-alex").relation == "first cousin once removed"


def test_confirming_a_confirmed_person_writes_nothing(store: Any) -> None:
    _seed(store, _person())
    before = store.events_for("p-alex")
    assert store.identities.confirm_person("p-alex", actor="p-editor").version == 1
    assert store.events_for("p-alex") == before


def test_confirming_an_unknown_person_raises(store: Any) -> None:
    with pytest.raises(NotFound):
        store.identities.confirm_person("p-ghost", actor="p-editor")


# -- resolve: the review's four determinations ------------------------------


def test_resolve_attested_confirms_with_knowledge(store: Any) -> None:
    _seed(store, _person(status="proposed"))
    resolved = store.identities.resolve_person("p-alex", "attested", actor="p-editor")
    assert isinstance(resolved, Person)
    assert resolved.status == "confirmed"
    assert resolved.basis == {"basis": "knowledge", "confidence": "certain"}
    assert store.people.require("p-alex").status == "confirmed"
    assert store.verify_chain() == ()


def test_resolve_estimated_records_the_basis_verbatim(store: Any) -> None:
    _seed(store, _person(status="proposed"))
    basis = {"text": "Grandma used to say this was the case.", "by": "Alex", "when": "2026-08-09"}
    resolved = store.identities.resolve_person("p-alex", "estimated", basis, actor="p-editor")
    assert isinstance(resolved, Person)
    assert resolved.status == "confirmed"  # estimated is a rendering, not a status
    assert resolved.basis == {"basis": "recollection", "confidence": "possible", **basis}
    stored = store.people.require("p-alex")
    assert stored.basis == {"basis": "recollection", "confidence": "possible", **basis}
    assert len(store.events_for("p-alex")) == 2  # the seed's create, then one supersede
    assert store.verify_chain() == ()


def test_resolve_estimated_requires_a_basis(store: Any) -> None:
    _seed(store, _person(status="proposed"))
    with pytest.raises(ValueError, match="basis"):
        store.identities.resolve_person("p-alex", "estimated", actor="p-editor")
    assert store.people.require("p-alex").status == "proposed"


def test_resolve_pending_writes_nothing(store: Any) -> None:
    _seed(store, _person(status="proposed"))
    before = store.events_for("p-alex")
    resolved = store.identities.resolve_person("p-alex", "pending", actor="p-editor")
    assert isinstance(resolved, Person) and resolved.status == "proposed"
    assert store.events_for("p-alex") == before


def test_resolve_attested_on_a_confirmed_person_writes_nothing(store: Any) -> None:
    _seed(store, _person())
    before = store.events_for("p-alex")
    resolved = store.identities.resolve_person("p-alex", "attested", actor="p-editor")
    assert isinstance(resolved, Person) and resolved.status == "confirmed"
    assert store.events_for("p-alex") == before  # byte-identical versions would clutter the chain


def test_a_later_determination_supersedes_an_earlier_one(store: Any) -> None:
    _seed(store, _person())
    assert len(store.events_for("p-alex")) == 1
    estimated = store.identities.resolve_person("p-alex", "estimated", {"text": "she told me so"}, actor="p-editor")
    assert isinstance(estimated, Person)
    assert estimated.basis is not None and estimated.basis["basis"] == "recollection"
    assert len(store.events_for("p-alex")) == 2
    gone = store.identities.resolve_person("p-alex", "delete", actor="p-editor")
    assert isinstance(gone, GonePerson)
    assert store.people.get("p-alex") is None
    assert len(store.events_for("p-alex")) == 3
    assert [event["event_type"] for event in store.events_for("p-alex")] == ["created", "superseded", "deleted"]
    assert store.verify_chain() == ()


def test_resolve_delete_removes_the_person_and_their_edges_in_one_change(store: Any) -> None:
    _seed(store, _person(), _person("p-robin", "Quentin Whitlock"))
    with store.change(actor="import") as change:
        change.relationships.save(_edge("p-robin", "p-alex"))
    before = len(store.events_for("p-alex")) + len(
        store.events_for("rel-p-robin-p-alex-spouse", entity_kind="relationship")
    )
    gone = store.identities.resolve_person("p-alex", "delete", actor="p-editor")
    assert isinstance(gone, GonePerson)
    assert store.people.get("p-alex") is None
    assert store.relationships.get("rel-p-robin-p-alex-spouse") is None
    after = len(store.events_for("p-alex")) + len(
        store.events_for("rel-p-robin-p-alex-spouse", entity_kind="relationship")
    )
    assert after - before == 2
    assert len({event["change_id"] for event in store.events_for("p-alex")}) == 2  # the seed, then the delete
    assert store.verify_chain() == ()


def test_resolve_an_unknown_person_returns_none_and_writes_nothing(store: Any) -> None:
    assert store.identities.resolve_person("p-ghost", "delete", actor="p-editor") is None
    assert store.events_for("p-ghost") == []


def test_a_stale_base_is_refused_with_the_current_value(store: Any) -> None:
    _seed(store, _person())
    with pytest.raises(StaleVersion) as caught, store.change(actor="p-editor") as change:
        change.people.save(_person(name="Other"), base=0)
    assert caught.value.current is not None
    assert store.people.require("p-alex").name == "Alex Hale"


def test_a_failed_identity_change_rolls_back(store: Any) -> None:
    _seed(store, _person(status="proposed"), _place())
    with pytest.raises(RuntimeError), store.change(actor="p-editor") as change:
        change.people.reject("p-alex")
        raise RuntimeError("boom")
    assert store.people.require("p-alex").status == "proposed"
    assert [event["event_type"] for event in store.events_for("p-alex")] == ["created"]


# -- reject: a proposal the review did not confirm --------------------------


def test_reject_a_proposal_keeps_the_row_and_marks_it_rejected(store: Any) -> None:
    _seed(store, _person(status="proposed"))
    rejected = store.identities.reject_person("p-alex", actor="p-editor")
    assert rejected.status == "rejected"
    stored = store.people.require("p-alex")
    assert stored.status == "rejected"  # the row stays; the log keeps the proposal
    assert [event["event_type"] for event in store.events_for("p-alex")] == ["created", "rejected"]
    assert store.verify_chain() == ()


def test_a_rejected_proposal_is_terminal(store: Any) -> None:
    _seed(store, _person(status="proposed"))
    store.identities.reject_person("p-alex", actor="p-editor")
    events = store.events_for("p-alex")
    resolved = store.identities.resolve_person("p-alex", "attested", actor="p-editor")
    assert isinstance(resolved, Person) and resolved.status == "rejected"
    assert store.events_for("p-alex") == events  # nothing revives a rejected record


def test_reject_a_confirmed_person_is_refused(store: Any) -> None:
    _seed(store, _person())
    with pytest.raises(Conflict):
        store.identities.reject_person("p-alex", actor="p-editor")
    assert store.people.require("p-alex").status == "confirmed"


def test_reject_a_place_keeps_the_row_marked_rejected(store: Any) -> None:
    _seed(store, _place(status="proposed"))
    rejected = store.identities.reject_place("pl-marlock", actor="p-editor")
    assert rejected.status == "rejected"
    assert store.places.require("pl-marlock").status == "rejected"


def test_reject_refuses_a_proposal_a_catalogued_item_still_names(store: Any) -> None:
    _seed(store, _person(status="proposed"))
    with store.change(actor="import") as change:
        change.items.save(_item(), files={})
    with pytest.raises(Conflict, match="letter-1"):
        store.identities.reject_person("p-alex", actor="p-editor")
    assert store.people.require("p-alex").status == "proposed"


# -- promote: a queued proposal joins the table as confirmed ----------------


def test_promote_a_proposal_confirms_it(store: Any) -> None:
    _seed(store, _person(status="proposed"), _place(status="proposed"))
    promoted = store.identities.promote_person("p-alex", actor="p-editor")
    assert promoted.status == "confirmed"
    assert store.people.require("p-alex").status == "confirmed"
    assert store.identities.promote_place("pl-marlock", actor="p-editor").status == "confirmed"


def test_promote_an_unknown_person_raises(store: Any) -> None:
    with pytest.raises(NotFound):
        store.identities.promote_person("p-ghost", actor="p-editor")


def test_promote_a_confirmed_person_is_refused(store: Any) -> None:
    _seed(store, _person())
    with pytest.raises(Conflict):
        store.identities.promote_person("p-alex", actor="p-editor")


# -- merge: the loser redirects to the survivor ------------------------------


def test_merge_records_the_alias_and_one_merged_event(store: Any) -> None:
    _seed(store, _person(), _person("p-alexander", "Alexander Hale"))
    before = len(store.events_for("p-alexander"))
    survivor = store.identities.merge_people("p-alexander", "p-alex", by="p-editor", actor="p-editor")
    assert survivor.id == "p-alex"
    events = store.events_for("p-alexander")[before:]
    assert [event["event_type"] for event in events] == ["merged"]
    assert store.aliases.get("person", "p-alexander") == "p-alex"
    assert store.people.require("p-alexander").status == "confirmed"  # the loser's row stays for the log
    assert store.verify_chain() == ()


def test_merge_moves_the_losers_edges_to_the_survivor(store: Any) -> None:
    _seed(
        store, _person("p-robin", "Robin Hale"), _person("p-sam", "Sam Hale"), _person("p-alexander", "Alexander Hale")
    )
    with store.change(actor="import") as change:
        change.relationships.save(_edge("p-sam", "p-alexander", "parent"))
    store.identities.merge_people("p-alexander", "p-robin", by="p-editor", actor="p-editor")
    assert store.relationships.get("rel-p-sam-p-alexander-parent") is None
    moved = store.relationships.get("rel-p-sam-p-robin-parent")
    assert moved is not None and (moved.a, moved.b) == ("p-sam", "p-robin")
    store.rebuild_all()
    assert store.relationships.get("rel-p-sam-p-alexander-parent") is None
    assert store.relationships.get("rel-p-sam-p-robin-parent") is not None
    assert store.aliases.get("person", "p-alexander") == "p-robin"
    assert store.verify_chain() == ()


def test_merge_refuses_a_loser_a_catalogued_item_still_names(store: Any) -> None:
    _seed(store, _person(), _person("p-alexander", "Alexander Hale"))
    with store.change(actor="import") as change:
        change.items.save(_item(), files={})
    with pytest.raises(Conflict, match="letter-1"):
        store.identities.merge_people("p-alex", "p-alexander", by="p-editor", actor="p-editor")
    assert store.aliases.get("person", "p-alex") is None


def test_merge_needs_a_known_survivor(store: Any) -> None:
    _seed(store, _person())
    with pytest.raises(NotFound):
        store.identities.merge_people("p-alex", "p-ghost", by="p-editor", actor="p-editor")


def test_rebuild_replays_rejection_and_merge(store: Any) -> None:
    _seed(
        store,
        _person("p-robin", "Robin Hale"),
        _person(status="proposed"),
        _person("p-alexander", "Alexander Hale"),
        _place(status="proposed"),
    )
    store.identities.reject_person("p-alex", actor="p-editor")
    store.identities.reject_place("pl-marlock", actor="p-editor")
    store.identities.merge_people("p-alexander", "p-robin", by="p-editor", actor="p-editor")
    store.rebuild_all()
    assert store.people.require("p-alex").status == "rejected"
    assert store.places.require("pl-marlock").status == "rejected"
    assert store.aliases.get("person", "p-alexander") == "p-robin"
    assert store.verify_chain() == ()


# -- the one writer, even under concurrent requests -------------------------


def test_concurrent_determinations_serialize_and_lose_nothing(store: Any) -> None:
    """The server runs sync routes in a thread pool: two decisions at once
    must both land, one after the other — never a nested BEGIN or a lost
    event."""
    _seed(store, _person(status="proposed"), _person("p-other", "Other Hale", status="proposed"))
    errors: list[Exception] = []

    def decide(person_id: str, decision: str) -> None:
        try:
            store.identities.resolve_person(person_id, decision, {"text": "told to me"}, actor="p-editor")
        except Exception as error:  # noqa: BLE001 — the test reports every failure
            errors.append(error)

    threads = [
        threading.Thread(target=decide, args=("p-alex", "estimated")),
        threading.Thread(target=decide, args=("p-other", "attested")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert store.people.require("p-alex").basis is not None
    assert store.people.require("p-other").basis == {"basis": "knowledge", "confidence": "certain"}
    assert store.verify_chain() == ()
