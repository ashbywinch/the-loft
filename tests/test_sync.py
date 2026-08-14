"""Tests for the two-app sync contract: the confirmation shape, the
frontend's catch-up outbox, the draft payloads, and the shared
confirmation write path — all deterministic, no models, no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.registry import RegistryError
from tools.sync import Outbox, draft_payloads, record_confirmation, validate_confirmation


def _confirmation(**overrides: object) -> dict[str, object]:
    return {
        "batch_id": "adopt-0001",
        "doc_index": 1,
        "pages": ["p1.jpg", "p2.jpg"],
        "text": "Chère Maman.",
        "status": "confirmed",
        "confirmed_at": "2026-08-14T00:00:00Z",
        **overrides,
    }


def test_validate_confirmation_accepts_the_shape() -> None:
    assert validate_confirmation(_confirmation())["status"] == "confirmed"


def test_validate_confirmation_rejects_bad_shapes() -> None:
    with pytest.raises(ValueError, match="missing fields"):
        validate_confirmation({"pages": []})
    with pytest.raises(ValueError, match="status"):
        validate_confirmation(_confirmation(status="maybe"))
    with pytest.raises(ValueError, match="pages"):
        validate_confirmation(_confirmation(pages=[]))


def test_outbox_catch_up_add_pending_mark_received(tmp_path: Path) -> None:
    outbox = Outbox(tmp_path / "outbox")
    item_id = outbox.add(_confirmation())
    pending = outbox.pending()
    assert [(i, p["status"]) for i, p in pending] == [(item_id, "confirmed")]
    outbox.mark_received([item_id])
    assert outbox.pending() == []
    assert list(tmp_path.glob("outbox/*.tmp")) == []  # atomic writes leave no temp siblings


def test_outbox_mark_received_rejects_traversal(tmp_path: Path) -> None:
    outbox = Outbox(tmp_path / "outbox")
    (tmp_path / "outbox").mkdir()
    victim = tmp_path / "victim.json"
    victim.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid outbox item id"):
        outbox.mark_received(["../../victim"])
    assert victim.exists()  # nothing outside the outbox was touched


def test_draft_payloads_serves_the_review_surface(tmp_path: Path) -> None:
    guess = tmp_path / "adopt-0001" / "ocr-guess"
    guess.mkdir(parents=True)
    (guess / "p1.txt").write_text("Chère Maman.", encoding="utf-8")
    (guess / "boundaries.json").write_text(
        json.dumps([{"pages": ["p1.jpg"], "greeting": "Chère Maman.", "signoff": None}]),
        encoding="utf-8",
    )
    drafts = draft_payloads("adopt-0001", tmp_path)
    assert drafts[0]["texts"]["p1.jpg"] == "Chère Maman."
    assert drafts[0]["greeting"] == "Chère Maman."


def _registered_batch(tmp_path: Path, registry: Path) -> None:
    registry.mkdir()
    (registry / "adopt-0001.json").write_text(
        json.dumps({"batch_id": "adopt-0001", "path": str(tmp_path), "status": "review", "boundaries": None}),
        encoding="utf-8",
    )


def test_record_confirmation_writes_and_updates_the_registry(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    _registered_batch(tmp_path, registry)
    document = {"pages": ["p1.jpg"]}

    record_confirmation("adopt-0001", 1, document, "Chère Maman.", work_dir=tmp_path, registry_dir=registry)
    record_confirmation("adopt-0001", 2, {"pages": ["p2.jpg"]}, None, work_dir=tmp_path, registry_dir=registry)

    record = json.loads((registry / "adopt-0001.json").read_text(encoding="utf-8"))
    assert record["boundaries"] == [
        {"pages": ["p1.jpg"], "status": "confirmed"},
        {"pages": ["p2.jpg"], "status": "rejected"},
    ]
    assert (tmp_path / "adopt-0001" / "ocr-confirmed" / "doc-01.txt").read_text(encoding="utf-8") == "Chère Maman."
    assert not (tmp_path / "adopt-0001" / "ocr-confirmed" / "doc-02.txt").exists()  # rejected leaves no text


def test_record_confirmation_replaces_by_pages(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    _registered_batch(tmp_path, registry)
    record_confirmation("adopt-0001", 1, {"pages": ["p1.jpg"]}, "v1", work_dir=tmp_path, registry_dir=registry)
    record_confirmation("adopt-0001", 1, {"pages": ["p1.jpg"]}, "v2", work_dir=tmp_path, registry_dir=registry)
    record = json.loads((registry / "adopt-0001.json").read_text(encoding="utf-8"))
    assert len(record["boundaries"]) == 1  # same pages → replaced, not duplicated


def test_record_confirmation_rejects_unknown_batch_without_writing(tmp_path: Path) -> None:
    # a confirmation for a batch the backend never adopted must neither
    # fabricate a record nor leave a review-output file — RegistryError -> 4xx
    registry = tmp_path / "registry"
    registry.mkdir()
    with pytest.raises(RegistryError):
        record_confirmation("adopt-9999", 1, {"pages": ["p1.jpg"]}, "text", work_dir=tmp_path, registry_dir=registry)
    assert not (tmp_path / "adopt-9999" / "ocr-confirmed").exists()  # nothing written for the unknown batch


def test_draft_payloads_rejects_unsafe_page_names(tmp_path: Path) -> None:
    # page names from boundaries.json become path segments — a separator or ".."
    # must fail closed (defense-in-depth; the pipeline writes only plain names)
    guess = tmp_path / "adopt-0001" / "ocr-guess"
    guess.mkdir(parents=True)
    (guess / "boundaries.json").write_text(json.dumps([{"pages": ["../etc/passwd"]}]), encoding="utf-8")
    with pytest.raises(ValueError):
        draft_payloads("adopt-0001", tmp_path)
    (guess / "boundaries.json").write_text(json.dumps([{"pages": [".."]}]), encoding="utf-8")
    with pytest.raises(ValueError):
        draft_payloads("adopt-0001", tmp_path)
