# lucidlint: ignore-file fakefs the import reads a real archive tree and writes a real
# SQLite database — C-level I/O, the testing standard's real-FS exception.
"""A4 — the item import: versions, content, refs, assets, marker, idempotency."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from loft.live.errors import LiveError
from loft.live.import_identity import import_identities
from loft.live.import_items import ItemImportError, import_items
from loft.live.store import LiveStore

SVG = b"<svg xmlns='http://www.w3.org/2000/svg'><rect width='1' height='1'/></svg>"


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(json.dumps(value, indent=1), encoding="utf-8")


def _item(item_id: str, *, title: str, item_type: str = "letter", **extra: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "id": item_id,
        "type": item_type,
        "title": title,
        "date": "1960-04-02",
        "date_precision": "exact",
        "status": "catalogued",
        "people": [],
        "places": [],
        "themes": [],
        "assets": [],
    }
    raw.update(extra)
    return raw


def _archive(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    # v1 of a story that still carries its text inline (the legacy shape)
    _write(
        root / "assets" / "story-1" / "item.json",
        _item(
            "story-1",
            title="The bucket",
            item_type="story",
            story="Q: Which boat? A: Sunlight.",
            people=[{"id": "p-1", "status": "confirmed"}],
        ),
    )
    # a letter whose transcription and page are files; the ref is a recollection
    trans = b"Dear Wren,\n\nThe flat is cold.\n"
    letter = _item(
        "letter-1",
        title="A cold flat",
        people=[{"id": "p-2", "status": "estimated"}],
        places=[{"id": "pl-1", "status": "proposed"}],
        description="The flat, in winter",
        provenance="Found in the brown box",
        source="https://example.invalid/letter",
        transcription_status="draft",
        assets=[
            {"kind": "transcription", "file": "transcription.txt", "caption": "The transcription"},
            {"kind": "page", "file": "page-1.svg", "caption": "Page 1"},
        ],
    )
    _write(root / "assets" / "letter-1" / "item.json", letter)
    _write(root / "assets" / "letter-1" / "transcription.txt", trans)
    _write(root / "assets" / "letter-1" / "page-1.svg", SVG)
    # an object with two versions — the picture (and its caption) changes
    obj = _item(
        "object-1",
        title="The viola",
        item_type="object",
        story="A viola, description only.",
        assets=[{"kind": "photo", "file": "page-1.svg", "caption": "The viola"}],
    )
    _write(root / "assets" / "object-1" / "item.json", obj)
    _write(root / "assets" / "object-1" / "page-1.svg", SVG)
    second = dict(obj)
    second["title"] = "The viola, restored"
    second["supersedes"] = "assets/object-1/item.json"
    _write(root / "assets" / "object-1" / "item-2.json", second)
    # a tombstoned item whose v1 names a transcription that is not on disk
    gone = _item(
        "gone-1",
        title="A seeded fake",
        item_type="story",
        assets=[{"kind": "transcription", "file": "transcription.txt", "caption": "The transcription"}],
    )
    _write(root / "assets" / "gone-1" / "item.json", gone)
    _write(
        root / "assets" / "gone-1" / "item-2.json",
        {
            "id": "gone-1",
            "type": "story",
            "title": "A seeded fake",
            "status": "deleted",
            "reason": "seeded fake",
            "supersedes": "assets/gone-1/item.json",
        },
    )
    # an unfinished story — its text is a draft
    _write(
        root / "assets" / "draft-1" / "item.json",
        _item("draft-1", title="Half a memory", item_type="story", status="draft", story="I started to say…"),
    )
    marker = root / "backup.json"
    marker.write_text(json.dumps({"verified": True}), encoding="utf-8")
    return marker


def _imported(tmp_path: Path) -> tuple[LiveStore, Any]:
    archive = tmp_path / "archive"
    marker = _archive(archive)
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    report = import_items(store, archive, backup_marker=marker)
    return store, report


def test_the_item_import_counts_versions_content_refs_and_assets(tmp_path: Path) -> None:
    store, report = _imported(tmp_path)
    try:
        assert report.counts == {"items": 5, "versions": 7, "content": 3, "refs": 3, "assets": 3}
        assert report.skipped == {"items": 0, "versions": 0}
        assert report.mismatches == ()
        assert report.missing == ("gone-1 v1: transcription.txt",)
        assert store.verify_chain() == ()
    finally:
        store.close()


def test_the_imported_items_read_back_field_by_field(tmp_path: Path) -> None:
    store, _report = _imported(tmp_path)
    try:
        story = store.items.require("story-1")
        assert (story.title, story.type, story.date, story.date_precision, story.status) == (
            "The bucket",
            "story",
            "1960-04-02",
            "exact",
            "catalogued",
        )
        assert "story" not in story.raw  # primary content left the sidecar
        assert store.items.content("story-1", "story") == b"Q: Which boat? A: Sunlight."

        letter = store.items.require("letter-1")
        assert (letter.title, letter.description, letter.provenance, letter.source) == (
            "A cold flat",
            "The flat, in winter",
            "Found in the brown box",
            "https://example.invalid/letter",
        )
        refs = store.items.refs("letter-1")
        assert [(ref.kind, ref.ref_id, ref.status) for ref in refs] == [
            ("person", "p-2", "confirmed"),
            ("place", "pl-1", "proposed"),
        ]
        assert refs[0].basis == {"basis": "recollection", "confidence": "possible"}
        assets = store.items.assets("letter-1")
        assert [(asset.kind, asset.file) for asset in assets] == [
            ("transcription", "transcription.txt"),
            ("page", "page-1.svg"),
        ]
        assert store.items.content("letter-1", "transcription") == b"Dear Wren,\n\nThe flat is cold.\n"
        assert (
            store.items.content_sha("letter-1", "transcription")
            == hashlib.sha256(b"Dear Wren,\n\nThe flat is cold.\n").hexdigest()
        )
        assert [(row.kind, row.trust) for row in store.items.contents("letter-1")] == [("transcription", "draft")]
        assert [(row.kind, row.trust) for row in store.items.contents("story-1")] == [("story", "confirmed")]
        record = store.items.asset(assets[0].asset_id)
        assert record is not None
        assert record.sha256 == hashlib.sha256(b"Dear Wren,\n\nThe flat is cold.\n").hexdigest()
        assert record.mime == "text/plain"
        page = store.items.asset(assets[1].asset_id)
        assert page is not None
        assert page.mime == "image/svg+xml"

        draft = store.items.require("draft-1")
        assert draft.status == "draft"
        assert [(row.kind, row.trust) for row in store.items.contents("draft-1")] == [("story", "draft")]
    finally:
        store.close()


def test_the_versions_import_in_order_and_a_tombstone_is_deleted(tmp_path: Path) -> None:
    store, _report = _imported(tmp_path)
    try:
        obj = store.items.require("object-1")
        assert (obj.title, obj.version) == ("The viola, restored", 2)
        assert [e["event_type"] for e in store.events_for("object-1", entity_kind="item")] == [
            "created",
            "superseded",
        ]
        assert [e["entity_version"] for e in store.events_for("object-1", entity_kind="item")] == [1, 2]
        gone = store.items.require("gone-1")
        assert gone.status == "deleted"
        assert [e["event_type"] for e in store.events_for("gone-1", entity_kind="item")] == [
            "created",
            "deleted",
        ]
    finally:
        store.close()


def test_a_dry_run_writes_nothing(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    marker = _archive(archive)
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        report = import_items(store, archive, backup_marker=marker, dry_run=True)
        assert report.dry_run is True
        assert report.operations
        assert store.items.get("story-1") is None
        assert store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert store.connection.execute("SELECT COUNT(*) FROM content").fetchone()[0] == 0
    finally:
        store.close()


def test_a_rerun_is_a_no_op(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    marker = _archive(archive)
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        first = import_items(store, archive, backup_marker=marker)
        second = import_items(store, archive, backup_marker=marker)
        assert second.counts == {kind: 0 for kind in first.counts}
        assert second.skipped == {"items": 5, "versions": 7}
        assert second.operations == ()
        assert store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 7
    finally:
        store.close()


def test_a_partial_rerun_imports_only_the_missing_versions(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    marker = _archive(archive)
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        # import everything, then delete the object's second event? No — the
        # event log is append-only. Start over: import with the second sidecar
        # hidden, then restore it and run again.
        second = archive / "assets" / "object-1" / "item-2.json"
        second.rename(second.with_suffix(".hidden"))
        import_items(store, archive, backup_marker=marker)
        assert store.items.require("object-1").version == 1
        second.with_suffix(".hidden").rename(second)
        report = import_items(store, archive, backup_marker=marker)
        assert report.counts["items"] == 1
        assert report.counts["versions"] == 1
        assert report.skipped == {"items": 4, "versions": 5}
        assert store.items.require("object-1").title == "The viola, restored"
    finally:
        store.close()


def test_the_import_refuses_without_a_verified_marker(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    _archive(archive)
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        with pytest.raises(LiveError):
            import_items(store, archive, backup_marker=tmp_path / "missing.json")
        bad = tmp_path / "bad.json"
        bad.write_text('{"verified": false}', encoding="utf-8")
        with pytest.raises(LiveError):
            import_items(store, archive, backup_marker=bad)
    finally:
        store.close()


def test_a_live_item_whose_file_is_missing_fails_loudly(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    marker = _archive(archive)
    (archive / "assets" / "letter-1" / "transcription.txt").unlink()
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        with pytest.raises(ItemImportError, match="transcription.txt"):
            import_items(store, archive, backup_marker=marker)
        assert store.items.get("letter-1") is None
        assert store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    finally:
        store.close()


def test_duplicate_refs_are_collapsed_to_the_one_link(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    marker = _archive(archive)
    sidecar = archive / "assets" / "story-1" / "item.json"
    raw = json.loads(sidecar.read_text(encoding="utf-8"))
    raw["places"] = [{"id": "pl-1", "status": "proposed"}, {"id": "pl-1", "status": "proposed"}]
    sidecar.write_text(json.dumps(raw), encoding="utf-8")
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        import_items(store, archive, backup_marker=marker)
        refs = store.items.refs("story-1")
        assert [(ref.kind, ref.ref_id) for ref in refs] == [("person", "p-1"), ("place", "pl-1")]
    finally:
        store.close()


def test_items_can_be_imported_after_the_identity_tables(tmp_path: Path) -> None:
    """The real migration's order: identities first, then items whose refs
    resolve into them."""
    archive = tmp_path / "archive"
    marker = _archive(archive)
    (archive / "people.json").write_text(
        json.dumps(
            {
                "people": [
                    {"id": "p-1", "name": "Person 1"},
                    {"id": "p-2", "name": "Person 2"},
                ],
                "relationships": [],
            }
        ),
        encoding="utf-8",
    )
    (archive / "places.json").write_text(json.dumps({"places": [{"id": "pl-1", "name": "Place 1"}]}), encoding="utf-8")
    (archive / "orgs.json").write_text(json.dumps({"orgs": []}), encoding="utf-8")
    (archive / "themes.json").write_text(json.dumps({"themes": []}), encoding="utf-8")
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        import_identities(store, archive, backup_marker=marker)
        import_items(store, archive, backup_marker=marker)
        assert store.people.require("p-2").name == "Person 2"
        assert store.places.require("pl-1").name == "Place 1"
        assert store.items.require("letter-1").title == "A cold flat"
    finally:
        store.close()
