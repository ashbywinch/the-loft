"""The reconciler's plan: the missing stages, computed from the artefacts.

The markers are the truth, so the plan is a pure filesystem question — these
tests build a batch's stage artefacts by hand and assert exactly which stages
the reconciler would run, and why. No model, no images.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

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


def _read_page(work: Path, batch: str, corrected: str = "") -> None:
    """A read row page: classification, orientation, the text, the reading and
    its grouping — the state a correction arrives on top of."""
    _artefact(
        work,
        batch,
        "classify.json",
        json.dumps({"p1.jpg": {"kind": "handwriting", "confidences": {"handwriting": 0.9}}}),
    )
    _artefact(work, batch, "oriented/p1.jpg", "upright")
    _artefact(work, batch, "ocr-guess/p1.txt", "text")
    _artefact(
        work,
        batch,
        "ocr-guess/p1.rows.json",
        json.dumps({"page": "p1.jpg", "width": 10, "height": 10, "revision": 1, "corrected": corrected, "lines": []}),
    )
    _artefact(work, batch, "ocr-guess/boundaries.json", "[]")


def _drawn(work: Path, batch: str, lines: list) -> None:
    _artefact(work, batch, "ocr-guess/p1.row-adjustments.json", json.dumps({"lines": lines}))


def test_a_corrected_page_awaits_a_re_read(tmp_path: Path) -> None:
    """The drawn lines outdate the reading, and the read marker is the draft
    read's own receipt — so the plan must compare the reading's correction sha
    with the file's, or a correction is never read back."""
    work = tmp_path / "work"
    record = _record(work)
    _read_page(work, record.batch_id)
    _drawn(work, record.batch_id, [[[0.1, 0.1], [0.9, 0.1]]])
    plan = plan_for(record, work)
    assert plan.stages == ("read",)
    assert "re-read" in plan.reasons[0]


def test_a_reading_that_carries_the_drawn_lines_is_current(tmp_path: Path) -> None:
    work = tmp_path / "work"
    record = _record(work)
    _read_page(work, record.batch_id)
    _drawn(work, record.batch_id, [[[0.1, 0.1], [0.9, 0.1]]])
    drawn = work / record.batch_id / "ocr-guess" / "p1.row-adjustments.json"
    drawn_sha = hashlib.sha256(drawn.read_bytes()).hexdigest()
    _read_page(work, record.batch_id, corrected=drawn_sha)
    assert plan_for(record, work).stages == ()


def test_an_empty_correction_is_not_a_re_read(tmp_path: Path) -> None:
    """ "Rows are right" records the check with nothing to read again."""
    work = tmp_path / "work"
    record = _record(work)
    _read_page(work, record.batch_id)
    _drawn(work, record.batch_id, [])
    assert plan_for(record, work).stages == ()


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

    def refuse(_system: str, _user: str) -> str:
        raise RuntimeError("the boundary call refused")

    reconciler = Reconciler(paths, write_line=lambda line: None, client=refuse)
    with pytest.raises(RuntimeError, match="refused"):  # the stage's own failure, journalled
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


def test_the_reconciler_runs_only_the_gap(tmp_path: Path) -> None:
    """The reconciler completes exactly the missing stage: a batch that is
    classified and read but not grouped makes one boundary call and no page
    read; a batch with nothing missing calls neither seam."""
    paths = LoftPaths(
        scan_area=tmp_path / "scans",
        registry_dir=tmp_path / "registry",
        work_dir=tmp_path / "work",
        archive_dir=tmp_path / "archive",
    )
    record = _record(paths.work_dir)
    batch = record.batch_id
    Image.new("RGB", (10, 12), "white").save(record.path / "p1.jpg")  # the grouping measures a real page
    _artefact(
        paths.work_dir,
        batch,
        "classify.json",
        json.dumps({"p1.jpg": {"kind": "printed", "confidences": {"printed": 0.9}}}),
    )
    _artefact(paths.work_dir, batch, "ocr-guess/p1.printed.json", "{}")
    _artefact(paths.work_dir, batch, "ocr-guess/p1.txt", "READ ALREADY")
    reads: list[Path] = []
    boundaries: list[tuple[str, str]] = []

    def vision(image: Path) -> Any:
        reads.append(image)
        raise AssertionError("the page is already read: the reconciler must not pay for it again")

    def chat(system: str, user: str) -> str:
        boundaries.append((system, user))
        return json.dumps(
            {"pages": [{"page": "p1.jpg", "text": "READ ALREADY", "starts_document": True, "ends_document": True}]}
        )

    reconciler = Reconciler(paths, write_line=lambda line: None, client=chat, printed=vision)
    plan = reconciler.run(record)
    assert plan.stages == ("group",)
    assert reads == []  # the read is current: the vision seam was never called
    assert len(boundaries) == 1
    assert (paths.work_dir / batch / "ocr-guess" / "boundaries.json").is_file()
