"""The engine stages, once: each stage's gap check and its runner, in order.

Two callers used to hold the order — the chain's full pass and the reconciler's
gap runner — and a stage added to one could be forgotten in the other. This
module is the order: `plan_stages(view)` says what is missing and why, and
`run_plan` runs the missing stages, re-planning after each one (the
classification decides the read, so a re-plan after `classify` is the rule, not
a special case).

The gap check is pure: it reads the artefacts and returns a reason, or None
when the stage is current. The runner is the stage's own code, called on the
`BatchRun` that owns the batch's paths.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from pipeline.artefacts import BatchArtefacts
from pipeline.batch_record import BatchRecord
from pipeline.classify import PageKinds
from pipeline.registry import load_batch

if TYPE_CHECKING:  # the runner is duck-typed: BatchRun supplies it at runtime
    from pipeline.chain import BatchRun


@dataclass(frozen=True)
class EngineView:
    """One batch as the stages see it: its artefacts, pages and categories."""

    artefacts: BatchArtefacts
    folder: Path
    pages: tuple[str, ...]
    classify: dict[str, Any]

    @classmethod
    def of(cls, record: BatchRecord, work_dir: Path) -> EngineView:
        artefacts = BatchArtefacts(work_dir, record.batch_id)
        return cls(artefacts, record.path, tuple(sorted(record.pages)), classification_of(artefacts))

    def fresh(self, record: BatchRecord) -> EngineView:
        """The view after a stage ran (the classification may have changed)."""
        return EngineView.of(record, self.artefacts.work_dir)

    def text_pages(self) -> list[str]:
        """The pages whose category carries writing to read."""
        return [
            name
            for name in self.pages
            if name in self.classify and PageKinds.category_of(self.classify[name]) in PageKinds.TEXT_KINDS
        ]

    def row_pages(self) -> list[str]:
        """The text pages the row pipeline reads (they need an upright first)."""
        return [name for name in self.text_pages() if PageKinds.read_route(self.classify[name]) == "rows"]

    def classify_gap(self) -> str | None:
        """The classification's gap: a page with no record, or a pre-category one."""
        unclassified = [name for name in self.pages if name not in self.classify]
        legacy = [
            name
            for name in self.pages
            if name in self.classify and self.classify[name].get("kind") in PageKinds.LEGACY_KINDS
        ]
        if unclassified:
            return f"classify: {len(unclassified)} page(s) have no category, e.g. {unclassified[0]!r}"
        if legacy:
            return f"classify: {len(legacy)} page(s) carry the old category, e.g. {legacy[0]!r}"
        return None

    def orient_gap(self) -> str | None:
        """A direct or structured read reads the page image itself: only the row
        pipeline needs the page turned upright first."""
        unoriented = [name for name in self.row_pages() if not self.artefacts.oriented(name).is_file()]
        if not unoriented:
            return None
        return f"orient: {len(unoriented)} page(s) are not oriented, e.g. {unoriented[0]!r}"

    def read_gap(self) -> str | None:
        unread = [
            name
            for name in self.text_pages()
            if not self.artefacts.is_read(name, PageKinds.read_route(self.classify[name]))
        ]
        if unread:
            return f"read: {len(unread)} page(s) have no text, e.g. {unread[0]!r}"
        stale = [name for name in self.row_pages() if self.correction_pending(name)]
        if stale:
            return f"read: {len(stale)} corrected page(s) await a re-read, e.g. {stale[0]!r}"
        return None

    def correction_pending(self, page: str) -> bool:
        """Does the page's reading predate its drawn lines?

        The read marker is the draft read's own receipt, so the marker rule
        cannot see a correction: the reading names the drawn-lines sha it was
        built from (`RowsReading.corrected`), and the read stage re-reads the
        page when the file's sha differs. An empty correction ("rows are
        right") is never a re-read; an unreadable one is the read stage's own
        error to raise."""
        adjustments = self.artefacts.adjustments(page)
        if not adjustments.is_file():
            return False
        try:
            lines = json.loads(adjustments.read_text(encoding="utf-8")).get("lines") or []
        except (ValueError, AttributeError):
            return True
        if not lines:
            return False
        reading = self.artefacts.marker(page, "rows")
        if not reading.is_file():
            return True
        try:
            corrected = str(json.loads(reading.read_text(encoding="utf-8")).get("corrected") or "")
        except (ValueError, AttributeError):
            return True
        return corrected != hashlib.sha256(adjustments.read_bytes()).hexdigest()

    def group_gap(self) -> str | None:
        """A photograph-only pile has no writing to group a document around."""
        if not self.text_pages():
            return None
        boundaries = _boundaries(self.artefacts)
        if boundaries is not None and not any(entry.get("provisional") for entry in boundaries):
            return None  # grouped (an empty list is a grouped pile with no documents)
        return "group: no grouped boundaries.json — the pile's documents are not grouped"

    def stale(self) -> list[str]:
        """The pages whose classification is missing or pre-category."""
        return [
            name
            for name in self.pages
            if name not in self.classify or self.classify[name].get("kind") in PageKinds.LEGACY_KINDS
        ]


