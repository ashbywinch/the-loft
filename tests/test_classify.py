"""Tests for content routing: the print/cursive density split, the
classify_pages shape, and run_classify's idempotency — the deterministic
contracts. The CLIP model itself runs on the real piles (the acceptance
test: PhotoScan must classify as photos)."""

from __future__ import annotations

import json
from pathlib import Path

from tools.classify import classify_pages, route, run_classify


def test_route_splits_print_and_cursive_at_the_threshold() -> None:
    assert route(1185) == "print"  # the printed reference fixture
    assert route(42) == "cursive"  # a real cursive page
    assert route(200) == "print"  # threshold is inclusive
    assert route(199) == "cursive"


def test_classify_pages_records_kind_and_confidences(tmp_path: Path) -> None:
    root = tmp_path / "pile"
    root.mkdir()
    pages = [root / "a.jpg", root / "b.jpg"]
    for p in pages:
        p.write_bytes(b"x")

    def fake(_page: Path) -> tuple[str, dict[str, float]]:
        return "photo", {"photo": 0.9, "text": 0.05, "drawing": 0.05}

    result = classify_pages(pages, fake, root)
    assert result["a.jpg"]["kind"] == "photo"
    assert result["b.jpg"]["confidences"]["photo"] == 0.9


def test_classify_pages_keys_by_relative_path_for_nested_piles(tmp_path: Path) -> None:
    root = tmp_path / "pile"
    (root / "sub").mkdir(parents=True)
    pages = [root / "top.JPG", root / "sub" / "nested.png"]
    for p in pages:
        p.write_bytes(b"x")

    def fake(_page: Path) -> tuple[str, dict[str, float]]:
        return "text", {"text": 0.9, "photo": 0.05, "drawing": 0.05}

    result = classify_pages(pages, fake, root)
    assert sorted(result) == ["sub/nested.png", "top.JPG"]  # relative keys, no basename collision


def test_run_classify_is_idempotent(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    registry.mkdir()
    batch = "adopt-0001"
    (registry / f"{batch}.json").write_text(
        json.dumps({"batch_id": batch, "path": str(tmp_path / "folder"), "pages": {"a.jpg": "h"}}),
        encoding="utf-8",
    )
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "a.jpg").write_bytes(b"x")

    calls = {"n": 0}

    def fake(_page: Path) -> tuple[str, dict[str, float]]:
        calls["n"] += 1
        return "photo", {"photo": 0.9, "text": 0.05, "drawing": 0.05}

    first = run_classify(batch, registry_dir=registry, work_dir=tmp_path / "work", classifier=fake)
    second = run_classify(batch, registry_dir=registry, work_dir=tmp_path / "work", classifier=fake)
    assert first == second
    assert calls["n"] == 1  # the classifier ran once — the stage is a cache
