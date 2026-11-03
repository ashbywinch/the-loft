"""The scan pickup (UR3): a dropped pile runs the machine stages with no
manual step, and its pages arrive in the "Check the rows" queue.

The worker's own decisions are what these pin — which piles it registers,
which batches it runs, and that one batch's failure never stops the queue.
The chain's pass itself (a model, real images) is not re-run here: the seam
that starts it is the worker's, so the tests subclass `Worker.run_batch`.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import override

import pytest
from watchfiles import Change

from pipeline.batch_record import BatchRecord
from pipeline.reconcile import Plan, Reconciler
from pipeline.registry import RegistryError, load_batch
from pipeline.worker import Worker
from tools.loft_paths import LoftPaths


def _pile(scan_area: Path, name: str = "scan-20261027-1200", pages: int = 2) -> Path:
    """A scanner's finished job folder — the scan area holds only complete piles."""
    folder = scan_area / name
    folder.mkdir(parents=True)
    for number in range(1, pages + 1):
        _ = (folder / f"{name}-{number:02d}.jpg").write_bytes(b"\xff\xd8 page")
    return folder


def _record(
    registry_dir: Path,
    batch_id: str,
    status: str,
    arrived_at: str,
    started_at: str = "",
    started_pid: int = 0,
    started_host: str = "",
) -> None:
    """A registry record, as an adoption, a scan, or a running pass leaves one
    (the stamp fields only when the caller passes them)."""
    registry_dir.mkdir(parents=True, exist_ok=True)
    record: dict[str, object] = {
        "batch_id": batch_id,
        "path": str(registry_dir.parent / "scans" / batch_id),
        "status": status,
        "arrived_at": arrived_at,
        "pages": {"p1.jpg": "hash-1"},
        "fingerprint": ["hash-1"],
    }
    if started_at:
        record["started_at"] = started_at
    if started_pid:
        record["started_pid"] = started_pid
    if started_host:
        record["started_host"] = started_host
    _ = (registry_dir / f"{batch_id}.json").write_text(json.dumps(record), encoding="utf-8")


class _RecordingReconciler(Reconciler):
    """The reconciler with only the model-run stage replaced: planning stays
    real, so these tests pin which batches the sweep finds work in."""

    def __init__(self, paths: LoftPaths, *, fail: tuple[str, ...] = ()) -> None:
        super().__init__(paths, write_line=lambda line: None)
        self.ran: list[str] = []
        self._fail = fail

    @override
    def run(self, record: BatchRecord) -> Plan:
        plan = self.plan_batch(record)
        if plan.stages:
            self.ran.append(record.batch_id)
        if record.batch_id in self._fail:
            raise RuntimeError("the model refused the page")
        return plan


def _paths(tmp_path: Path) -> LoftPaths:
    """One scratch tree: the scan area, the registry, the work stages and the
    archive, all under the test's directory."""
    return LoftPaths(
        scan_area=tmp_path / "scans",
        registry_dir=tmp_path / "registry",
        work_dir=tmp_path / "work",
        archive_dir=tmp_path / "archive",
    )


def _worker(tmp_path: Path, *, fail: tuple[str, ...] = (), now: Callable[[], datetime] | None = None) -> Worker:
    paths = _paths(tmp_path)
    return Worker(
        paths,
        write_line=lambda line: None,
        now=now,
        reconciler=_RecordingReconciler(paths, fail=fail),
    )


def _ran(worker: Worker) -> list[str]:
    """The batches the test's reconciler was asked to run."""
    assert isinstance(worker.reconciler, _RecordingReconciler)
    return worker.reconciler.ran


def test_a_dropped_pile_is_registered_and_run(tmp_path: Path) -> None:
    """UR3: the pile appears in the scan area and nothing else is done — the
    sweep registers it and runs its batch."""
    worker = _worker(tmp_path)
    pile = _pile(tmp_path / "scans")
    report = worker.sweep()
    assert [outcome.outcome for outcome in report.adoptions] == ["new"]
    assert len(report.processed) == 1
    record = load_batch(report.processed[0], tmp_path / "registry")
    assert record.status == "pending"
    assert record.path == pile
    assert sorted(record.pages) == ["scan-20261027-1200-01.jpg", "scan-20261027-1200-02.jpg"]
    assert report.failed == ()


def test_an_already_registered_pile_is_a_no_op(tmp_path: Path) -> None:
    """A sweep is safe to repeat: the pile hashes to the record it already has,
    and no second record appears."""
    worker = _worker(tmp_path)
    _pile(tmp_path / "scans")
    _ = worker.sweep()
    second = worker.sweep()
    assert [outcome.outcome for outcome in second.adoptions] == ["already-registered"]
    assert len(list((tmp_path / "registry").glob("*.json"))) == 1


