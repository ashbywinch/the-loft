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

import os
import socket
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pipeline.adopt import IMAGE_EXTENSIONS, register_adopted
from pipeline.adoption_result import AdoptionResult
from pipeline.api.sync import BatchReadings, pages_pending
from pipeline.batch_failure import BatchFailure
from pipeline.batch_record import STATUS_PENDING, STATUS_PROCESSING, BatchRecord
from pipeline.chain import process
from pipeline.registry import list_batches, set_status
from pipeline.sweep_report import SweepReport
from tools.loft_paths import LoftPaths

DEFAULT_PATHS = LoftPaths()  # the install's locations; a caller passes its own for a scratch tree


def _has_pages(folder: Path) -> bool:
    """Whether the folder holds a page image (the adoption's own extension
    set, so a folder adoption would refuse is not offered to it)."""
    return any(path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS for path in folder.rglob("*"))


def _pid_alive(pid: int) -> bool:
    """Whether a process with this pid exists — the liveness check for a pass
    stamped on this host. PermissionError means it exists and is not ours."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Worker:
    """The batch processor: notice the scan area's piles, requeue a dead
    pass's batch, run the queue.

    `paths` is the whole of where it reads and writes; `run_batch` is the one
    seam that starts the chain's machine pass, so a test replaces the pass
    (a model and real images) without faking anything else."""

    # a pass on ANOTHER host is given this long before it is presumed dead;
    # on this host the pass's own pid decides (a killed pass cannot reset its
    # own record, and a real pass can outlive any grace)
    stale_after_seconds = 6 * 60 * 60

    def __init__(
        self,
        paths: LoftPaths = DEFAULT_PATHS,
        *,
        client: Callable[[str, str], str] | None = None,
        write_line: Callable[[str], None] = print,
        stale_after: float | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.paths = paths
        self.client = client
        self.write_line = write_line
        self._stale_after = self.stale_after_seconds if stale_after is None else stale_after
        self._now = now or (lambda: datetime.now(UTC))
        self._host = socket.gethostname()

    def sweep(self) -> SweepReport:
        """One pass: register the scan area's piles, requeue a dead pass's
        batch, then run the queue."""
        adoptions = self.pickup()
        requeued = self.requeue_dead()
        processed, failed = self.run_pending()
        return SweepReport(adoptions=adoptions, processed=processed, failed=failed, requeued=requeued)

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

    def requeue_dead(self) -> tuple[str, ...]:
        """Put a batch whose processing pass is gone back in the queue.

        A pass that RAISES resets its own record; one that is killed (the
        terminal closed, a power cut) leaves `processing`, and the queue —
        which is the status — never looks at it again. A record stamped older
        than the grace period is dead; a record with no stamp predates the
        stamping and is dead by definition. `review` is never touched: it may
        be a person's work in progress."""
        requeued: list[str] = []
        now = self._now()
        for record in list_batches(self.paths.registry_dir):
            if record.status != STATUS_PROCESSING or self._pass_alive(record, now):
                continue
            _ = set_status(record.batch_id, STATUS_PENDING, self.paths.registry_dir)
            self.write_line(f"requeue: {record.batch_id} — its pass is gone; back in the queue")
            requeued.append(record.batch_id)
        return tuple(requeued)

    def requeue(self, batch_id: str) -> BatchRecord:
        """Put one batch back in the queue, whatever it was doing — the
        explicit re-entry for a batch a person has finished with (a legacy
        `review` from before the rows stage) or one a crash left behind."""
        record = set_status(batch_id, STATUS_PENDING, self.paths.registry_dir)
        self.write_line(f"requeue: {record.batch_id} — back in the queue")
        return record

    def _pass_alive(self, record: BatchRecord, now: datetime) -> bool:
        """Whether the record's processing pass may still be running.

        On this host the pass's own process decides: a pid that is gone is a
        dead pass, however recent the stamp (a killed pass cannot reset its
        own record, and a real pass can outlive any grace). A pass stamped on
        another host — or with no host, from before the stamp — is judged by
        the grace period, since its pid means nothing here."""
        if not record.started_at:
            return False  # no stamp: no live pass wrote it
        if record.started_host == self._host:
            return bool(record.started_pid) and _pid_alive(record.started_pid)
        try:
            started = datetime.fromisoformat(record.started_at)
        except ValueError:
            return False  # an unreadable stamp is no evidence of a live pass
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        return (now - started).total_seconds() < self._stale_after

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
