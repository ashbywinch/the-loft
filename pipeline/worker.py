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
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from watchfiles import Change, watch

from pipeline.adopt import IMAGE_EXTENSIONS, register_adopted
from pipeline.adoption_result import AdoptionResult
from pipeline.batch_failure import BatchFailure
from pipeline.batch_record import STATUS_PENDING, STATUS_PROCESSING, BatchRecord
from pipeline.reconcile import Reconciler
from pipeline.registry import RegistryError, list_batches, load_batch, set_status
from pipeline.store import VERSION_SUFFIX
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
        self.reconciler = Reconciler(paths, write_line=write_line, client=client)
        self._inflight: set[str] = set()

    def sweep(self) -> SweepReport:
        """One pass: register the scan area's piles, requeue a dead pass's
        batch, then reconcile every batch's missing stages.

        This is the resync: planning is per-page `stat`s, so it is cheap, and
        it is what corrects a missed event, a restart, or a stage whose marker
        was lost. A batch with nothing missing costs nothing."""
        adoptions = self.pickup()
        requeued = self.requeue_dead()
        now = self._now()
        processed: list[str] = []
        failed: list[BatchFailure] = []
        for record in list_batches(self.paths.registry_dir):
            if self._pass_alive(record, now):
                continue  # a live pass holds this batch; a second one would race it
            try:
                plan = self.reconciler.run(record)
            # one batch's failure never holds the queue, and is never retried here
            except Exception as exc:
                self.write_line(f"worker: {record.batch_id} FAILED — {type(exc).__name__}: {exc}")
                failed.append(BatchFailure(record.batch_id, f"{type(exc).__name__}: {exc}"))
                continue
            if plan.stages:
                processed.append(record.batch_id)
        return SweepReport(
            adoptions=adoptions,
            processed=tuple(processed),
            failed=tuple(failed),
            requeued=requeued,
        )

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

    def watch(self, resync: float = 600.0, *, debounce_ms: int = 800) -> None:
        """The long-running mode: a file change is a trigger, a periodic
        resync is the safety net.

        Every change under the scan area, the registry or the work tree maps
        to the batch it concerns; that batch is reconciled then. A batch
        already in flight is skipped — so the reconciler's own writes never
        feed back into it — and the plan only ever contains missing stages. A
        change to the scan area runs the pickup first, so a new pile is
        registered before it is reconciled. A quiet ``resync`` interval is a
        full sweep, which corrects a missed event, a restart or a lost
        marker."""
        roots = (self.paths.scan_area, self.paths.registry_dir, self.paths.work_dir)
        self.write_line(
            f"worker: watching {', '.join(str(root) for root in roots)} — a resync every {resync:g}s (Ctrl-C stops)"
        )
        events = watch(
            *roots,
            debounce=debounce_ms,
            step=int(resync * 1000),
            yield_on_timeout=True,
            rust_timeout=500,
        )
        for changes in events:
            if not changes:
                report = self.sweep()
                self.write_line(
                    f"worker: resync — {len(report.adoptions)} pile(s) seen, "
                    f"{len(report.processed)} batch(es) had work, {len(report.failed)} failed"
                )
                continue
            batch_ids, scan_touched = self._batch_ids(changes)
            if scan_touched:
                new_piles = {
                    result.path.resolve() for result in self.pickup() if result.outcome != "already-registered"
                }
                for record in list_batches(self.paths.registry_dir):
                    if record.path.resolve() in new_piles:
                        batch_ids.add(record.batch_id)
            for batch_id in sorted(batch_ids):
                if batch_id in self._inflight:
                    continue
                failure = self._reconcile_one(batch_id)
                if failure is not None:
                    self.write_line(f"worker: {batch_id} FAILED — {failure}")

    def _reconcile_one(self, batch_id: str) -> str | None:
        """Reconcile one batch from an event, skipping it while it is already
        being run (the self-write suppression). Returns a failure's reason for
        the watch loop to report; None when there was nothing to do or it ran."""
        records = {record.batch_id: record for record in list_batches(self.paths.registry_dir)}
        record = records.get(batch_id)
        if record is None or self._pass_alive(record, self._now()):
            return None  # a batch whose record is gone, or one a live pass already holds
        self._inflight.add(batch_id)
        try:
            _ = self.reconciler.run(record)
        except Exception as exc:  # one batch's failure never holds the queue, and is never retried here
            return f"{type(exc).__name__}: {exc}"
        finally:
            self._inflight.discard(batch_id)
        return None

    def _batch_ids(self, changes: set[tuple[Change, str]]) -> tuple[set[str], bool]:
        """The batches a set of file changes concerns, and whether the scan
        area was touched (a new pile needs the pickup before a batch id
        exists)."""
        batches: set[str] = set()
        scan_touched = False
        scan = self.paths.scan_area.resolve()
        work = self.paths.work_dir.resolve()
        registry = self.paths.registry_dir.resolve()
        for _change, raw in changes:
            path = Path(raw).resolve()
            if path.is_relative_to(work):
                parts = path.relative_to(work).parts
                if parts:
                    batches.add(parts[0])
            elif path.is_relative_to(registry) and path.suffix == ".json":
                batch_id = VERSION_SUFFIX.sub(".json", path.name)[: -len(".json")]
                try:
                    _ = load_batch(batch_id, self.paths.registry_dir)
                except RegistryError:
                    continue
                batches.add(batch_id)
            elif path.is_relative_to(scan):
                scan_touched = True
        return batches, scan_touched