def test_a_folder_with_no_pages_is_not_a_pile(tmp_path: Path) -> None:
    notes = tmp_path / "scans" / "notes"
    notes.mkdir(parents=True)
    _ = (notes / "readme.txt").write_text("not a scan", encoding="utf-8")
    report = _worker(tmp_path).sweep()
    assert report.adoptions == ()
    assert report.processed == ()


def _complete_batch(tmp_path: Path, batch_id: str, status: str, arrived_at: str) -> None:
    """A batch whose machine stages are all done — a page classified, oriented
    and read, and its pile grouped — as the artefacts leave it."""
    registry = tmp_path / "registry"
    _record(registry, batch_id, status, arrived_at)
    work = tmp_path / "work" / batch_id
    (work / "oriented").mkdir(parents=True)
    (work / "ocr-guess").mkdir(parents=True)
    _ = (work / "classify.json").write_text(
        json.dumps({"p1.jpg": {"kind": "photograph", "confidences": {"photograph": 0.9}}}), encoding="utf-8"
    )
    _ = (work / "ocr-guess" / "boundaries.json").write_text("[]", encoding="utf-8")


def test_a_batch_with_no_gap_is_left_alone(tmp_path: Path) -> None:
    """A finished batch is not re-run: planning sees no missing stage."""
    _complete_batch(tmp_path, "batch-done", "review", "2026-10-27T13:00:00+00:00")
    worker = _worker(tmp_path)
    report = worker.sweep()
    assert _ran(worker) == []
    assert report.processed == ()


def test_a_reviewed_batch_with_a_gap_is_reconciled(tmp_path: Path) -> None:
    """The Gazette case: a `review` batch whose grouping never ran is not in
    the pending queue, and the gap is what the reconciler notices."""
    registry = tmp_path / "registry"
    _record(registry, "batch-review", "review", "2026-10-27T13:00:00+00:00")
    work = tmp_path / "work" / "batch-review"
    (work / "oriented").mkdir(parents=True)
    (work / "ocr-guess").mkdir(parents=True)
    _ = (work / "classify.json").write_text(
        json.dumps({"p1.jpg": {"kind": "printed", "confidences": {"printed": 0.9}}}), encoding="utf-8"
    )
    _ = (work / "ocr-guess" / "p1.printed.json").write_text("{}", encoding="utf-8")
    _ = (work / "ocr-guess" / "p1.txt").write_text("TEXT", encoding="utf-8")
    worker = _worker(tmp_path)
    report = worker.sweep()
    assert _ran(worker) == ["batch-review"]  # group is missing
    assert report.processed == ("batch-review",)


def test_a_failing_batch_is_reported_and_the_queue_continues(tmp_path: Path) -> None:
    """One batch's failure is named in the report and never holds the rest."""
    registry = tmp_path / "registry"
    _record(registry, "batch-a", "pending", "2026-10-27T12:00:00+00:00")
    _record(registry, "batch-b", "pending", "2026-10-27T11:00:00+00:00")
    worker = _worker(tmp_path, fail=("batch-a",))
    report = worker.sweep()
    assert _ran(worker) == ["batch-a", "batch-b"]  # newest first, both attempted
    assert [failure.batch_id for failure in report.failed] == ["batch-a"]
    assert report.failed[0].reason == "RuntimeError: the model refused the page"
    assert report.processed == ("batch-b",)


def test_a_changed_path_names_its_batch(tmp_path: Path) -> None:
    """The watch turns a file change into the batch it concerns: a work-tree
    path, a registry record (base or a versioned copy), and the scan area."""
    paths = _paths(tmp_path)
    batch = "adopt-20261027-120000"
    _record(paths.registry_dir, batch, "review", "2026-10-27T12:00:00+00:00")
    (paths.work_dir / batch / "ocr-guess").mkdir(parents=True)
    (paths.scan_area / "pile").mkdir(parents=True)
    worker = Worker(paths, write_line=lambda line: None)
    changes = {
        (Change.added, str(paths.work_dir / batch / "ocr-guess" / "p1.txt")),
        (Change.modified, str(paths.registry_dir / f"{batch}-2.json")),
        (Change.added, str(paths.scan_area / "pile" / "p1.jpg")),
    }
    batches, scan_touched = worker._batch_ids(changes)
    assert batches == {batch}
    assert scan_touched is True


NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def test_a_dead_processing_batch_goes_back_in_the_queue(tmp_path: Path) -> None:
    """A pass that is killed leaves the record `importing` and the queue never
    looks at it again. A record with no stamp was written before the stamping
    existed — no live pass wrote it — so the sweep returns it."""
    registry = tmp_path / "registry"
    _record(registry, "batch-stuck", "importing", "2026-08-13T20:10:04+00:00")
    worker = _worker(tmp_path, now=lambda: NOW)

    report = worker.sweep()

    assert report.requeued == ("batch-stuck",)
    assert _ran(worker) == ["batch-stuck"]


