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

from loft.live.batch_row import BatchState, ScanState
from loft.live.document_row import DocumentState
from loft.live.errors import Conflict, StaleVersion
from loft.live.items import ContentInput
from loft.live.memory import MemoryLiveStore
from loft.live.page_row import PageState
from loft.live.store import LiveStore
from tools.records import Item, Org, Person, Place, Relationship, Session
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


def _session(
    session_id: str = "import-test",
    *,
    status: str = "pending",
    messages: list[dict[str, Any]] | None = None,
) -> Session:
    return Session.from_dict(
        {
            "id": session_id,
            "kind": "import-review",
            "title": "The import",
            "status": status,
            "current": "p-a",
            "attempts": [
                {
                    "started": "2026-01-01T00:00:00+00:00",
                    "messages": messages
                    if messages is not None
                    else [
                        {"role": "user", "text": "I think so", "when": "2026-01-01"},
                        {"role": "assistant", "text": "Thanks", "when": "2026-01-01", "thinking": "raw verdict"},
                    ],
                    "decisions": [
                        {
                            "person_id": "p-a",
                            "decision": "estimated",
                            "when": "2026-01-01",
                            "basis": {"text": "the family's memory", "by": "Wren", "when": "2026-01-01"},
                        }
                    ],
                }
            ],
        }
    )


def test_a_review_session_is_one_event_a_row_its_messages_and_decisions(store: Any) -> None:
    with store.change(actor="import") as change:
        saved = change.reviews.save(_session())
    assert saved.version == 1
    assert store.events_for("import-test", entity_kind="review_session")[0]["event_type"] == "created"
    session = store.reviews.require("import-test")
    assert (session.kind, session.status, session.current_attempt) == ("import", "pending", 1)
    assert (session.subject_kind, session.actor_person_id) == ("batch", "import")
    assert [message.ordinal for message in store.reviews.messages("import-test")] == [1, 2]
    assert store.verify_chain() == ()


def test_review_decisions_map_to_the_target_vocabulary(store: Any) -> None:
    with store.change(actor="import") as change:
        change.reviews.save(_session())
    decision = store.reviews.decisions("import-test")[0]
    assert (decision.subject_kind, decision.subject_id, decision.decision) == ("person", "p-a", "attested")
    assert decision.basis == {
        "basis": "recollection",
        "confidence": "possible",
        "text": "the family's memory",
        "by": "Wren",
        "when": "2026-01-01",
    }


def test_review_thinking_is_content_addressed(store: Any) -> None:
    with store.change(actor="import") as change:
        change.reviews.save(_session())
    messages = store.reviews.messages("import-test")
    assert messages[0].thinking_sha is None
    assert messages[1].thinking_sha == hashlib.sha256(b"raw verdict").hexdigest()
    assert store.reviews.thinking("import-test", 2) == b"raw verdict"
    assert store.reviews.thinking("import-test", 1) is None


def test_a_review_supersede_replaces_the_transcript(store: Any) -> None:
    with store.change(actor="import") as change:
        change.reviews.save(_session())
    with store.change(actor="import") as change:
        second = change.reviews.save(
            _session(
                messages=[
                    {"role": "user", "text": "I think so", "when": "2026-01-01"},
                    {"role": "assistant", "text": "Thanks", "when": "2026-01-01", "thinking": "raw verdict"},
                    {"role": "user", "text": "And another thing", "when": "2026-01-02"},
                ]
            ),
            base=1,
        )
    assert second.version == 2
    assert [message.ordinal for message in store.reviews.messages("import-test")] == [1, 2, 3]
    assert [message.text for message in store.reviews.messages("import-test")][-1] == "And another thing"
    assert [event["event_type"] for event in store.events_for("import-test", entity_kind="review_session")] == [
        "created",
        "superseded",
    ]


def test_a_stale_review_base_is_refused_with_the_current_value(store: Any) -> None:
    with store.change(actor="import") as change:
        change.reviews.save(_session())
    with pytest.raises(StaleVersion) as caught, store.change(actor="import") as change:
        change.reviews.save(_session(), base=0)
    assert caught.value.current is not None
    assert store.reviews.require("import-test").version == 1


def test_a_failed_review_change_writes_nothing(store: Any) -> None:
    with pytest.raises(RuntimeError), store.change(actor="import") as change:
        change.reviews.save(_session())
        raise RuntimeError("boom")
    assert store.reviews.get("import-test") is None
    assert store.events_for("import-test", entity_kind="review_session") == []


def test_a_reviewed_session_closes_at_its_last_word(store: Any) -> None:
    with store.change(actor="import") as change:
        change.reviews.save(_session(status="reviewed"))
    session = store.reviews.require("import-test")
    assert session.current_attempt is None
    assert session.closed_at == "2026-01-01"


