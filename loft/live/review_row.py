"""The review-session projection — the session, its messages and its decisions.

TECHSPEC/05 §18.4: `review_sessions` is the conversation's state,
`review_messages` the transcript and `review_decisions` the outcomes. The old
session's attempts flatten into one ordinal sequence each; the decisions map
to the target vocabulary (`review_map`), and the assistant's reasoning is a
content-addressed blob referenced by `thinking_sha`.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, ClassVar

from loft.live.errors import StaleVersion
from loft.live.person_row import RowPosition
from loft.live.review_map import decision_disposition
from tools.records import Session


@dataclass(frozen=True)
class ReviewSessionRow:
    """One review session's current state."""

    session_id: str
    kind: str
    subject_kind: str
    subject_id: str | None
    actor_person_id: str
    status: str
    current_attempt: int | None
    closed_at: str | None
    version: int = 0


@dataclass(frozen=True)
class ReviewMessageRow:
    """One transcript line, in the session's ordinal sequence."""

    session_id: str
    ordinal: int
    role: str
    actor_person_id: str | None
    text: str
    thinking_sha: str | None
    at: str
    event_seq: int = 0


@dataclass(frozen=True)
class ReviewDecisionRow:
    """One reviewer determination, in the session's ordinal sequence."""

    session_id: str
    ordinal: int
    subject_kind: str
    subject_id: str | None
    decision: str
    basis: dict[str, Any] | None
    actor_person_id: str
    at: str
    event_seq: int = 0


@dataclass(frozen=True)
class ReviewRows:
    """One session's projection rows — the session and its two ordinal lists."""

    session: ReviewSessionRow
    messages: tuple[ReviewMessageRow, ...]
    decisions: tuple[ReviewDecisionRow, ...]


class ReviewRow:
    """The review session's row mapping — kind, subject, actor and ordinals."""

    KIND: ClassVar[dict[str, str]] = {"import-review": "import"}
    SUBJECT_KIND: ClassVar[str] = "batch"
    SYSTEM_ACTOR: ClassVar[str] = "import"
    DECISION_SUBJECT: ClassVar[str] = "person"

    @classmethod
    def thinking_key(cls, attempt: int, message: int) -> str:
        return f"{attempt}:{message}"

    @classmethod
    def build(cls, session: Session, thinking: dict[str, str]) -> ReviewRows:
        """Map the old session's attempts to the target rows, in order."""
        messages: list[ReviewMessageRow] = []
        decisions: list[ReviewDecisionRow] = []
        for attempt_index, attempt in enumerate(session.attempts):
            for message_index, message in enumerate(attempt.messages):
                messages.append(
                    ReviewMessageRow(
                        session_id=session.id,
                        ordinal=len(messages) + 1,
                        role=message.role,
                        actor_person_id=None,
                        text=message.text,
                        thinking_sha=thinking.get(cls.thinking_key(attempt_index, message_index)),
                        at=message.when,
                    )
                )
            for decision in attempt.decisions:
                mapped, basis = decision_disposition(decision.decision, decision.basis)
                decisions.append(
                    ReviewDecisionRow(
                        session_id=session.id,
                        ordinal=len(decisions) + 1,
                        subject_kind=cls.DECISION_SUBJECT,
                        subject_id=decision.person_id,
                        decision=mapped,
                        basis=basis,
                        actor_person_id=cls.SYSTEM_ACTOR,
                        at=decision.when,
                    )
                )
        return ReviewRows(
            session=ReviewSessionRow(
                session_id=session.id,
                kind=cls.KIND.get(session.kind, session.kind),
                subject_kind=cls.SUBJECT_KIND,
                subject_id=None,
                actor_person_id=cls.SYSTEM_ACTOR,
                status=session.status,
                current_attempt=cls._current_attempt(session),
                closed_at=cls._closed_at(session),
            ),
            messages=tuple(messages),
            decisions=tuple(decisions),
        )

    @classmethod
    def _current_attempt(cls, session: Session) -> int | None:
        """The attempt in progress, as the target column names it. The old
        session's ``current`` is the next person to review — the review
        queue, which C1's claims carry, not an attempt."""
        attempts = session.attempts
        if session.status == "pending" and attempts and not attempts[-1].finished:
            return len(attempts)
        return None

    @classmethod
    def _closed_at(cls, session: Session) -> str | None:
        """When a finished session last spoke; a pending session is open."""
        if session.status != "reviewed":
            return None
        whens = [
            entry
            for attempt in session.attempts
            for entry in [m.when for m in attempt.messages] + [d.when for d in attempt.decisions]
        ]
        return next((when for when in reversed(whens) if when), None)