def test_a_stale_processing_stamp_is_dead(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    _record(registry, "batch-stuck", "importing", "2026-10-29T00:00:00+00:00", started_at="2026-10-29T00:00:00+00:00")
    worker = _worker(tmp_path, now=lambda: NOW)  # 12 h later — past the grace

    assert worker.sweep().requeued == ("batch-stuck",)


def test_a_live_processing_pass_is_left_alone(tmp_path: Path) -> None:
    """A pass stamped inside the grace period may still be running: the sweep
    must not start a second one over it."""
    registry = tmp_path / "registry"
    _record(registry, "batch-live", "importing", "2026-10-29T11:30:00+00:00", started_at="2026-10-29T11:30:00+00:00")
    worker = _worker(tmp_path, now=lambda: NOW)

    report = worker.sweep()

    assert report.requeued == ()
    assert _ran(worker) == []


def test_a_killed_pass_on_this_host_is_requeued_at_once(tmp_path: Path) -> None:
    """The pid decides on the host that ran the pass: a killed pass is dead
    however recent its stamp — a 40-minute read killed mid-run must not look
    live for six hours."""
    registry = tmp_path / "registry"
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    _record(
        registry,
        "batch-killed",
        "importing",
        "2026-10-29T11:59:00+00:00",
        started_at="2026-10-29T11:59:00+00:00",
        started_pid=dead.pid,
        started_host=socket.gethostname(),
    )
    worker = _worker(tmp_path, now=lambda: NOW)

    assert worker.sweep().requeued == ("batch-killed",)
    assert _ran(worker) == ["batch-killed"]


def test_a_live_pass_on_this_host_is_left_alone(tmp_path: Path) -> None:
    """A pass whose process is alive is running, whatever its age: the sweep
    must not start a second one over it."""
    registry = tmp_path / "registry"
    _record(
        registry,
        "batch-live",
        "importing",
        "2026-10-29T11:00:00+00:00",
        started_at="2026-10-29T11:00:00+00:00",
        started_pid=os.getpid(),
        started_host=socket.gethostname(),
    )
    worker = _worker(tmp_path, now=lambda: NOW)  # an hour in — past the grace

    assert worker.sweep().requeued == ()
    assert _ran(worker) == []


def test_a_reviewed_batch_is_never_requeued_automatically(tmp_path: Path) -> None:
    """`review` may be a person mid-gate: only an explicit requeue touches it."""
    registry = tmp_path / "registry"
    _record(registry, "batch-reviewed", "review", "2026-08-13T20:10:24+00:00")

    assert _worker(tmp_path, now=lambda: NOW).sweep().requeued == ()


def test_requeue_puts_a_reviewed_batch_back(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    _record(registry, "batch-legacy", "review", "2026-08-13T20:10:24+00:00")
    worker = _worker(tmp_path, now=lambda: NOW)

    worker.requeue("batch-legacy")
    assert load_batch("batch-legacy", registry).status == "pending"
    report = worker.sweep()
    assert report.requeued == ()  # already pending, not demoted
    assert _ran(worker) == ["batch-legacy"]


def test_requeue_an_unknown_batch_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="no registry record"):
        _worker(tmp_path, now=lambda: NOW).requeue("batch-ghost")


def test_a_folder_of_piles_is_adopted_as_its_piles(tmp_path: Path) -> None:
    """An inbox folder (no images of its own) is not a pile: its child folders
    are, one batch each."""
    inbox = tmp_path / "scans" / "inbox"
    for name in ("pile-a", "pile-b"):
        folder = inbox / name
        folder.mkdir(parents=True)
        (folder / f"{name}-01.jpg").write_bytes(f"page {name}".encode())  # distinct content: a different pile
    worker = _worker(tmp_path)
    report = worker.sweep()
    records = [load_batch(result.path.stem, tmp_path / "registry") for result in report.adoptions]
    assert sorted(str(record.path) for record in records) == sorted([str(inbox / "pile-a"), str(inbox / "pile-b")])


def test_a_pile_whose_scans_sit_in_a_subfolder_is_one_pile(tmp_path: Path) -> None:
    """A folder with no images of its own but scans in a subfolder is adopted
    at the folder that holds them — one pile, not one per level."""
    dated = tmp_path / "scans" / "dad" / "2026-08-17"
    dated.mkdir(parents=True)
    (dated / "scan-01.jpg").write_bytes(b"\xff\xd8 page")
    (dated / "scan-02.jpg").write_bytes(b"\xff\xd8 page")
    worker = _worker(tmp_path)
    report = worker.sweep()
    assert len(report.adoptions) == 1
    record = load_batch(report.adoptions[0].path.stem, tmp_path / "registry")
    assert record.path == dated
    assert sorted(record.pages) == ["scan-01.jpg", "scan-02.jpg"]