def test_rebuild_replays_review_sessions(store: Any) -> None:
    with store.change(actor="import") as change:
        change.reviews.save(_session())
    with store.change(actor="import") as change:
        change.reviews.save(
            _session(
                messages=[
                    {"role": "user", "text": "I think so", "when": "2026-01-01"},
                    {"role": "assistant", "text": "Thanks", "when": "2026-01-01", "thinking": "raw verdict"},
                    {"role": "user", "text": "And another thing", "when": "2026-01-02"},
                ]
            ),
            base=1,
        )
    store.rebuild_reviews()
    assert store.reviews.require("import-test").version == 2
    assert len(store.reviews.messages("import-test")) == 3
    assert store.reviews.decisions("import-test")[0].decision == "attested"
    assert store.reviews.thinking("import-test", 2) == b"raw verdict"
    assert store.verify_chain() == ()


def _batch(batch_id: str = "batch-1", *, status: str = "review") -> BatchState:
    return BatchState(
        batch_id=batch_id,
        label="A pile",
        source="external",
        path="/scans/pile",
        status=status,
        arrived_at="2026-01-01T00:00:00+00:00",
        started_at="",
        started_pid=0,
        started_host="",
        fingerprint=["sha-b", "sha-a"],
        content_changed=False,
    )


def _scans(batch_id: str = "batch-1") -> tuple[ScanState, ...]:
    return tuple(
        ScanState(
            scan_id=f"{batch_id}/page-0{index}.jpg",
            batch_id=batch_id,
            page_id=f"{batch_id}/page-0{index}.jpg",
            sha256=f"sha-{index}",
            path=f"/scans/pile/page-0{index}.jpg",
            ordinal=index - 1,
            created_at="2026-01-01T00:00:00+00:00",
        )
        for index in (1, 2)
    )


def _page(page_id: str = "batch-1/page-01.jpg", *, revision: int = 1) -> PageState:
    return PageState(
        page_id=page_id,
        image_asset_id=page_id,
        sha256="sha-1",
        revision=revision,
        rotation=180,
        category="text",
        status="rows_pending",
    )


def _reading(text: str = "Hello") -> dict[str, Any]:
    return {
        "page": "ignored",
        "width": 100,
        "height": 200,
        "rotation": 0,
        "revision": 1,
        "lines": [
            {
                "index": 0,
                "text": text,
                "box": [1, 2, 3, 4],
                "orientation": 0,
                "box_source": "reader",
                "words": [],
            },
            {
                "index": 1,
                "text": "World",
                "box": [5, 6, 7, 8],
                "orientation": 0,
                "box_source": "reader",
                "words": [],
            },
        ],
        "words": [{"x0": 1, "y0": 2, "x1": 3, "y1": 4, "line": 0, "baseline": 3, "waistline": 2}],
    }


def _document(
    document_id: str = "batch-1/doc-1", *, status: str = "review", item_id: str | None = None
) -> DocumentState:
    return DocumentState(
        document_id=document_id,
        item_id=item_id,
        batch_id="batch-1",
        doc_index=1,
        title=None,
        date_json=None,
        date=None,
        date2=None,
        date_precision=None,
        status=status,
        greeting="Dear",
        signoff=None,
        text_sha=None,
        confirmed_at=None,
    )


def test_a_batch_is_one_event_a_row_and_its_scans(store: Any) -> None:
    with store.change(actor="import") as change:
        saved = change.batches.save(_batch(), _scans())
    assert saved.version == 1
    assert store.batches.require("batch-1").status == "review"
    assert [scan.ordinal for scan in store.batches.scans("batch-1")] == [0, 1]
    assert store.events_for("batch-1", entity_kind="batch")[0]["event_type"] == "created"
    assert store.verify_chain() == ()


def test_a_batch_supersede_is_versioned_and_stale_is_refused(store: Any) -> None:
    with store.change(actor="import") as change:
        change.batches.save(_batch(), _scans())
    with store.change(actor="import") as change:
        second = change.batches.save(_batch(status="confirmed"), _scans(), base=1)
    assert second.version == 2
    assert store.batches.require("batch-1").status == "confirmed"
    with pytest.raises(StaleVersion), store.change(actor="import") as change:
        change.batches.save(_batch(), _scans(), base=1)


