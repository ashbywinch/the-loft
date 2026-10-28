"""The scan pickup (UR3): a dropped pile runs the machine stages with no
manual step, and its pages arrive in the "Check the rows" queue.

The worker's own decisions are what these pin — which piles it registers,
which batches it runs, and that one batch's failure never stops the queue.
The chain's pass itself (a model, real images) is not re-run here: the seam
that starts it is the worker's, so the tests subclass `Worker.run_batch`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import override

import pytest

from pipeline.registry import load_batch
from pipeline.worker import Worker
from tools.loft_paths import LoftPaths


def _pile(scan_area: Path, name: str = "scan-20261027-1200", pages: int = 2) -> Path:
    """A scanner's finished job folder — the scan area holds only complete piles."""
    folder = scan_area / name
    folder.mkdir(parents=True)
    for number in range(1, pages + 1):
        _ = (folder / f"{name}-{number:02d}.jpg").write_bytes(b"\xff\xd8 page")
    return folder


def _record(registry_dir: Path, batch_id: str, status: str, arrived_at: str) -> None:
    """A registry record, as an adoption or a scan leaves one."""
    registry_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "batch_id": batch_id,
        "path": str(registry_dir.parent / "scans" / batch_id),
        "status": status,
        "arrived_at": arrived_at,
        "pages": {"p1.jpg": "hash-1"},
        "fingerprint": ["hash-1"],
    }
    _ = (registry_dir / f"{batch_id}.json").write_text(json.dumps(record), encoding="utf-8")


class _Ran(Worker):
    """A worker whose machine pass is the test's: it records the batch ids it
    was asked to run, and can be told to fail one."""

    def __init__(
        self,
        paths: LoftPaths,
        *,
        write_line: Callable[[str], None] = print,
        fail: tuple[str, ...] = (),
    ) -> None:
        super().__init__(paths, write_line=write_line)
        self.ran: list[str] = []
        self._fail = fail

    @override
    def run_batch(self, batch_id: str) -> None:
        self.ran.append(batch_id)
        if batch_id in self._fail:
            raise RuntimeError("the model refused the page")


def _paths(tmp_path: Path) -> LoftPaths:
    """One scratch tree: the scan area, the registry, the work stages and the
    archive, all under the test's directory."""
    return LoftPaths(
        scan_area=tmp_path / "scans",
        registry_dir=tmp_path / "registry",
        work_dir=tmp_path / "work",
        archive_dir=tmp_path / "archive",
    )


def _worker(tmp_path: Path, *, fail: tuple[str, ...] = ()) -> _Ran:
    return _Ran(_paths(tmp_path), write_line=lambda line: None, fail=fail)


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


def test_only_a_pending_batch_is_run(tmp_path: Path) -> None:
    """The registry's status IS the queue: a reviewed batch is not re-run."""
    registry = tmp_path / "registry"
    _record(registry, "batch-reviewed", "review", "2026-10-27T13:00:00+00:00")
    _record(registry, "batch-pending", "pending", "2026-10-27T12:00:00+00:00")
    worker = _worker(tmp_path)
    report = worker.sweep()
    assert worker.ran == ["batch-pending"]
    assert report.processed == ("batch-pending",)


def test_a_failing_batch_is_reported_and_the_queue_continues(tmp_path: Path) -> None:
    """One batch's failure is named in the report and never holds the rest."""
    registry = tmp_path / "registry"
    _record(registry, "batch-a", "pending", "2026-10-27T12:00:00+00:00")
    _record(registry, "batch-b", "pending", "2026-10-27T11:00:00+00:00")
    worker = _worker(tmp_path, fail=("batch-a",))
    report = worker.sweep()
    assert worker.ran == ["batch-a", "batch-b"]  # newest first, both attempted
    assert [failure.batch_id for failure in report.failed] == ["batch-a"]
    assert report.failed[0].reason == "RuntimeError: the model refused the page"
    assert report.processed == ("batch-b",)


def test_watch_sweeps_until_interrupted(tmp_path: Path) -> None:
    """The long-running mode: a sweep, the interval's wait, a sweep — the wait
    is the seam, so the test drives it without a clock."""
    worker = _worker(tmp_path)
    _pile(tmp_path / "scans")
    waits: list[float] = []

    def _sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 3:
            raise RuntimeError("stop the watch loop")

    with pytest.raises(RuntimeError, match="stop the watch loop"):
        worker.watch(30, _sleep=_sleep)
    assert waits == [30, 30, 30]
    assert len(worker.ran) == 3  # the third sweep ran before its wait
