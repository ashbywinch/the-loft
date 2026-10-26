"""Tests for content routing: the print/cursive density split, the
classify_pages shape, run_classify's idempotency, and classify_page's
reading of the vision model's answer — the deterministic contracts plus
the one model call, driven through its injected transport."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.classify import classify_page, classify_pages, route, run_classify
from pipeline.model.vlm import VlmError
from pipeline.page_classification import PageClassification


class _BytesResponse:
    """The urlopen context-manager shim returning fixed bytes."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _BytesResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _completion(content: str) -> bytes:
    body = {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"completion_tokens": 7},
    }
    return json.dumps(body).encode()


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

    def fake(_page: Path) -> PageClassification:
        return PageClassification("photo", {"photo": 0.9, "text": 0.05, "drawing": 0.05})

    result = classify_pages(pages, fake, root)
    assert result["a.jpg"].kind == "photo"
    assert result["b.jpg"].confidences["photo"] == 0.9


def test_classify_pages_keys_by_relative_path_for_nested_piles(tmp_path: Path) -> None:
    root = tmp_path / "pile"
    (root / "sub").mkdir(parents=True)
    pages = [root / "top.JPG", root / "sub" / "nested.png"]
    for p in pages:
        p.write_bytes(b"x")

    def fake(_page: Path) -> PageClassification:
        return PageClassification("text", {"text": 0.9, "photo": 0.05, "drawing": 0.05})

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

    def fake(_page: Path) -> PageClassification:
        calls["n"] += 1
        return PageClassification("photo", {"photo": 0.9, "text": 0.05, "drawing": 0.05})

    first = run_classify(batch, registry_dir=registry, work_dir=tmp_path / "work", classifier=fake)
    second = run_classify(batch, registry_dir=registry, work_dir=tmp_path / "work", classifier=fake)
    assert first == second
    assert calls["n"] == 1  # the classifier ran once — the stage is a cache
    written = json.loads((tmp_path / "work" / batch / "classify.json").read_text(encoding="utf-8"))
    assert written["a.jpg"]["kind"] == "photo"
    assert list(written["a.jpg"]) == ["kind", "confidences"]  # the wire record, key order included


def test_classify_page_reads_the_models_kind(tmp_path: Path) -> None:
    """The page's kind is the vision model's reading of the image; a malformed
    or out-of-vocabulary answer fails loudly rather than becoming a routing
    guess (the classifier decides what gets transcribed)."""
    image = tmp_path / "p.png"
    image.write_bytes(b"\x89PNG fake bytes")

    def good(request: object, timeout: float | None = None) -> _BytesResponse:
        return _BytesResponse(_completion('{"kind": "photo", "confidence": 0.93}'))

    result = classify_page(image, urlopen=good)
    assert result.kind == "photo"
    assert result.confidences["photo"] == 0.93

    def unknown_kind(request: object, timeout: float | None = None) -> _BytesResponse:
        return _BytesResponse(_completion('{"kind": "map", "confidence": 0.5}'))

    with pytest.raises(VlmError):
        classify_page(image, urlopen=unknown_kind)

    def garbage(request: object, timeout: float | None = None) -> _BytesResponse:
        return _BytesResponse(_completion("I could not classify this page"))

    with pytest.raises(VlmError):
        classify_page(image, urlopen=garbage)