def test_a_page_is_one_event_its_reading_rows_and_adjustment(store: Any) -> None:
    with store.change(actor="import") as change:
        saved = change.pages.save(
            _page(),
            reading=_reading(),
            adjustment=b'{"lines":[]}',
            adjustment_at="2026-01-01T00:00:00+00:00",
        )
    assert saved.revision == 1
    page = store.pages.require("batch-1/page-01.jpg")
    assert (page.rotation, page.category, page.status) == (180, "text", "rows_pending")
    reading = store.pages.reading("batch-1/page-01.jpg")
    assert reading is not None and reading.rows == 2 and reading.words == 1
    rows = store.pages.rows("batch-1/page-01.jpg")
    assert [row.ordinal for row in rows] == [1, 2]
    assert [row.text for row in rows] == ["Hello", "World"]
    assert rows[0].source == "machine"
    adjustment = store.pages.adjustment("batch-1/page-01.jpg")
    assert adjustment is not None
    assert adjustment.sha256 == hashlib.sha256(b'{"lines":[]}').hexdigest()
    assert store.verify_chain() == ()


def test_a_corrected_page_records_human_rows_and_the_corrected_sha(store: Any) -> None:
    corrected = _reading("Corrected")
    corrected["corrected"] = "abc123"
    with store.change(actor="import") as change:
        change.pages.save(_page(), reading=corrected)
    reading = store.pages.reading("batch-1/page-01.jpg")
    assert reading is not None and reading.corrected_sha == "abc123"
    assert store.pages.rows("batch-1/page-01.jpg")[0].source == "human"


def test_a_page_supersede_bumps_the_revision_and_replaces_the_rows(store: Any) -> None:
    with store.change(actor="import") as change:
        change.pages.save(_page(), reading=_reading())
    with store.change(actor="import") as change:
        second = change.pages.save(_page(revision=1), base=1, reading=_reading("Changed"))
    assert second.revision == 2
    assert store.pages.require("batch-1/page-01.jpg").revision == 2
    assert store.pages.rows("batch-1/page-01.jpg")[0].text == "Changed"
    assert store.pages.rows("batch-1/page-01.jpg")[0].revision == 2


def test_a_document_is_one_event_its_pages_and_confirmed_text(store: Any) -> None:
    with store.change(actor="import") as change:
        saved = change.documents.save(_document(), ("batch-1/page-01.jpg", "batch-1/page-02.jpg"), text="Dear family")
    assert saved.text_sha == hashlib.sha256(b"Dear family").hexdigest()
    assert store.documents.require("batch-1/doc-1").status == "review"
    assert [page.page_id for page in store.documents.pages("batch-1/doc-1")] == [
        "batch-1/page-01.jpg",
        "batch-1/page-02.jpg",
    ]
    assert [page.ordinal for page in store.documents.pages("batch-1/doc-1")] == [0, 1]
    assert saved.text_sha is not None
    assert store.content.get(saved.text_sha) == b"Dear family"
    assert store.documents.for_batch("batch-1")[0].document_id == "batch-1/doc-1"


def test_a_document_supersede_is_versioned_and_stale_is_refused(store: Any) -> None:
    with store.change(actor="import") as change:
        change.documents.save(_document(), ("batch-1/page-01.jpg",))
    with store.change(actor="import") as change:
        second = change.documents.save(
            _document(status="confirmed", item_id="item-1"), ("batch-1/page-01.jpg",), base=1
        )
    assert second.version == 2
    assert store.documents.require("batch-1/doc-1").status == "confirmed"
    with pytest.raises(StaleVersion), store.change(actor="import") as change:
        change.documents.save(_document(), ("batch-1/page-01.jpg",), base=1)


def test_a_failed_pipeline_change_writes_nothing(store: Any) -> None:
    with pytest.raises(RuntimeError), store.change(actor="import") as change:
        change.batches.save(_batch(), _scans())
        change.pages.save(_page(), reading=_reading())
        raise RuntimeError("boom")
    assert store.batches.get("batch-1") is None
    assert store.pages.get("batch-1/page-01.jpg") is None
    assert store.events_for("batch-1", entity_kind="batch") == []


def test_rebuild_replays_the_pipeline(store: Any) -> None:
    with store.change(actor="import") as change:
        change.batches.save(_batch(), _scans())
        change.pages.save(_page(), reading=_reading(), adjustment=b'{"lines":[]}')
        change.documents.save(_document(), ("batch-1/page-01.jpg",), text="Dear family")
    store.rebuild_pipeline()
    assert store.batches.require("batch-1").version == 1
    assert len(store.batches.scans("batch-1")) == 2
    assert store.pages.require("batch-1/page-01.jpg").revision == 1
    assert [row.text for row in store.pages.rows("batch-1/page-01.jpg")] == ["Hello", "World"]
    reading = store.pages.reading("batch-1/page-01.jpg")
    assert reading is not None and reading.rows == 2
    assert store.documents.require("batch-1/doc-1").text_sha is not None
    assert len(store.documents.pages("batch-1/doc-1")) == 1
    assert store.verify_chain() == ()
