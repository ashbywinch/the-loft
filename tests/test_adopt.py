"""Tests for the adopt component: in-place registration, idempotency, and
re-association by content fingerprint — the deterministic contracts; the
real piles (PhotoScan, the scan output) are adopted by hand, not in tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.adopt import AdoptionError, page_files, register_adopted


def _pile(tmp_path: Path, name: str = "pile") -> Path:
    from PIL import Image

    folder = tmp_path / name
    folder.mkdir()
    Image.new("RGB", (8, 8), (255, 0, 0)).save(folder / "a.jpg", quality=88)
    Image.new("RGB", (8, 8), (0, 255, 0)).save(folder / "b.jpg", quality=88)
    return folder


def test_register_adopted_creates_record_without_touching_the_folder(tmp_path: Path) -> None:
    folder = _pile(tmp_path)
    registry = tmp_path / "registry"

    record_path, outcome = register_adopted(folder, label="Box 1", registry_dir=registry)

    assert outcome == "new"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["label"] == "Box 1"
    assert record["status"] == "pending"
    assert sorted(record["pages"]) == ["a.jpg", "b.jpg"]
    assert record["fingerprint"] == sorted(record["pages"].values())
    assert sorted(p.name for p in folder.iterdir()) == ["a.jpg", "b.jpg"]  # never modified


def test_register_adopted_is_idempotent(tmp_path: Path) -> None:
    folder = _pile(tmp_path)
    registry = tmp_path / "registry"

    first, _ = register_adopted(folder, registry_dir=registry)
    second, outcome = register_adopted(folder, registry_dir=registry)

    assert outcome == "already-registered"
    assert second == first
    assert len(list(registry.glob("*.json"))) == 1


def test_register_adopted_reassociates_a_moved_folder(tmp_path: Path) -> None:
    folder = _pile(tmp_path)
    registry = tmp_path / "registry"

    first, _ = register_adopted(folder, registry_dir=registry)
    moved = tmp_path / "renamed-pile"
    folder.rename(moved)
    second, outcome = register_adopted(moved, registry_dir=registry)

    assert outcome == "re-associated"
    assert second == first  # same record, id stable
    record = json.loads(first.read_text(encoding="utf-8"))
    assert record["path"] == str(moved)
    assert len(list(registry.glob("*.json"))) == 2  # base + PipelineStore versioned copy


def test_register_adopted_rejects_folders_without_images(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(AdoptionError, match="no page images"):
        _ = register_adopted(empty, registry_dir=tmp_path / "registry")
    with pytest.raises(AdoptionError, match="no such folder"):
        _ = register_adopted(tmp_path / "missing", registry_dir=tmp_path / "registry")


def test_register_adopted_updates_a_changed_pile_not_duplicates_it(tmp_path: Path) -> None:
    from PIL import Image

    folder = _pile(tmp_path)
    registry = tmp_path / "registry"
    first, _ = register_adopted(folder, label="Box 1", registry_dir=registry)

    Image.new("RGB", (8, 8), (0, 0, 255)).save(folder / "c.jpg", quality=88)  # a page was added
    second, outcome = register_adopted(folder, registry_dir=registry)

    assert outcome == "content-changed"
    assert second == first  # the same record, not a silent duplicate
    record = json.loads(first.read_text(encoding="utf-8"))
    assert sorted(record["pages"]) == ["a.jpg", "b.jpg", "c.jpg"]
    assert record["label"] == "Box 1"  # the pile's label survives
    assert record["status"] == "pending"  # reprocessed
    assert len(list(registry.glob("*.json"))) == 2  # base + PipelineStore versioned copy


def test_page_files_lists_images_recursively(tmp_path: Path) -> None:
    from PIL import Image

    folder = tmp_path / "pile"
    (folder / "sub").mkdir(parents=True)
    Image.new("RGB", (8, 8), (0, 0, 255)).save(folder / "top.JPG", quality=88)  # uppercase ext
    Image.new("RGB", (8, 8), (0, 255, 255)).save(folder / "sub" / "nested.png", quality=88)
    (folder / "notes.txt").write_text("not an image")

    names = [str(p.relative_to(folder)) for p in page_files(folder)]
    assert names == ["sub/nested.png", "top.JPG"]  # name order, images only


def test_register_adopted_preserves_confirmed_content_on_change(tmp_path: Path) -> None:
    """2026-08-14 review: a content-changed pile with confirmed transcriptions
    must NOT have them cleared — the change is flagged for a manual review."""
    from PIL import Image

    from tools.sync import record_confirmation

    folder = _pile(tmp_path)
    registry = tmp_path / "registry"
    record_path, _ = register_adopted(folder, label="Box 1", registry_dir=registry)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record_confirmation(
        record["batch_id"], 1, {"pages": ["a.jpg"]}, "Chère Maman.", work_dir=tmp_path, registry_dir=registry
    )

    Image.new("RGB", (8, 8), (0, 0, 255)).save(folder / "c.jpg", quality=88)
    _, outcome = register_adopted(folder, registry_dir=registry)

    assert outcome == "content-changed"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["content_changed"] is True
    assert record["boundaries"][0]["status"] == "confirmed"  # the confirmed text survives
    confirmed = tmp_path / record["batch_id"] / "ocr-confirmed" / "doc-01.txt"
    assert confirmed.exists()  # never cleared
    assert confirmed.read_text(encoding="utf-8") == "Chère Maman."


def test_register_adopted_clears_stages_when_nothing_confirmed(tmp_path: Path) -> None:
    """The no-confirmed-content branch still clears the regenerable stages
    so the reprocess is real (2026-08-14 review: the flag's consumer)."""
    from PIL import Image

    folder = _pile(tmp_path)
    registry = tmp_path / "registry"
    work = tmp_path / "work"
    record_path, _ = register_adopted(folder, label="Box 1", registry_dir=registry, work_dir=work)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    stale = work / record["batch_id"]
    (stale / "ocr-guess").mkdir(parents=True)
    (stale / "ocr-guess" / "boundaries.json").write_text("[]", encoding="utf-8")

    Image.new("RGB", (8, 8), (0, 0, 255)).save(folder / "c.jpg", quality=88)
    _, outcome = register_adopted(folder, registry_dir=registry, work_dir=work)

    assert outcome == "content-changed"
    assert not stale.exists()  # the regenerable stages were cleared


def test_register_adopted_reassociates_a_moved_and_changed_pile(tmp_path: Path) -> None:
    """2026-08-14 final review: a move combined with a content change must
    update the same record (large overlap), not orphan it as a duplicate."""
    from PIL import Image

    folder = _pile(tmp_path)
    registry = tmp_path / "registry"
    first, _ = register_adopted(folder, label="Box 1", registry_dir=registry, work_dir=tmp_path / "work")

    moved = tmp_path / "renamed-pile"
    folder.rename(moved)
    Image.new("RGB", (8, 8), (0, 0, 255)).save(moved / "c.jpg", quality=88)  # added a page while moving
    second, outcome = register_adopted(moved, registry_dir=registry, work_dir=tmp_path / "work")

    assert outcome == "content-changed"
    assert second == first  # not a duplicate record
    record = json.loads(first.read_text(encoding="utf-8"))
    assert record["path"] == str(moved)
    assert sorted(record["pages"]) == ["a.jpg", "b.jpg", "c.jpg"]
    assert len(list(registry.glob("*.json"))) == 2  # base + PipelineStore versioned copy
