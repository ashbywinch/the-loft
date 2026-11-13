"""A5 — import `imports.json` and its review sessions (TECHSPEC/11).

The latest imports table is read once: each session becomes one event whose
payload carries the old attempts (the reasoning replaced by content shas),
and the projection writes the session, its transcript and its decisions. A
re-run skips a session the store holds; a dry run writes nothing; the
verified backup marker is required.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from pathlib import Path

from loft.live.backup import check_marker
from loft.live.errors import LiveError
from loft.live.protocols import ItemStore
from loft.live.review_row import ReviewRow, ReviewRows
from loft.live.reviews import Reviews
from loft.live.store import LiveStore
from tools.archive import Archive
from tools.records import ImportsTable, Session
from tools.store import DiskStore


class ReviewImportError(LiveError):
    """A review session could not be imported."""


@dataclass(frozen=True)
class PlannedReview:
    """One session ready to import and its expected counts."""

    session: Session
    thinking: dict[str, bytes]

    @property
    def counts(self) -> dict[str, int]:
        messages = sum(len(attempt.messages) for attempt in self.session.attempts)
        decisions = sum(len(attempt.decisions) for attempt in self.session.attempts)
        return {
            "attempts": len(self.session.attempts),
            "messages": messages,
            "decisions": decisions,
            "thinking": len(self.thinking),
        }


@dataclass(frozen=True)
class ReviewReport:
    """What the import did (or would do) — counts, skips, operations, result."""

    counts: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    per_session: dict[str, dict[str, int]] = field(default_factory=dict)
    operations: tuple[str, ...] = ()
    dry_run: bool = False
    mismatches: tuple[str, ...] = ()


class ReviewImport:
    """The review import's vocabulary."""

    COUNT_KEYS: tuple[str, ...] = ("sessions", "messages", "decisions", "thinking")


def _latest(archive_root: Path) -> ImportsTable:
    table = Archive(DiskStore(archive_root)).get_identity("imports")
    if table is None:
        return ImportsTable(imports=())
    if not isinstance(table, ImportsTable):
        raise ReviewImportError(f"the imports identity table is {type(table).__name__}")
    return table


def _thinking_bytes(session: Session) -> dict[str, bytes]:
    thinking: dict[str, bytes] = {}
    for attempt_index, attempt in enumerate(session.attempts):
        for message_index, message in enumerate(attempt.messages):
            if message.thinking:
                thinking[ReviewRow.thinking_key(attempt_index, message_index)] = message.thinking.encode("utf-8")
    return thinking


def _plan(store: ItemStore, table: ImportsTable) -> tuple[list[PlannedReview], dict[str, int]]:
    plans: list[PlannedReview] = []
    skipped = {"sessions": 0}
    for session in table.imports:
        if store.reviews.get(session.id) is not None:
            skipped["sessions"] += 1
            continue
        plans.append(PlannedReview(session=session, thinking=_thinking_bytes(session)))
    return plans, skipped


def _counts(plans: list[PlannedReview]) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    counts = {key: 0 for key in ReviewImport.COUNT_KEYS}
    per_session: dict[str, dict[str, int]] = {}
    for plan in plans:
        session_counts = plan.counts
        per_session[plan.session.id] = session_counts
        counts["sessions"] += 1
        counts["messages"] += session_counts["messages"]
        counts["decisions"] += session_counts["decisions"]
        counts["thinking"] += session_counts["thinking"]
    return counts, per_session


def _sha_map(plan: PlannedReview) -> dict[str, str]:
    return {key: hashlib.sha256(data).hexdigest() for key, data in plan.thinking.items()}


def _normal_rows(rows: ReviewRows) -> ReviewRows:
    """The rows without their projection position — the compare's shape."""
    return ReviewRows(
        session=replace(rows.session, version=0),
        messages=tuple(replace(message, event_seq=0) for message in rows.messages),
        decisions=tuple(replace(decision, event_seq=0) for decision in rows.decisions),
    )


def _compare(store: Reviews, plans: list[PlannedReview]) -> tuple[str, ...]:
    mismatches: list[str] = []
    for plan in plans:
        expected = _normal_rows(ReviewRow.build(plan.session, _sha_map(plan)))
        stored = store.get(plan.session.id)
        if stored is None:
            mismatches.append(f"review session {plan.session.id} is missing after import")
            continue
        actual = ReviewRows(
            session=replace(stored, version=0),
            messages=tuple(replace(message, event_seq=0) for message in store.messages(plan.session.id)),
            decisions=tuple(replace(decision, event_seq=0) for decision in store.decisions(plan.session.id)),
        )
        if actual != expected:
            mismatches.append(f"review session {plan.session.id} differs from the imported record")
        for key, data in plan.thinking.items():
            attempt, message = (int(part) for part in key.split(":"))
            ordinal = _ordinal(plan.session, attempt, message)
            if store.thinking(plan.session.id, ordinal) != data:
                mismatches.append(f"review session {plan.session.id} message {ordinal} thinking differs")
    return tuple(mismatches)


def _ordinal(session: Session, attempt_index: int, message_index: int) -> int:
    """The message's flattened ordinal — the transcript's one ordering."""
    return sum(len(attempt.messages) for attempt in session.attempts[:attempt_index]) + message_index + 1


def import_reviews(
    store: LiveStore,
    archive_root: Path,
    *,
    backup_marker: Path,
    dry_run: bool = False,
) -> ReviewReport:
    """Import the latest imports table's sessions, messages and decisions."""
    check_marker(backup_marker)
    plans, skipped = _plan(store, _latest(archive_root))
    return _apply(store, plans, skipped, dry_run=dry_run)


def sync_reviews(store: ItemStore, archive: Archive) -> ReviewReport:
    """Catch the DB up with the old imports table — the review flip's opening
    import (B3). A session the store holds is skipped, so a newer DB record
    is never regressed; the backup marker guards the first migration only."""
    table = archive.get_identity("imports")
    plans, skipped = _plan(store, table if isinstance(table, ImportsTable) else ImportsTable(imports=()))
    return _apply(store, plans, skipped)


def _apply(
    store: ItemStore, plans: list[PlannedReview], skipped: dict[str, int], *, dry_run: bool = False
) -> ReviewReport:
    counts, per_session = _counts(plans)
    operations = tuple(f"review {plan.session.id}" for plan in plans)
    if dry_run:
        return ReviewReport(
            counts=counts,
            skipped=skipped,
            per_session=per_session,
            operations=operations,
            dry_run=True,
        )
    if plans:
        with store.change(actor="import", note="review sessions") as change:
            for plan in plans:
                change.reviews.save(plan.session)
    return ReviewReport(
        counts=counts,
        skipped=skipped,
        per_session=per_session,
        operations=operations,
        dry_run=False,
        mismatches=_compare(store.reviews, plans),
    )
