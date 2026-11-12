"""The reconciler: what a batch still needs, and only that.

The machine stages are idempotent and their artefacts are their own markers, so
"what does this batch need?" is a question the filesystem answers.
`pipeline/stage_table.py` owns the stage order and the gap checks; this module
turns them into the operator's two operations for one batch: `plan_batch`
(report the gap) and `run` (complete it, journalling each outcome).

This module has no loop of its own: the triggers are `Worker.watch`
(`pipeline/worker.py`). A filesystem change under `work/`, the registry or the
scan area maps to the batch it concerns and `Reconciler.run` is called then (a
batch already in flight is skipped — the self-write suppression: the
reconciler's own writes do not feed back into it); a periodic resync calls it
for every batch, so a missed event, a restart or a stage whose marker was lost
is corrected. Planning is a handful of `stat`s per page — no model call — so
the resync is cheap.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline.batch_record import BatchRecord
from pipeline.chain import BatchRun
from pipeline.registry import list_batches, load_batch
from pipeline.stage_table import EngineView, StageInputs, plan_stages, run_plan
from tools.loft_paths import LoftPaths

__all__ = ["Plan", "Reconciler", "plan_for"]


@dataclass(frozen=True)
class Plan:
    """What one batch needs: the stages, and one reason line per stage."""

    batch_id: str
    stages: tuple[str, ...]
    reasons: tuple[str, ...]


def plan_for(record: BatchRecord, work_dir: Path) -> Plan:
    """The batch's gap, from the one stage table (never calls a model)."""
    gaps = plan_stages(EngineView.of(record, work_dir))
    return Plan(record.batch_id, tuple(spec.name for spec, _ in gaps), tuple(reason for _, reason in gaps))


class _RunJournal:
    """One batch run's log lines and journal entries — the callbacks the stage
    loop calls, not closures over the run's locals."""

    def __init__(self, reconciler: Reconciler, batch_id: str) -> None:
        self.reconciler = reconciler
        self.batch_id = batch_id
        self.done: list[str] = []

    def announce(self, name: str, reason: str) -> None:
        self.reconciler.write_line(f"  {reason}")
        self.reconciler._journal(self.batch_id, {"stage": name, "action": "run", "reason": reason})

    def finished(self, name: str, duration_ms: int) -> None:
        self.done.append(name)
        self.reconciler._journal(self.batch_id, {"stage": name, "action": "done", "duration_ms": duration_ms})


class Reconciler:
    """Plan one batch from its artefacts, then run the gap.

    ``write_line`` is the operator's log (one line per decision); the same
    events are appended to the batch's journal (``work/<batch>/events.jsonl``),
    the durable record of what ran and why."""

    def __init__(
        self,
        paths: LoftPaths,
        *,
        write_line: Callable[[str], None] = print,
        client: Callable[[str, str], str] | None = None,
        printed: Callable[[Path], Any] | None = None,
    ) -> None:
        self.paths = paths
        self.write_line = write_line
        self.client = client
        self.printed = printed  # the vision read's seam (page → (text, answer))

    # ---- planning -------------------------------------------------------
    def plan(self) -> list[Plan]:
        """Every batch's gap, the registry being the list of batches."""
        return [plan_for(record, self.paths.work_dir) for record in list_batches(self.paths.registry_dir)]

    def plan_batch(self, record: BatchRecord) -> Plan:
        """The stages this batch still needs, with the reason for each. Never
        writes and never calls a model."""
        return plan_for(record, self.paths.work_dir)

    # ---- running --------------------------------------------------------
    def run(self, record: BatchRecord) -> Plan:
        """Run the batch's missing stages, in order, logging each one. Nothing
        is retried: a failure is journalled and raised to the caller, which
        decides when the batch is looked at again (an event or a resync)."""
        plan = self.plan_batch(record)
        if not plan.stages:
            self.write_line(f"reconcile: {record.batch_id} — nothing to do")
            return plan
        self.write_line(f"reconcile: {record.batch_id} — running {', '.join(plan.stages)}")
        run = BatchRun(
            record.batch_id,
            work_dir=self.paths.work_dir,
            registry_dir=self.paths.registry_dir,
            archive_dir=self.paths.archive_dir,
        )
        run.update_status(record, BatchRecord.STATUS_PROCESSING)  # stamps the pass (pid, host, time)
        started = datetime.now(UTC)
        log = _RunJournal(self, record.batch_id)
        try:
            _ = run_plan(
                run,
                record,
                inputs=StageInputs(client=self.client, printed=self.printed),
                on_stage=log.announce,
                on_done=log.finished,
            )
        except Exception as exc:
            self._journal(
                record.batch_id,
                {
                    "stage": plan.stages[len(log.done)] if len(log.done) < len(plan.stages) else "reconcile",
                    "action": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            raise
        run.update_status(load_batch(record.batch_id, self.paths.registry_dir), BatchRecord.STATUS_REVIEW)
        took_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
        self.write_line(f"reconcile: {record.batch_id} — {', '.join(log.done)} done in {took_ms} ms")
        self._journal(record.batch_id, {"action": "reconciled", "stages": log.done, "duration_ms": took_ms})
        return Plan(record.batch_id, tuple(log.done), plan.reasons[: len(log.done)])

    def _journal(self, batch_id: str, event: dict[str, Any]) -> None:
        """Append one event to the batch's journal — the durable log of what
        ran, when, and why (the markers stay the truth; the journal is the
        record of decisions)."""
        path = self.paths.work_dir / batch_id / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"ts": datetime.now(UTC).isoformat(timespec="seconds"), **event}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
