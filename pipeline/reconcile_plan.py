"""One batch's gap: the stages its artefacts say it still needs.

Planning is pure filesystem inspection — no model call, no write — so it is
cheap enough to run per batch on every event and on a periodic resync. The
markers are the truth: a stage is missing when its artefact is.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.batch_record import BatchRecord
from pipeline.classify import LEGACY_KINDS, category_of, read_route
from pipeline.store import PipelineStore

# the machine stages a batch may still need, in dependency order
STAGES = ("classify", "orient", "read", "group")
# the categories whose pages carry writing to read
TEXT_KINDS = ("printed", "handwriting", "postcard_face", "form")


@dataclass(frozen=True)
class Plan:
    """What one batch needs: the stages, and one reason line per stage."""

    batch_id: str
    stages: tuple[str, ...]
    reasons: tuple[str, ...]


class GapFinder:
    """One batch's gap: the pages, their classification, and the artefacts.

    The plan's checks share that state, so they are methods of one value —
    each returns its stage and reason, or nothing when the stage is current."""

    def __init__(self, record: BatchRecord, work_dir: Path) -> None:
        self.work = work_dir / record.batch_id
        self.pages = sorted(record.pages)
        self.classify = classification_of(work_dir, record.batch_id)

    def gaps(self) -> list[tuple[str, str]]:
        return [*self._classification_gap(), *self._orient_gap(), *self._read_gap(), *self._group_gap()]

    def _classification_gap(self) -> list[tuple[str, str]]:
        """Pages with no record, or one from before the category vocabulary —
        which cannot route a read, so it is classified again."""
        unclassified = [name for name in self.pages if name not in self.classify]
        legacy = [
            name for name in self.pages if name in self.classify and self.classify[name].get("kind") in LEGACY_KINDS
        ]
        gaps: list[tuple[str, str]] = []
        if unclassified:
            gaps.append(
                ("classify", f"classify: {len(unclassified)} page(s) have no category, e.g. {unclassified[0]!r}")
            )
        if legacy:
            gaps.append(("classify", f"classify: {len(legacy)} page(s) carry the old category, e.g. {legacy[0]!r}"))
        return gaps

    def _writing_pages(self) -> list[str]:
        """The pages whose category carries writing to read."""
        return [name for name in self.pages if name in self.classify and category_of(self.classify[name]) in TEXT_KINDS]

    def _orient_gap(self) -> list[tuple[str, str]]:
        """A direct or structured read reads the page image itself: only the
        row pipeline needs the page turned upright first."""
        row_pages = [name for name in self._writing_pages() if read_route(self.classify[name]) == "rows"]
        unoriented = [name for name in row_pages if not (self.work / "oriented" / name).is_file()]
        if not unoriented:
            return []
        return [("orient", f"orient: {len(unoriented)} page(s) are not oriented, e.g. {unoriented[0]!r}")]

    def _read_gap(self) -> list[tuple[str, str]]:
        unread = [name for name in self._writing_pages() if not _page_read(self.work, name, self.classify[name])]
        if not unread:
            return []
        return [("read", f"read: {len(unread)} page(s) have no text, e.g. {unread[0]!r}")]

    def _group_gap(self) -> list[tuple[str, str]]:
        if (self.work / "ocr-guess" / "boundaries.json").is_file():
            return []
        return [("group", "group: no boundaries.json — the pile's documents are not grouped")]


def missing_stages(record: BatchRecord, work_dir: Path) -> Plan:
    """The stages this batch still needs, with the reason for each. Never
    writes and never calls a model."""
    gaps = GapFinder(record, work_dir).gaps()
    return Plan(record.batch_id, tuple(stage for stage, _ in gaps), tuple(reason for _, reason in gaps))


def classification_of(work_dir: Path, batch_id: str) -> dict[str, Any]:
    """The batch's classify.json, or an empty mapping when none exists."""
    store = PipelineStore(work_dir)
    rel = f"{batch_id}/classify.json"
    if not store.exists(rel):
        return {}
    try:
        entries = json.loads(store.read_latest(rel))
    except (ValueError, OSError):
        return {}
    return entries if isinstance(entries, dict) else {}


def _page_read(work: Path, page: str, entry: dict[str, Any]) -> bool:
    """Whether a page's own text exists — the read's completion marker per
    category (the direct read's marker, or the row read's files)."""
    stem = Path(page).stem
    route = read_route(entry)
    text = (work / "ocr-guess" / f"{stem}.txt").is_file()
    if route == "direct":
        return text and (work / "ocr-guess" / f"{stem}.printed.json").is_file()
    if route == "structured":
        return text and (work / "ocr-guess" / f"{stem}.structured.json").is_file()
    if route == "rows":
        return text and (work / "ocr-guess" / f"{stem}.rows.json").is_file()
    return True  # no writing to read
