"""The reconciler: what a batch still needs, and only that.

The machine stages are idempotent and their artefacts are their own markers, so
"what does this batch need?" is a question the filesystem answers: a page whose
`oriented/<page>` is missing needs orientation; one whose reading is missing
needs the read; a batch with no `boundaries.json` needs grouping. The
reconciler asks that question per batch, runs the missing stages, and logs each
decision — it never re-runs a stage whose artefact is current, and never
reprocesses the workspace to find work.

Two triggers, one loop (the controller pattern): a filesystem WATCH turns a
change under `work/`, the registry or the scan area into the batch it concerns
(events are coalesced, and a batch already being run is skipped — that is the
self-write suppression: the reconciler's own writes do not feed back into it);
a periodic RESYNC plans every batch, so a missed event, a restart or a stage
whose marker was lost is corrected. Planning is a handful of `stat`s per page —
no model call — so the resync is cheap.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pipeline.batch_record import STATUS_PROCESSING, STATUS_REVIEW, BatchRecord
from pipeline.chain import BatchRun
from pipeline.classify import LEGACY_KINDS, run_classify
from pipeline.reconcile_plan import Plan, classification_of, missing_stages
from pipeline.registry import list_batches, load_batch
from tools.loft_paths import LoftPaths

__all__ = ["Plan", "Reconciler", "missing_stages"]


class Reconciler:
    """The reconciler's one loop: plan a batch from its artefacts, run the gap.

    ``write_line`` is the operator's log (one line per decision); the same
    events are appended to the batch's journal (``work/<batch>/events.jsonl``),
    the durable record of what ran and why."""

    def __init__(
        self,
        paths: LoftPaths,
        *,
        write_line: Callable[[str], None] = print,
        client: Callable[[str, str], str] | None = None,
    ) -> None:
        self.paths = paths
        self.write_line = write_line
        self.client = client

    # ---- planning -------------------------------------------------------
    def plan(self) -> list[Plan]:
        """Every batch's gap, the registry being the list of batches."""
        return [missing_stages(record, self.paths.work_dir) for record in list_batches(self.paths.registry_dir)]

    def plan_batch(self, record: BatchRecord) -> Plan:
        """The stages this batch still needs, with the reason for each. Never
        writes and never calls a model."""
        return missing_stages(record, self.paths.work_dir)

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
        run.update_status(record, STATUS_PROCESSING)  # stamps the pass (pid, host, time)
        started = datetime.now(UTC)
        if "classify" in plan.stages:
            self._stage(
                record.batch_id,
                "classify",
                plan.reasons[plan.stages.index("classify")],
                lambda: run_classify(
                    record.batch_id,
                    registry_dir=self.paths.registry_dir,
                    work_dir=self.paths.work_dir,
                    reclassify=self._stale_pages(record),
                ),
            )
            # the classification decides the read, so the plan is re-made on the
            # new categories before anything downstream runs
            replanned = missing_stages(record, self.paths.work_dir)
            if replanned.stages != plan.stages:
                self.write_line(f"  replanned after classify: {', '.join(replanned.stages) or 'nothing'}")
                plan = replanned
        classification = run.classify_pages([record.path / name for name in sorted(record.pages)])
        for stage, reason in zip(plan.stages, plan.reasons, strict=True):
            if stage == "classify":
                continue  # done above, on the pages that needed it
            if stage == "orient":
                self._stage(
                    record.batch_id, stage, reason, lambda: run.orient_pages(classification.text_pages, record.path)
                )
            elif stage == "read":
                self._stage(record.batch_id, stage, reason, lambda: run.read_all(classification))
            elif stage == "group":
                self._stage(
                    record.batch_id, stage, reason, lambda: run.write_boundaries(classification, record, self.client)
                )
        run.update_status(load_batch(record.batch_id, self.paths.registry_dir), STATUS_REVIEW)
        took_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
        self.write_line(f"reconcile: {record.batch_id} — {', '.join(plan.stages)} done in {took_ms} ms")
        self._journal(
            record.batch_id,
            {"action": "reconciled", "stages": list(plan.stages), "duration_ms": took_ms},
        )
        return plan

    def _stage(self, batch_id: str, stage: str, reason: str, action: Callable[[], Any]) -> None:
        """Run one stage, logging its reason first and journalling the outcome
        — a failure is journalled with its error and raised, never retried
        here."""
        self.write_line(f"  {reason}")
        started = datetime.now(UTC)
        try:
            _ = action()
        except Exception as exc:
            self._journal(
                batch_id,
                {"stage": stage, "action": "failed", "reason": reason, "error": f"{type(exc).__name__}: {exc}"},
            )
            raise
        took_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
        self._journal(batch_id, {"stage": stage, "action": "done", "reason": reason, "duration_ms": took_ms})

    def _stale_pages(self, record: BatchRecord) -> list[str]:
        """The pages whose classification is missing or carries the old
        vocabulary — the ones a re-run must classify again."""
        current = classification_of(self.paths.work_dir, record.batch_id)
        return [name for name in record.pages if name not in current or current[name].get("kind") in LEGACY_KINDS]

    def _journal(self, batch_id: str, event: dict[str, Any]) -> None:
        """Append one event to the batch's journal — the durable log of what
        ran, when, and why (the markers stay the truth; the journal is the
        record of decisions)."""
        path = self.paths.work_dir / batch_id / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"ts": datetime.now(UTC).isoformat(timespec="seconds"), **event}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
