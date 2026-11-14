"""The review sessions — the repository both the store and a change expose.

TECHSPEC/08 §19.4: `store.reviews` reads the session, its transcript and its
decisions; `change.reviews` writes them inside the change. The session's
event carries the old attempts (reasoning replaced by content shas); the
projection writes the session row and replaces its ordinal rows.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from typing import TYPE_CHECKING

from loft.live.content import ContentStore
from loft.live.errors import Conflict, NotFound, StaleVersion
from loft.live.person_row import RowPosition
from loft.live.review_row import (
    ReviewDecisionRow,
    ReviewMessageRow,
    ReviewProjection,
    ReviewRow,
    ReviewSessionRow,
    session_from_payload,
    session_payload,
    session_with_thinking,
)
from tools.records import Session

if TYPE_CHECKING:
    from loft.live.change import Change


class Reviews:
    """The review-session collection: read through the store, write through a change."""

    def __init__(self, connection: sqlite3.Connection, content: ContentStore, change: Change | None = None) -> None:
        self.connection = connection
        self.content_store = content
        self.projection = ReviewProjection(connection)
        self.change = change

    # -- reads -------------------------------------------------------------

    def get(self, session_id: str) -> ReviewSessionRow | None:
        return self.projection.get(session_id)

    def require(self, session_id: str) -> ReviewSessionRow:
        session = self.get(session_id)
        if session is None:
            raise NotFound(f"no review session {session_id}")
        return session

    def messages(self, session_id: str) -> tuple[ReviewMessageRow, ...]:
        return self.projection.messages(session_id)

    def decisions(self, session_id: str) -> tuple[ReviewDecisionRow, ...]:
        return self.projection.decisions(session_id)

    def thinking(self, session_id: str, ordinal: int) -> bytes | None:
        sha = self.projection.thinking_sha(session_id, ordinal)
        return None if sha is None else self.content_store.get(sha)

    def session(self, session_id: str) -> Session | None:
        """The archive's Session — the latest event's state, thinking text
        restored from the content store."""
        row = self.connection.execute(
            """SELECT payload FROM events
               WHERE entity_kind = 'review_session' AND entity_id = ?
               ORDER BY seq DESC LIMIT 1""",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        session, thinking = session_from_payload(json.loads(row["payload"]))
        return session_with_thinking(session, thinking, self.content_store)

    def session_ids(self) -> tuple[str, ...]:
        """Every session id in its create order — the imports table's order."""
        rows = self.connection.execute(
            """SELECT t.session_id FROM review_sessions t
               LEFT JOIN (SELECT entity_id, MIN(seq) AS first_seq FROM events
                          WHERE entity_kind = 'review_session' GROUP BY entity_id) e
                 ON e.entity_id = t.session_id
               ORDER BY COALESCE(e.first_seq, 0), t.session_id"""
        ).fetchall()
        return tuple(str(row["session_id"]) for row in rows)

    # -- writes ------------------------------------------------------------

    def save(self, session: Session, *, base: int | None = None) -> Session:
        """Write a create (base None) or a supersede, version-checked."""
        change = self.change
        if change is None:
            raise Conflict("reviews.save needs a change")
        current = self.get(session.id)
        if base is None:
            if current is not None:
                raise Conflict(f"review session {session.id} exists")
            event_type = "created"
            version = 1
        else:
            if current is None:
                raise NotFound(f"no review session {session.id}")
            if current.version != base:
                raise StaleVersion(current=current, base=base)
            event_type = "superseded"
            version = base + 1
        thinking: dict[str, str] = {}
        for attempt_index, attempt in enumerate(session.attempts):
            for message_index, message in enumerate(attempt.messages):
                if message.thinking:
                    thinking[ReviewRow.thinking_key(attempt_index, message_index)] = change.content.put(
                        message.thinking.encode("utf-8"), mime="text/plain"
                    )
        payload = session_payload(session, thinking)
        event = change.append(
            entity_kind="review_session",
            entity_id=session.id,
            event_type=event_type,
            entity_version=version,
            payload=payload,
        )
        saved = replace(session, version=version)
        self.projection.write(
            ReviewRow.build(saved, thinking),
            RowPosition(
                version=version,
                event_no=event["event_no"],
                event_seq=event["seq"],
                updated_at=event["recorded_at"],
            ),
            base=base,
        )
        return saved