@dataclass(frozen=True)
class StageInputs:
    """What a runner needs besides the batch and its view."""

    client: Callable[[str, str], str] | None = None
    printed: Callable[[Path], tuple[str, Any]] | None = None


@dataclass(frozen=True)
class StageContext:
    """Everything a stage does, with the batch, its view and the call seams.

    Each runner is a method here: the same three values every time, so the
    stage's act and the values it acts on are one thing."""

    batch: BatchRun
    view: EngineView
    inputs: StageInputs

    def classify(self) -> None:
        self.batch.classify_pages(
            [self.view.folder / name for name in self.view.pages],
            reclassify=self.view.stale(),
        )

    def orient(self) -> None:
        self.batch.orient_pages(self.view.row_pages(), self.view.folder)

    def read(self) -> None:
        classification = self.batch.classify_pages([self.view.folder / name for name in self.view.pages])
        self.batch.read_all(classification, _printed=self.inputs.printed)

    def group(self) -> None:
        classification = self.batch.classify_pages([self.view.folder / name for name in self.view.pages])
        self.batch.write_boundaries(
            classification,
            load_batch(self.batch.batch_id, self.batch.registry_dir),
            self.inputs.client,
        )


@dataclass(frozen=True)
class StageSpec:
    ALL: ClassVar[tuple[StageSpec, ...]] = ()

    """One engine stage: its name, its gap check, and its runner."""

    name: str
    missing: Callable[[EngineView], str | None]
    run: Callable[[StageContext], None]


StageSpec.ALL = (
    StageSpec("classify", EngineView.classify_gap, StageContext.classify),
    StageSpec("orient", EngineView.orient_gap, StageContext.orient),
    StageSpec("read", EngineView.read_gap, StageContext.read),
    StageSpec("group", EngineView.group_gap, StageContext.group),
)


def plan_stages(view: EngineView) -> list[tuple[StageSpec, str]]:
    """The stages this batch still needs, with the reason for each — in order."""
    gaps: list[tuple[StageSpec, str]] = []
    for spec in StageSpec.ALL:
        reason = spec.missing(view)
        if reason is not None:
            gaps.append((spec, reason))
    return gaps


def run_plan(
    batch: BatchRun,
    record: BatchRecord,
    *,
    inputs: StageInputs | None = None,
    on_stage: Callable[[str, str], None] | None = None,
    on_done: Callable[[str, int], None] | None = None,
) -> tuple[str, ...]:
    """Run the batch's missing stages, one at a time, re-planning after each.

    `on_stage(name, reason)` is the operator's log seam. Returns the stages
    that ran, in order."""
    inputs = inputs or StageInputs()
    view = EngineView.of(record, batch.work_dir)
    ran: list[str] = []
    while True:
        gaps = plan_stages(view)
        if not gaps:
            return tuple(ran)
        spec, reason = gaps[0]
        if on_stage is not None:
            on_stage(spec.name, reason)
        started = time.monotonic()
        spec.run(StageContext(batch, view, inputs))
        if on_done is not None:
            on_done(spec.name, int((time.monotonic() - started) * 1000))
        ran.append(spec.name)
        view = view.fresh(record)


def _boundaries(artefacts: BatchArtefacts) -> list[dict[str, Any]] | None:
    """The batch's boundaries entries, or None when the file is absent or
    unreadable (an empty list is a grouped pile that holds no documents)."""
    if not artefacts.boundaries.is_file():
        return None
    try:
        entries = json.loads(artefacts.boundaries.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else None


def classification_of(artefacts: BatchArtefacts) -> dict[str, Any]:
    """The batch's classify.json, or an empty mapping when none exists or it
    is unreadable."""
    if not artefacts.classify.is_file():
        return {}
    try:
        entries = json.loads(artefacts.classify.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return entries if isinstance(entries, dict) else {}
