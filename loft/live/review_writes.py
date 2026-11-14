"""The review-state write service — one change per review action (B3).

The archive's session verbs move here: ensure the import session, start a
walk, append a message, record a decision, complete the import. Each opens
exactly one `Change`, so the session event, its projection rows and the
thinking blobs commit together; the read-modify-write happens *inside* the
change, under the store's writer lock (TECHSPEC/08 §19.4).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from loft.live.errors import NotFound
from tools.records import Session

if TYPE_CHECKING:
    from loft.live.protocols import ItemStore


class ReviewWrites:
    """The review session write surface: one change per action."""

    def __init__(self, store: ItemStore) -> None:
        self.store = store

    def session(self, session_id: str) -> Session | None:
        with self.store.lock:
            return self.store.reviews.session(session_id)

    def ensure(self, session: Session, *, actor: str) -> Session:
        """Create the session once; an existing session is a no-op."""
        with self.store.change(actor=actor, note=f"ensure review session {session.id}") as change:
            current = change.reviews.session(session.id)
            if current is not None:
                return current
            return change.reviews.save(session)

    def update(self, session_id: str, mutate: Callable[[Session], Session], *, actor: str) -> Session:
        """Apply one mutation to the session as it stands, in one change."""
        with self.store.change(actor=actor, note=f"update review session {session_id}") as change:
            current = change.reviews.session(session_id)
            row = change.reviews.get(session_id)
            if current is None or row is None:
                raise NotFound(f"no import session {session_id}")
            updated = mutate(current)
            if updated == current:
                return current  # a keep writes nothing — no identical version
            return change.reviews.save(updated, base=row.version)

    def start(self, session_id: str, *, actor: str) -> Session:
        """Start a walk (or continue the unfinished one) and return it."""
        return self.update(session_id, lambda session: session.start_attempt(), actor=actor)

    def refresh(self, *, actor: str) -> int:
        """Complete every pending session when no proposed person remains."""
        with self.store.change(actor=actor, note="refresh the import status") as change:
            if any(person.status == "proposed" for person in change.people.all()):
                return 0
            completed = 0
            for session_id in change.reviews.session_ids():
                session = change.reviews.session(session_id)
                row = change.reviews.get(session_id)
                if session is None or row is None or session.status != "pending":
                    continue
                change.reviews.save(session.completed(), base=row.version)
                completed += 1
            return completed
