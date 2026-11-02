"""The reconciler's plan: the missing stages, computed from the artefacts.

The markers are the truth, so the plan is a pure filesystem question — these
tests build a batch's stage artefacts by hand and assert exactly which stages
the reconciler would run, and why. No model, no images.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.batch_record import BatchRecord
from pipeline.reconcile import Reconciler
from pipeline.reconcile_plan import missing_stages
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
    plan = missing_stages(record, work)
    assert plan.stages == ()
    assert plan.reasons == ()


def test_a_missing_classification_is_the_first_gap(tmp_path: Path) -> None:
    work = tmp_path / "work"
    record = _record(work, pages=("p1.jpg", "p2.jpg"))
    plan = missing_stages(record, work)
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
    plan = missing_stages(record, work)
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
    plan = missing_stages(record, work)
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
    plan = missing_stages(record, work)
    assert "orient" not in plan.stages


def test_missing_grouping_alone_is_one_stage(tmp_path: Path) -> None:
    work = tmp_path / "work"
    record = _record(work)
    batch = record.batch_id
    _artefact(
        work, batch, "classify.json", json.dumps({"p1.jpg": {"kind": "photograph", "confidences": {"photograph": 0.9}}})
    )
    plan = missing_stages(record, work)
    assert plan.stages == ("group",)  # a photograph has nothing to orient or read


def test_a_stage_is_journalled_after_it_runs(tmp_path: Path) -> None:
    """The journal records the OUTCOME: a stage that ran is `done`; one that
    raised is `failed` with its error, and the error still reaches the caller."""
    paths = LoftPaths(
        scan_area=tmp_path / "scans",
        registry_dir=tmp_path / "registry",
        work_dir=tmp_path / "work",
        archive_dir=tmp_path / "archive",
    )
    reconciler = Reconciler(paths, write_line=lambda line: None)
    reconciler._stage("batch", "group", "group: no boundaries.json", lambda: None)
    with pytest.raises(RuntimeError, match="the model refused"):
        reconciler._stage("batch", "read", "read: no text", _refuse)
    events = [json.loads(line) for line in (paths.work_dir / "batch" / "events.jsonl").read_text().splitlines()]
    assert [(event["stage"], event["action"]) for event in events] == [("group", "done"), ("read", "failed")]
    assert events[1]["error"] == "RuntimeError: the model refused"


def _refuse() -> None:
    raise RuntimeError("the model refused")


def test_a_marker_is_the_reads_receipt(tmp_path: Path) -> None:
    """A page whose read marker exists is read, even if the text beside it is
    missing — the marker is written AFTER the text, and the stage skips it, so
    the plan must not demand a re-read (they used to disagree)."""
    work = tmp_path / "work"
    record = _record(work)
    batch = record.batch_id
    _artefact(
        work, batch, "classify.json", json.dumps({"p1.jpg": {"kind": "printed", "confidences": {"printed": 0.9}}})
    )
    _artefact(work, batch, "ocr-guess/p1.printed.json", "{}")  # marker present, text missing
    plan = missing_stages(record, work)
    assert "read" not in plan.stages
