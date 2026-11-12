# lucidlint: ignore-file fakefs the import reads a real archive tree and writes a real
# SQLite database — C-level I/O, the testing standard's real-FS exception.
"""A5 — the review-session import: counts, order, decision mapping, replay."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from loft.live.errors import LiveError
from loft.live.import_reviews import import_reviews
from loft.live.store import LiveStore


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1), encoding="utf-8")


def _message(role: str, text: str, *, when: str = "2026-01-01", thinking: str | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"role": role, "text": text, "when": when}
    if thinking is not None:
        message["thinking"] = thinking
    return message


def _decision(
    person_id: str,
    decision: str,
    *,
    when: str = "2026-01-01",
    basis: dict[str, Any] | None = None,
    last: bool = False,
) -> dict[str, Any]:
    raw: dict[str, Any] = {"person_id": person_id, "decision": decision, "when": when}
    if basis is not None:
        raw["basis"] = basis
    if last:
        raw["last"] = True
    return raw


def _sessions() -> list[dict[str, Any]]:
    first = {
        "id": "import-documents",
        "kind": "import-review",
        "title": "The document import",
        "status": "pending",
        "current": "p-a",
        "attempts": [
            {
                "started": "2026-01-01T00:00:00+00:00",
                "messages": [
                    _message("user", "I think so"),
                    _message("assistant", "Thanks", thinking="raw verdict"),
                ],
                "decisions": [
                    _decision(
                        "p-a",
                        "estimated",
                        basis={"text": "the family's memory", "by": "Wren", "when": "2026-01-01"},
                    )
                ],
            }
        ],
    }
    second = {
        "id": "import-photos",
        "kind": "import-review",
        "title": "The photo import",
        "status": "reviewed",
        "attempts": [
            {
                "started": "2026-01-02T00:00:00+00:00",
                "messages": [_message("user", "First walk", when="2026-01-02")],
                "decisions": [_decision("p-b", "attested", when="2026-01-02")],
            },
            {
                "started": "2026-01-03T00:00:00+00:00",
                "messages": [
                    _message("assistant", "Second walk", when="2026-01-03", thinking="second verdict"),
                    _message("user", "Done", when="2026-01-03"),
                ],
                "decisions": [_decision("p-c", "pending", when="2026-01-03", last=True)],
            },
        ],
    }
    return [first, second]


def _archive(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    # v1 has a session the later table dropped; the import must read the latest
    _write(root / "imports.json", {"imports": [{"id": "stale-session", "title": "Old", "status": "pending"}]})
    _write(root / "imports-2.json", {"imports": _sessions(), "supersedes": "imports.json"})
    marker = root / "backup.json"
    marker.write_text(json.dumps({"verified": True}), encoding="utf-8")
    return marker


def _imported(tmp_path: Path) -> tuple[LiveStore, Any]:
    archive = tmp_path / "archive"
    marker = _archive(archive)
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    report = import_reviews(store, archive, backup_marker=marker)
    return store, report


def test_the_review_import_counts_sessions_messages_decisions_and_thinking(tmp_path: Path) -> None:
    store, report = _imported(tmp_path)
    try:
        assert report.counts == {"sessions": 2, "messages": 5, "decisions": 3, "thinking": 2}
        assert report.per_session == {
            "import-documents": {"attempts": 1, "messages": 2, "decisions": 1, "thinking": 1},
            "import-photos": {"attempts": 2, "messages": 3, "decisions": 2, "thinking": 1},
        }
        assert report.skipped == {"sessions": 0}
        assert report.mismatches == ()
        assert store.reviews.get("stale-session") is None
        assert store.verify_chain() == ()
    finally:
        store.close()


def test_the_transcript_keeps_its_order_across_attempts(tmp_path: Path) -> None:
    store, _report = _imported(tmp_path)
    try:
        messages = store.reviews.messages("import-photos")
        assert [message.ordinal for message in messages] == [1, 2, 3]
        assert [message.role for message in messages] == ["user", "assistant", "user"]
        assert [message.text for message in messages] == ["First walk", "Second walk", "Done"]
        assert [message.at for message in messages] == ["2026-01-02", "2026-01-03", "2026-01-03"]
        assert messages[0].thinking_sha is None
        assert messages[1].thinking_sha == hashlib.sha256(b"second verdict").hexdigest()
        assert store.reviews.thinking("import-photos", 2) == b"second verdict"
    finally:
        store.close()


def test_the_decisions_map_to_the_target_vocabulary(tmp_path: Path) -> None:
    store, _report = _imported(tmp_path)
    try:
        first = store.reviews.decisions("import-documents")[0]
        assert (first.subject_id, first.decision) == ("p-a", "attested")
        assert first.basis is not None
        assert first.basis["basis"] == "recollection" and first.basis["confidence"] == "possible"
        assert first.basis["text"] == "the family's memory"
        second = store.reviews.decisions("import-photos")
        assert [decision.decision for decision in second] == ["attested", "pending"]
        assert second[0].basis == {"basis": "knowledge", "confidence": "certain"}
        assert second[1].basis is None
    finally:
        store.close()


def test_the_session_state_carries_kind_attempt_and_closure(tmp_path: Path) -> None:
    store, _report = _imported(tmp_path)
    try:
        pending = store.reviews.require("import-documents")
        assert (pending.kind, pending.status, pending.current_attempt) == ("import", "pending", 1)
        assert (pending.subject_kind, pending.actor_person_id) == ("batch", "import")
        reviewed = store.reviews.require("import-photos")
        assert (reviewed.status, reviewed.current_attempt) == ("reviewed", None)
        assert reviewed.closed_at == "2026-01-03"
    finally:
        store.close()


def test_a_dry_run_writes_nothing(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    marker = _archive(archive)
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        report = import_reviews(store, archive, backup_marker=marker, dry_run=True)
        assert report.dry_run is True
        assert report.operations == ("review import-documents", "review import-photos")
        assert store.reviews.get("import-documents") is None
        assert store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert store.connection.execute("SELECT COUNT(*) FROM content").fetchone()[0] == 0
    finally:
        store.close()


def test_a_rerun_is_a_no_op(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    marker = _archive(archive)
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        import_reviews(store, archive, backup_marker=marker)
        second = import_reviews(store, archive, backup_marker=marker)
        assert second.counts == {"sessions": 0, "messages": 0, "decisions": 0, "thinking": 0}
        assert second.per_session == {}
        assert second.skipped == {"sessions": 2}
        assert second.operations == ()
        assert store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
    finally:
        store.close()


def test_a_rebuild_replays_the_sessions(tmp_path: Path) -> None:
    store, _report = _imported(tmp_path)
    try:
        store.rebuild_reviews()
        assert len(store.reviews.messages("import-photos")) == 3
        assert store.reviews.decisions("import-documents")[0].basis is not None
        assert store.reviews.thinking("import-photos", 2) == b"second verdict"
        assert store.reviews.require("import-photos").closed_at == "2026-01-03"
    finally:
        store.close()


def test_the_import_refuses_without_a_verified_marker(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    _archive(archive)
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        with pytest.raises(LiveError):
            import_reviews(store, archive, backup_marker=tmp_path / "missing.json")
    finally:
        store.close()