class ReviewProjection:
    """One connection's review rows: the reader and the guarded writer."""

    COLUMNS: ClassVar[tuple[str, ...]] = (
        "session_id",
        "kind",
        "subject_kind",
        "subject_id",
        "actor_person_id",
        "status",
        "current_attempt",
        "closed_at",
        "version",
        "event_no",
        "event_seq",
        "updated_at",
    )

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def current_version(self, session_id: str) -> int | None:
        row = self.connection.execute(
            "SELECT version FROM review_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return None if row is None else int(row["version"])

    def get(self, session_id: str) -> ReviewSessionRow | None:
        row = self.connection.execute("SELECT * FROM review_sessions WHERE session_id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        return ReviewSessionRow(
            session_id=row["session_id"],
            kind=row["kind"],
            subject_kind=row["subject_kind"],
            subject_id=row["subject_id"],
            actor_person_id=row["actor_person_id"],
            status=row["status"],
            current_attempt=row["current_attempt"],
            closed_at=row["closed_at"],
            version=row["version"],
        )

    def messages(self, session_id: str) -> tuple[ReviewMessageRow, ...]:
        rows = self.connection.execute(
            """SELECT session_id, ordinal, role, actor_person_id, text, thinking_sha, at, event_seq
               FROM review_messages WHERE session_id = ? ORDER BY ordinal""",
            (session_id,),
        ).fetchall()
        return tuple(
            ReviewMessageRow(
                session_id=row["session_id"],
                ordinal=row["ordinal"],
                role=row["role"],
                actor_person_id=row["actor_person_id"],
                text=row["text"],
                thinking_sha=row["thinking_sha"],
                at=row["at"],
                event_seq=row["event_seq"],
            )
            for row in rows
        )

    def decisions(self, session_id: str) -> tuple[ReviewDecisionRow, ...]:
        rows = self.connection.execute(
            """SELECT session_id, ordinal, subject_kind, subject_id, decision, basis_json,
                      actor_person_id, at, event_seq
               FROM review_decisions WHERE session_id = ? ORDER BY ordinal""",
            (session_id,),
        ).fetchall()
        return tuple(
            ReviewDecisionRow(
                session_id=row["session_id"],
                ordinal=row["ordinal"],
                subject_kind=row["subject_kind"],
                subject_id=row["subject_id"],
                decision=row["decision"],
                basis=json.loads(row["basis_json"]) if row["basis_json"] else None,
                actor_person_id=row["actor_person_id"],
                at=row["at"],
                event_seq=row["event_seq"],
            )
            for row in rows
        )

    def thinking_sha(self, session_id: str, ordinal: int) -> str | None:
        row = self.connection.execute(
            "SELECT thinking_sha FROM review_messages WHERE session_id = ? AND ordinal = ?",
            (session_id, ordinal),
        ).fetchone()
        return None if row is None else row["thinking_sha"]

    def write(self, rows: ReviewRows, position: RowPosition, *, base: int | None) -> None:
        """Upsert the session and replace its transcript and decisions."""
        values = (
            rows.session.session_id,
            rows.session.kind,
            rows.session.subject_kind,
            rows.session.subject_id,
            rows.session.actor_person_id,
            rows.session.status,
            rows.session.current_attempt,
            rows.session.closed_at,
            position.version,
            position.event_no,
            position.event_seq,
            position.updated_at,
        )
        placeholders = ", ".join("?" for _ in values)
        assignments = ", ".join(f"{column} = excluded.{column}" for column in self.COLUMNS if column != "session_id")
        cursor = self.connection.execute(
            f"""INSERT INTO review_sessions ({", ".join(self.COLUMNS)}) VALUES ({placeholders})
                ON CONFLICT (session_id) DO UPDATE SET {assignments}
                WHERE review_sessions.version IS ?""",
            (*values, base),
        )
        if cursor.rowcount == 0:
            raise StaleVersion(current=self.get(rows.session.session_id), base=base)
        self._write_messages(rows.session.session_id, rows.messages, position.event_seq)
        self._write_decisions(rows.session.session_id, rows.decisions, position.event_seq)

    def _write_messages(self, session_id: str, messages: tuple[ReviewMessageRow, ...], event_seq: int) -> None:
        self.connection.execute("DELETE FROM review_messages WHERE session_id = ?", (session_id,))
        for message in messages:
            self.connection.execute(
                """INSERT INTO review_messages (session_id, ordinal, role, actor_person_id, text,
                                                thinking_sha, at, event_seq)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    message.session_id,
                    message.ordinal,
                    message.role,
                    message.actor_person_id,
                    message.text,
                    message.thinking_sha,
                    message.at,
                    event_seq,
                ),
            )

    def _write_decisions(self, session_id: str, decisions: tuple[ReviewDecisionRow, ...], event_seq: int) -> None:
        self.connection.execute("DELETE FROM review_decisions WHERE session_id = ?", (session_id,))
        for decision in decisions:
            self.connection.execute(
                """INSERT INTO review_decisions (session_id, ordinal, subject_kind, subject_id,
                                                 decision, basis_json, actor_person_id, at, event_seq)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    decision.session_id,
                    decision.ordinal,
                    decision.subject_kind,
                    decision.subject_id,
                    decision.decision,
                    json.dumps(decision.basis, sort_keys=True) if decision.basis else None,
                    decision.actor_person_id,
                    decision.at,
                    event_seq,
                ),
            )


def session_payload(session: Session, thinking: dict[str, str]) -> str:
    """The event payload: the session without its thinking text, plus the shas."""
    data = session.to_dict()
    for attempt in data["attempts"]:
        for message in attempt["messages"]:
            message.pop("thinking", None)
    return json.dumps(
        {"session": data, "thinking": thinking},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def session_from_payload(payload: dict[str, Any]) -> tuple[Session, dict[str, str]]:
    """The session and its thinking-sha map an event carries."""
    return Session.from_dict(payload["session"]), {
        str(key): str(value) for key, value in (payload.get("thinking") or {}).items()
    }
