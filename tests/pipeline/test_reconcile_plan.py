"""The reconciler's plan: the missing stages, computed from the artefacts.

The markers are the truth, so the plan is a pure filesystem question — these
tests build a batch's stage artefacts by hand and assert exactly which stages
the reconciler would run, and why. No model, no images.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import UnidentifiedImageError

from pipeline.batch_record import BatchRecord
from pipeline.reconcile import Reconciler, plan_for
from tools.loft_paths import LoftPaths


def _record(work: Path, pages: tuple[str, ...] = ("p1.jpg",), batch_id: str = "adopt-20260101-000000") -> BatchRecord:
    folder = work.parent / "scans" / batch_id
    folder.mkdir(parents=True, exist_ok=True)
    for page in pages:
        _ = (folder / page).write_bytes(b"\xff\xd8 page")
    return BatchRecord(
        batch_id=batch_id,
        path=folder,
        status="review",
        arrived_at="2026-01-01T00:00:00+00:00",
        pages={page: f"hash-{page}" for page in pages},
        fingerprint=[f"hash-{page}" for page in pages],
    )


def _artefact(work: Path, batch_id: str, rel: str, content: str = "") -> None:
    path = work / batch_id / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(content, encoding="utf-8")


def test_a_complete_batch_needs_nothing(tmp_path: Path) -> None:
    work = tmp_path / "work"
    record = _record(work)
    batch = record.batch_id
    _artefact(
        work,
        batch,
        "classify.json",
        json.dumps({"p1.jpg": {"kind": "handwriting", "confidences": {"handwriting": 0.9}}}),
    )
    _artefact(work, batch, "oriented/p1.jpg", "upright")
    _artefact(work, batch, "ocr-guess/p1.txt", "text")
    _artefact(work, batch, "ocr-guess/p1.rows.json", "{}")
    _artefact(work, batch, "ocr-guess/boundaries.json", "[]")
    plan = plan_for(record, work)
    assert plan.stages == ()
    assert plan.reasons == ()


def test_a_missing_classification_is_the_first_gap(tmp_path: Path) -> None:
    work = tmp_path / "work"
    record = _record(work, pages=("p1.jpg", "p2.jpg"))
    plan = plan_for(record, work)
    assert plan.stages[0] == "classify"
    assert "2 page(s) have no category" in plan.reasons[0]


def test_a_printed_page_needs_no_row_read(tmp_path: Path) -> None:
    work = tmp_path / "work"
    record = _record(work)
    batch = record.batch_id
    _artefact(
        work, batch, "classify.json", json.dumps({"p1.jpg": {"kind": "printed", "confidences": {"printed": 0.9}}})
    )
    _artefact(work, batch, "oriented/p1.jpg", "upright")
    _artefact(work, batch, "ocr-guess/p1.txt", "text")
    _artefact(work, batch, "ocr-guess/p1.printed.json", "{}")
    plan = plan_for(record, work)
    assert plan.stages == ("group",)  # read is done; only the pile's grouping remains


def test_an_old_vocabulary_record_is_reclassified(tmp_path: Path) -> None:
    """A `text` classification cannot route a read (the medium is unknown): the
    reconciler classifies the page again rather than guessing its route."""
    work = tmp_path / "work"
    record = _record(work)
    batch = record.batch_id
    _artefact(work, batch, "classify.json", json.dumps({"p1.jpg": {"kind": "text", "confidences": {"text": 0.9}}}))
    _artefact(work, batch, "oriented/p1.jpg", "upright")
    _artefact(work, batch, "ocr-guess/p1.txt", "text")
    plan = plan_for(record, work)
    assert plan.stages[0] == "classify"
    assert "old category" in plan.reasons[0]


def test_a_direct_read_needs_no_orientation(tmp_path: Path) -> None:
    """A printed page is read from the raw page: orientation is the row
    pipeline's need, not the read's."""
    work = tmp_path / "work"
    record = _record(work)
    batch = record.batch_id
    _artefact(
        work, batch, "classify.json", json.dumps({"p1.jpg": {"kind": "printed", "confidences": {"printed": 0.9}}})
    )
    plan = plan_for(record, work)
    assert "orient" not in plan.stages


def test_missing_grouping_alone_is_one_stage(tmp_path: Path) -> None:
    """A pile that is read but not grouped needs the one stage: grouping."""
    work = tmp_path / "work"
    record = _record(work)
    batch = record.batch_id
    _artefact(
        work, batch, "classify.json", json.dumps({"p1.jpg": {"kind": "printed", "confidences": {"printed": 0.9}}})
    )
    _artefact(work, batch, "ocr-guess/p1.printed.json", "{}")
    _artefact(work, batch, "ocr-guess/p1.txt", "TEXT")
    plan = plan_for(record, work)
    assert plan.stages == ("group",)


def test_a_failing_stage_is_journalled_and_raised(tmp_path: Path) -> None:
    """A stage that cannot run is journalled with its error, and the failure
    reaches the caller — nothing is swallowed and nothing is retried."""
    paths = LoftPaths(
        scan_area=tmp_path / "scans",
        registry_dir=tmp_path / "registry",
        work_dir=tmp_path / "work",
        archive_dir=tmp_path / "archive",
    )
    record = _record(paths.work_dir)
    batch = record.batch_id
    classify = json.dumps({"p1.jpg": {"kind": "printed", "confidences": {"printed": 0.9}}})
    _artefact(paths.work_dir, batch, "classify.json", classify)
    _artefact(paths.work_dir, batch, "ocr-guess/p1.printed.json", "{}")
    _artefact(paths.work_dir, batch, "ocr-guess/p1.txt", "TEXT")
    reconciler = Reconciler(paths, write_line=lambda line: None)
    with pytest.raises(UnidentifiedImageError):  # grouping measures the page; it is not an image
        reconciler.run(record)
    events = [json.loads(line) for line in (paths.work_dir / batch / "events.jsonl").read_text().splitlines()]
    assert events[0]["stage"] == "group" and events[0]["action"] == "run"
    assert events[-1]["action"] == "failed" and "Error" in events[-1]["error"]


def test_a_batch_with_nothing_missing_is_left_alone(tmp_path: Path) -> None:
    """A complete batch logs one line and journals nothing: no work, no write."""
    paths = LoftPaths(
        scan_area=tmp_path / "scans",
        registry_dir=tmp_path / "registry",
        work_dir=tmp_path / "work",
        archive_dir=tmp_path / "archive",
    )
    record = _record(paths.work_dir)
    batch = record.batch_id
    photograph = json.dumps({"p1.jpg": {"kind": "photograph", "confidences": {"photograph": 0.9}}})
    _artefact(paths.work_dir, batch, "classify.json", photograph)
    _artefact(paths.work_dir, batch, "ocr-guess/boundaries.json", "[]")
    lines: list[str] = []
    reconciler = Reconciler(paths, write_line=lines.append)
    plan = reconciler.run(record)
    assert plan.stages == ()
    assert lines == [f"reconcile: {batch} — nothing to do"]
    assert not (paths.work_dir / batch / "events.jsonl").exists()
