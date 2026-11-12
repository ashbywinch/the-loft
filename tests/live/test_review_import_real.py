"""A5's real-archive acceptance — the review sessions from the Loft disk.

Runs only under `make verify` (`-m archive`); CI has no archive.
"""

# lucidlint: ignore-file fakefs the import reads a real archive tree and writes a real
# SQLite database — C-level I/O, the testing standard's real-FS exception.

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from loft.live.import_identity import import_identities
from loft.live.import_reviews import import_reviews
from loft.live.review_map import decision_disposition
from loft.live.store import LiveStore
from tools.archive import Archive
from tools.loft_paths import LoftPaths
from tools.records import ImportsTable, Session
from tools.store import DiskStore

ARCHIVE = LoftPaths.ARCHIVE_DIR


def _table() -> ImportsTable:
    table = Archive(DiskStore(ARCHIVE)).get_identity("imports")
    assert isinstance(table, ImportsTable)
    return table


def _messages(session: Session) -> list[tuple[str, str, str]]:
    return [(message.role, message.text, message.when) for attempt in session.attempts for message in attempt.messages]


def _decisions(session: Session) -> list[tuple[str, str, dict | None]]:
    return [
        (decision.person_id, *decision_disposition(decision.decision, decision.basis))
        for attempt in session.attempts
        for decision in attempt.decisions
    ]


@pytest.mark.archive
@pytest.mark.skipif(not (ARCHIVE / "imports.json").exists(), reason="archive not mounted")
def test_the_real_archive_reviews_import_and_replay(tmp_path: Path) -> None:
    marker = tmp_path / "backup.json"
    marker.write_text(json.dumps({"verified": True}), encoding="utf-8")
    table = _table()
    expected_messages = sum(len(attempt.messages) for session in table.imports for attempt in session.attempts)
    expected_decisions = sum(len(attempt.decisions) for session in table.imports for attempt in session.attempts)
    expected_thinking = sum(
        1
        for session in table.imports
        for attempt in session.attempts
        for message in attempt.messages
        if message.thinking
    )
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        import_identities(store, ARCHIVE, backup_marker=marker)
        report = import_reviews(store, ARCHIVE, backup_marker=marker)
        assert report.counts == {
            "sessions": len(table.imports),
            "messages": expected_messages,
            "decisions": expected_decisions,
            "thinking": expected_thinking,
        }
        assert report.mismatches == ()
        assert report.skipped == {"sessions": 0}

        for session in table.imports:
            assert store.reviews.require(session.id).kind == "import"
            messages = store.reviews.messages(session.id)
            assert [(message.ordinal, message.role, message.text, message.at) for message in messages] == [
                (index, role, text, when) for index, (role, text, when) in enumerate(_messages(session), start=1)
            ]
            assert [
                (decision.subject_id, decision.decision, decision.basis)
                for decision in store.reviews.decisions(session.id)
            ] == _decisions(session)
            for decision in store.reviews.decisions(session.id):
                assert store.people.get(decision.subject_id or "") is not None
            for attempt_index, attempt in enumerate(session.attempts):
                for message_index, message in enumerate(attempt.messages):
                    if not message.thinking:
                        continue
                    ordinal = sum(len(a.messages) for a in session.attempts[:attempt_index]) + message_index + 1
                    assert store.reviews.thinking(session.id, ordinal) == message.thinking.encode("utf-8")
                    assert (
                        store.reviews.messages(session.id)[ordinal - 1].thinking_sha
                        == hashlib.sha256(message.thinking.encode("utf-8")).hexdigest()
                    )

        store.rebuild_reviews()
        for session in table.imports:
            assert [message.text for message in store.reviews.messages(session.id)] == [
                text for _role, text, _when in _messages(session)
            ]
            assert [decision.decision for decision in store.reviews.decisions(session.id)] == [
                mapped for _subject, mapped, _basis in _decisions(session)
            ]

        again = import_reviews(store, ARCHIVE, backup_marker=marker)
        assert again.counts == {"sessions": 0, "messages": 0, "decisions": 0, "thinking": 0}
        assert again.skipped == {"sessions": len(table.imports)}
    finally:
        store.close()
