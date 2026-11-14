"""B3 — the review state writes through the service.

The ported review scenarios: the import session's creation, its walk, its
transcript and decisions, and the completion rule — each one change, on both
stores. The imports-table exporter follows every write, so the projection and
the archive's session reads see the old table.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from loft.live.compat_reviews import ImportsCompatibility
from loft.live.memory import MemoryLiveStore
from loft.live.review_writes import ReviewWrites
from loft.live.store import LiveStore
from tools.archive import Archive
from tools.records import Person, ReviewDecision, Session
from tools.store import MemoryStore


@pytest.fixture(params=["sqlite", "memory"])
def host(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[tuple[Any, Archive, ReviewWrites]]:
    if request.param == "sqlite":
        live = LiveStore.create(tmp_path / "loft.db", app_version="test")
    else:
        live = MemoryLiveStore(app_version="test")
    archive = Archive(MemoryStore())
    export = ImportsCompatibility(live, archive)
    writes = ReviewWrites(live)
    archive.bind_review_service(writes, export.write)
    yield live, archive, writes
    live.close()


def _session(session_id: str = "import-documents") -> Session:
    return Session(
        id=session_id,
        kind="import-review",
        title="The document import",
        status="pending",
        current=None,
        attempts=(),
    )


def _seed_proposal(host: tuple[Any, Archive, ReviewWrites]) -> None:
    live, _archive, _writes = host
    with live.change(actor="import") as change:
        change.people.save(Person.from_dict({"id": "p-pending", "name": "A Pending Person", "status": "proposed"}))


def test_ensure_writes_the_session_once(host: tuple[Any, Archive, ReviewWrites]) -> None:
    live, archive, writes = host
    writes.ensure(_session(), actor="import")
    writes.ensure(_session(), actor="import")  # a repeat is a no-op
    assert live.reviews.require("import-documents").version == 1
    assert len(live.events_for("import-documents", entity_kind="review_session")) == 1
    archive._ensure_import_session()
    assert archive.get_review_session("import-documents") is not None
    assert live.verify_chain() == ()


def test_start_continues_the_unfinished_walk(host: tuple[Any, Archive, ReviewWrites]) -> None:
    live, _archive, writes = host
    writes.ensure(_session(), actor="import")
    assert writes.start("import-documents", actor="review") is not None
    assert len(writes.start("import-documents", actor="review").attempts) == 1
    before = len(live.events_for("import-documents", entity_kind="review_session"))
    # a mid-walk re-render continues the same attempt and writes nothing
    writes.start("import-documents", actor="review")
    assert len(live.events_for("import-documents", entity_kind="review_session")) == before
    writes.update(
        "import-documents",
        lambda session: session.add_message("user", "a line", "2026-01-01"),
        actor="review",
    )
    writes.update(
        "import-documents",
        lambda session: session.add_decision(
            ReviewDecision(person_id="p-a", decision="pending", when="2026-01-01", last=True)
        ),
        actor="review",
    )
    started = writes.start("import-documents", actor="review")
    assert len(started.attempts) == 2  # the finished walk is done; a fresh one starts


def test_a_message_and_its_thinking_round_trip(host: tuple[Any, Archive, ReviewWrites]) -> None:
    live, _archive, writes = host
    writes.ensure(_session(), actor="import")
    writes.start("import-documents", actor="review")
    writes.update(
        "import-documents",
        lambda session: session.add_message("user", "I think so", "2026-01-01"),
        actor="review",
    )
    writes.update(
        "import-documents",
        lambda session: session.add_message("assistant", "Thanks", "2026-01-01", "raw verdict"),
        actor="review",
    )
    session = writes.session("import-documents")
    assert session is not None
    assert [message.text for message in session.attempts[0].messages] == ["I think so", "Thanks"]
    assert session.attempts[0].messages[1].thinking == "raw verdict"
    rows = live.reviews.messages("import-documents")
    assert [(row.role, row.text) for row in rows] == [("user", "I think so"), ("assistant", "Thanks")]
    assert live.reviews.thinking("import-documents", 2) == b"raw verdict"
    assert live.verify_chain() == ()


def test_a_decision_advances_the_resume_point(host: tuple[Any, Archive, ReviewWrites]) -> None:
    live, _archive, writes = host
    writes.ensure(_session(), actor="import")
    writes.start("import-documents", actor="review")
    writes.update(
        "import-documents",
        lambda session: session.add_decision(
            ReviewDecision(person_id="p-a", decision="estimated", when="2026-01-01", last=False)
        ),
        actor="review",
    )
    session = writes.session("import-documents")
    assert session is not None and session.current == "p-a"
    assert session.attempts[0].decisions[0].decision == "estimated"  # the old API's vocabulary
    assert [row.decision for row in live.reviews.decisions("import-documents")] == [
        "attested"
    ]  # the target disposition
    assert live.verify_chain() == ()


def test_refresh_completes_the_session_only_when_no_proposal_waits(host: tuple[Any, Archive, ReviewWrites]) -> None:
    live, _archive, writes = host
    writes.ensure(_session(), actor="import")
    _seed_proposal(host)
    assert writes.refresh(actor="review") == 0
    assert live.reviews.require("import-documents").status == "pending"
    live.identities.confirm_person("p-pending", actor="review")
    assert writes.refresh(actor="review") == 1
    assert live.reviews.require("import-documents").status == "reviewed"
    assert writes.refresh(actor="review") == 0  # already done


def test_a_failed_review_change_rolls_back(host: tuple[Any, Archive, ReviewWrites]) -> None:
    live, _archive, writes = host
    writes.ensure(_session(), actor="import")
    with pytest.raises(RuntimeError), live.change(actor="review") as change:
        session = change.reviews.session("import-documents")
        assert session is not None
        change.reviews.save(
            session.add_message("user", "never", "2026-01-01"), base=change.reviews.get("import-documents").version
        )
        raise RuntimeError("boom")
    assert live.reviews.messages("import-documents") == ()
    assert len(live.events_for("import-documents", entity_kind="review_session")) == 1


def test_concurrent_messages_lose_nothing(host: tuple[Any, Archive, ReviewWrites]) -> None:
    _live, _archive, writes = host
    writes.ensure(_session(), actor="import")
    writes.start("import-documents", actor="review")
    errors: list[Exception] = []

    def writer(prefix: str) -> None:
        try:
            for index in range(10):
                writes.update(
                    "import-documents",
                    lambda session, text=f"{prefix}-{index}": session.add_message("user", text, "2026-01-01"),
                    actor="review",
                )
        except Exception as error:  # noqa: BLE001 — the test reports every failure
            errors.append(error)

    threads = [threading.Thread(target=writer, args=(prefix,)) for prefix in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    session = writes.session("import-documents")
    assert session is not None
    texts = [message.text for message in session.attempts[0].messages]
    assert len(texts) == 20
    assert all(f"a-{index}" in texts and f"b-{index}" in texts for index in range(10))


def test_the_archive_routes_the_review_verbs(host: tuple[Any, Archive, ReviewWrites]) -> None:
    live, archive, _writes = host
    archive._ensure_import_session()
    assert archive.start_review_attempt("import-documents") == 0
    archive.record_review_message("import-documents", "user", "I think so", "2026-01-01")
    archive.record_review_decision(
        "import-documents", ReviewDecision(person_id="p-a", decision="pending", when="2026-01-01", last=True)
    )
    session = archive.get_review_session("import-documents")
    assert session is not None
    assert session.attempts[0].messages[0].text == "I think so"
    assert session.attempts[0].decisions[0].decision == "pending"
    assert live.reviews.require("import-documents").status == "pending"


def test_the_imports_table_is_the_old_shape(host: tuple[Any, Archive, ReviewWrites]) -> None:
    live, archive, _writes = host
    archive._ensure_import_session()
    archive.start_review_attempt("import-documents")
    archive.record_review_message("import-documents", "assistant", "Thanks", "2026-01-01", "raw verdict")
    table = archive.get_identity("imports")
    assert table is not None
    assert table.imports[0].id == "import-documents"
    message = table.imports[0].attempts[0].messages[0]
    assert message.text == "Thanks" and message.thinking == "raw verdict"  # the thinking text, not a sha
    assert archive.store.exists("imports.json")  # the old versioned table the readers parse
    # a second export with no change writes nothing
    assert ImportsCompatibility(live, archive).write() is False
    assert table.imports[0].status == "pending"
