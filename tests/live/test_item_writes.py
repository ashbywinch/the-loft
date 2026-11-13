"""B2 — items, content and document agreement write through the service.

The ported item scenarios: the archive's save, supersede, tombstone and
agreement, now one `Change` each, with the compatibility exporter writing the
old sidecar chain and content files synchronously. The suite runs on both
stores (TECHSPEC/08 §19.7).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from loft.live.compat_items import ItemCompatibility
from loft.live.import_items import sync_items
from loft.live.item_writes import ItemWrites
from loft.live.memory import MemoryLiveStore
from loft.live.store import LiveStore
from tools.archive import Archive
from tools.records import Item
from tools.store import MemoryStore


@pytest.fixture(params=["sqlite", "memory"])
def host(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[tuple[Any, Archive]]:
    if request.param == "sqlite":
        live = LiveStore.create(tmp_path / "loft.db", app_version="test")
    else:
        live = MemoryLiveStore(app_version="test")
    archive = Archive(MemoryStore())
    export = ItemCompatibility(live, archive)
    archive.bind_item_service(ItemWrites(live), export.write)
    yield live, archive
    live.close()


def _item(
    item_id: str = "story-x",
    *,
    item_type: str = "story",
    title: str = "A story",
    assets: list[dict[str, str]] | None = None,
    status: str = "catalogued",
) -> Item:
    raw: dict[str, Any] = {
        "id": item_id,
        "type": item_type,
        "title": title,
        "date": "1960",
        "date_precision": "year",
        "status": status,
        "assets": assets if assets is not None else [],
        "people": [],
        "places": [],
        "themes": [],
    }
    if status == "deleted":
        raw = {"id": item_id, "type": item_type, "title": title, "status": "deleted", "reason": "test"}
    return Item.from_dict(raw)


def _read(archive: Archive, path: str) -> str:
    return archive.store.read(path)


def test_a_live_save_is_one_change_and_the_old_sidecar(host: tuple[Any, Archive]) -> None:
    live, archive = host
    version = archive.save_item(_item(), content={"story": "We took the dinghy out."})
    assert version == 1
    stored = live.items.require("story-x")
    assert stored.version == 1 and stored.status == "catalogued"
    assert live.items.content("story-x", "story") == b"We took the dinghy out."
    assert [event["event_type"] for event in live.events_for("story-x", entity_kind="item")] == ["created"]
    assert live.verify_chain() == ()
    sidecar = json.loads(_read(archive, "assets/story-x/item.json"))
    assert sidecar["title"] == "A story"
    assert sidecar["assets"] == [{"kind": "story", "file": "story.txt", "caption": "The story, verbatim"}]
    assert "story" not in sidecar
    assert _read(archive, "assets/story-x/story.txt") == "We took the dinghy out."
    resolved = archive.get_item("story-x")
    assert resolved is not None and resolved.title == "A story"


def test_a_live_supersede_is_the_next_version(host: tuple[Any, Archive]) -> None:
    live, archive = host
    archive.save_item(_item(title="One"), content={"story": "Version one."})
    version = archive.save_item(_item(title="Two"), content={"story": "Version two."})
    assert version == 2
    assert live.items.require("story-x").version == 2
    assert [event["event_type"] for event in live.events_for("story-x", entity_kind="item")] == [
        "created",
        "superseded",
    ]
    first = json.loads(_read(archive, "assets/story-x/item.json"))
    second = json.loads(_read(archive, "assets/story-x/item-2.json"))
    assert first["title"] == "One"  # the first version is untouched
    assert second["supersedes"] == "assets/story-x/item.json"
    assert {"kind": "story", "file": "story-2.txt", "caption": "The story, verbatim"} in second["assets"]
    assert _read(archive, "assets/story-x/story.txt") == "Version one."
    assert _read(archive, "assets/story-x/story-2.txt") == "Version two."
    assert live.items.content("story-x", "story") == b"Version two."


def test_a_live_tombstone_is_the_deleted_version(host: tuple[Any, Archive]) -> None:
    live, archive = host
    archive.save_item(_item(title="One"))
    archive.delete_item("story-x", "test fabrication")
    stored = live.items.require("story-x")
    assert stored.status == "deleted" and stored.raw["reason"] == "test fabrication"
    assert [event["event_type"] for event in live.events_for("story-x", entity_kind="item")] == ["created", "deleted"]
    tombstone = json.loads(_read(archive, "assets/story-x/item-2.json"))
    assert tombstone["status"] == "deleted" and tombstone["reason"] == "test fabrication"
    assert archive.get_item("story-x") is None


def test_a_live_agreement_mints_the_document(host: tuple[Any, Archive]) -> None:
    live, archive = host
    item = archive.agree_document(
        title="A letter from Peg", date="1975-03-01", date_precision="exact", text="Dear Mum,\nwe arrived."
    )
    assert item.id == "doc-1975-03-01"
    stored = live.items.require(item.id)
    assert stored.type == "document" and stored.title == "A letter from Peg"
    assert live.items.content(item.id, "transcription") == b"Dear Mum,\nwe arrived."
    sidecar = json.loads(_read(archive, f"assets/{item.id}/item.json"))
    assert sidecar["assets"] == [{"kind": "transcription", "file": "transcription.txt", "caption": "The transcription"}]
    assert _read(archive, f"assets/{item.id}/transcription.txt") == "Dear Mum,\nwe arrived."

    corrected = archive.agree_document(
        title="A letter from Peg", date="1975-03-01", date_precision="exact", text="corrected", item_id=item.id
    )
    assert corrected.id == item.id
    assert live.items.require(item.id).version == 2
    assert _read(archive, f"assets/{item.id}/transcription-2.txt") == "corrected"
    second = archive.agree_document(title="Two", date="1975-03-01", date_precision="exact", text="b")
    assert second.id == "doc-1975-03-01-2"


def test_a_live_re_save_keeps_an_unsupplied_transcription(host: tuple[Any, Archive]) -> None:
    live, archive = host
    archive.agree_document(title="A letter", date="1975-03-01", date_precision="exact", text="the words")
    current = archive.get_item("doc-1975-03-01")
    assert current is not None
    archive.save_item(Item({**current.to_dict(), "title": "A better title"}))
    stored = live.items.require("doc-1975-03-01")
    assert stored.title == "A better title"
    assert live.items.content("doc-1975-03-01", "transcription") == b"the words"
    # the transcription keeps its existing file — a re-save is not a content edit
    assert _read(archive, "assets/doc-1975-03-01/transcription.txt") == "the words"
    assert not archive.store.exists("assets/doc-1975-03-01/transcription-2.txt")


def test_a_live_save_reads_its_asset_bytes(host: tuple[Any, Archive]) -> None:
    live, archive = host
    archive.save_file("photo-x", "scan.jpg", b"\xff\xd8scan")
    archive.save_item(
        _item("photo-x", item_type="photo", assets=[{"kind": "scan", "file": "scan.jpg", "caption": ""}]),
        content={},
    )
    assets = live.items.assets("photo-x")
    assert [(asset.kind, asset.file) for asset in assets] == [("scan", "scan.jpg")]
    record = live.items.asset(assets[0].asset_id)
    assert record is not None and record.size == 6


def test_the_exporter_replays_a_missing_version(host: tuple[Any, Archive]) -> None:
    live, archive = host
    export = ItemCompatibility(live, archive)
    archive.save_item(_item(title="One"), content={"story": "one"})
    archive.save_item(_item(title="Two"), content={"story": "two"})
    archive.store.delete("assets/story-x/item-2.json")  # a crash after the commit
    assert export.write("story-x") == (2,)
    assert json.loads(_read(archive, "assets/story-x/item-2.json"))["title"] == "Two"
    assert _read(archive, "assets/story-x/story-2.txt") == "two"


def test_the_exporter_repairs_a_missing_content_file(host: tuple[Any, Archive]) -> None:
    live, archive = host
    export = ItemCompatibility(live, archive)
    archive.save_item(_item(), content={"story": "the words"})
    archive.store.delete("assets/story-x/story.txt")  # a crash between sidecar and content
    assert export.write("story-x") == ()
    assert _read(archive, "assets/story-x/story.txt") == "the words"


def test_the_exporter_is_idempotent(host: tuple[Any, Archive]) -> None:
    live, archive = host
    export = ItemCompatibility(live, archive)
    archive.save_item(_item(), content={"story": "the words"})
    assert export.write("story-x") == ()
    assert export.write_all() == ()


def test_the_old_writer_and_the_live_export_agree() -> None:
    old = Archive(MemoryStore())
    old.save_item(_item(), content={"story": "We took the dinghy out."})

    live = MemoryLiveStore(app_version="test")
    archive = Archive(MemoryStore())
    archive.bind_item_service(ItemWrites(live), ItemCompatibility(live, archive).write)
    try:
        archive.save_item(_item(), content={"story": "We took the dinghy out."})
    finally:
        live.close()
    assert json.loads(old.store.read("assets/story-x/item.json")) == json.loads(
        archive.store.read("assets/story-x/item.json")
    )
    assert old.store.read("assets/story-x/story.txt") == archive.store.read("assets/story-x/story.txt")


def test_a_re_import_of_the_exported_items_is_a_no_op(host: tuple[Any, Archive]) -> None:
    live, archive = host
    archive.save_item(_item(), content={"story": "the words"})
    report = sync_items(live, archive)
    assert report.operations == ()
    fresh = MemoryLiveStore(app_version="test")
    try:
        imported = sync_items(fresh, archive)
        assert imported.mismatches == ()
        assert imported.counts == {"items": 1, "versions": 1, "content": 1, "refs": 0, "assets": 1}
        assert fresh.items.content("story-x", "story") == b"the words"
        assert sync_items(fresh, archive).operations == ()
    finally:
        fresh.close()
