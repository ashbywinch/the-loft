"""The worker: the machine stages, driven without a person (UR3).

`docs/PRD/pipeline-stages-spec.md` UR3 and `docs/PLAN/pipeline-stages-plan.md`:
scans arrive, the backend notices them itself, and the machine stages run —
orient, marks, words, draft rows — so a page lands in the "Check the rows"
queue with no manual step. Two facts make this a sweep rather than a
pipeline of its own:

- **the registry's records ARE the queue**: a record is work while its
  status is `pending` (a fresh scan, a fresh adoption, or a pile whose
  content changed);
- **a page's status is derived** from its stage artefacts
  (`BatchReadings.page_status`), never stored, so this module decides only
  what to RUN — it writes no status field that could go stale.

Every step is idempotent: adoption hashes a pile it has already seen and
the chain skips a page whose stage artefacts exist. A sweep is therefore
safe to repeat, and a crash costs at most the batch in flight.

The worker is a separate process from the API server (the plan's seam): the
server never contacts it, and it never serves HTTP.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from pipeline.adopt import IMAGE_EXTENSIONS, register_adopted
from pipeline.adoption_result import AdoptionResult
from pipeline.api.sync import BatchReadings, pages_pending
from pipeline.batch_failure import BatchFailure
from pipeline.batch_record import STATUS_PENDING
from pipeline.chain import process
from pipeline.registry import list_batches
from pipeline.sweep_report import SweepReport
from tools.loft_paths import LoftPaths

DEFAULT_PATHS = LoftPaths()  # the install's locations; a caller passes its own for a scratch tree


def _has_pages(folder: Path) -> bool:
    """Whether the folder holds a page image (the adoption's own extension
    set, so a folder adoption would refuse is not offered to it)."""
    return any(path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS for path in folder.rglob("*"))


class Worker:
    """The batch processor: notice the scan area's piles, run the queue.

    `paths` is the whole of where it reads and writes; `run_batch` is the one
    seam that starts the chain's machine pass, so a test replaces the pass
    (a model and real images) without faking anything else."""

    def __init__(
        self,
        paths: LoftPaths = DEFAULT_PATHS,
        *,
        client: Callable[[str, str], str] | None = None,
        write_line: Callable[[str], None] = print,
    ) -> None:
        self.paths = paths
        self.client = client
        self.write_line = write_line

    def sweep(self) -> SweepReport:
        """One pass: register the scan area's piles, then run the queue."""
        adoptions = self.pickup()
        processed, failed = self.run_pending()
        return SweepReport(adoptions=adoptions, processed=processed, failed=failed)

    def pickup(self) -> tuple[AdoptionResult, ...]:
        """Register every complete pile in the scan area.

        A pile is a directory holding page images. The scan tools publish a
        finished job atomically (the job directory appears whole), so a
        directory seen here is a pile the scanner finished — the scan area
        never holds a partial one. Adoption is in place and by content
        fingerprint: a pile already registered is a no-op, and one whose
        pages changed comes back as `content-changed`."""
        if not self.paths.scan_area.is_dir():
            return ()
        adopted: list[AdoptionResult] = []
        for folder in sorted(path for path in self.paths.scan_area.iterdir() if path.is_dir()):
            if not _has_pages(folder):
                continue
            result = register_adopted(folder, registry_dir=self.paths.registry_dir, work_dir=self.paths.work_dir)
            if result.outcome != "already-registered":
                self.write_line(f"pickup: {folder.name} — {result.outcome}")
            adopted.append(result)
        return tuple(adopted)

    def run_pending(self) -> tuple[tuple[str, ...], tuple[BatchFailure, ...]]:
        """Run every pending batch; one failure never holds the queue.

        A failed batch keeps its `pending` status (nothing here writes the
        record), so the next sweep retries it: the failure is reported every
        pass until it is fixed, never dropped."""
        processed: list[str] = []
        failed: list[BatchFailure] = []
        for record in list_batches(self.paths.registry_dir):
            if record.status != STATUS_PENDING:
                continue
            # a boundary catch, blast radius ONE batch: the chain raises for
            # model transport, a scan folder that moved, and a corrupt stage
            # artefact alike, and none of them may hold the piles behind it
            try:
                self.run_batch(record.batch_id)
            # lucidlint: ignore broad-except the boundary is one batch's pass, reported whole
            except Exception as exc:
                failure = BatchFailure(record.batch_id, f"{type(exc).__name__}: {exc}")
                failed.append(failure)
                self.write_line(f"worker: {record.batch_id} FAILED — {failure.reason}")
                continue
            processed.append(record.batch_id)
            waiting = len(pages_pending(BatchReadings(self.paths.work_dir, record.batch_id), list(record.pages)))
            self.write_line(f"worker: {record.batch_id} ran — {waiting} page(s) to check")
        return tuple(processed), tuple(failed)

    def run_batch(self, batch_id: str) -> None:
        """One batch's machine pass — the chain's own entry point, with this
        worker's locations and client. The chain stops where a person takes
        over: the draft rows exist and the page waits on its row check."""
        process(
            batch_id,
            registry_dir=self.paths.registry_dir,
            work_dir=self.paths.work_dir,
            archive_dir=self.paths.archive_dir,
            client=self.client,
        )

    def watch(self, interval: float, *, _sleep: Callable[[float], None] = time.sleep) -> None:
        """The long-running mode: a sweep, the interval's wait, a sweep —
        until interrupted. The wait is this method's seam, so a test drives
        several sweeps without a clock."""
        while True:
            report = self.sweep()
            self.write_line(
                f"worker: {len(report.adoptions)} pile(s) seen, {len(report.processed)} batch(es) ran, "
                f"{len(report.failed)} failed — next sweep in {interval:g}s"
            )
            _sleep(interval)
