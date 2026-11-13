# lucidlint: ignore-file fakefs the migration reads a real archive/workspace and writes a
# real SQLite database — C-level I/O, the testing standard's real-FS exception.
"""A7 — the migration gate: dry run, the four importers, verification, replay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loft.live.import_identity import import_identities
from loft.live.migrate import VerificationInputs, migrate, verify
from loft.live.store import LiveStore
from loft.live.verify import Projections, tree_digest


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(json.dumps(value, indent=1), encoding="utf-8")


def _fixture(root: Path) -> tuple[Path, Path, Path]:
    archive = root / "archive"
    workspace = root / "workspace"
    _write(
        archive / "people.json",
        {"people": [{"id": "p-1", "name": "Person One"}], "relationships": []},
    )
    _write(archive / "places.json", {"places": [{"id": "pl-1", "name": "Place One"}]})
    _write(archive / "orgs.json", {"orgs": [{"id": "org-1", "name": "Org One"}]})
    _write(
        archive / "themes.json",
        {"themes": [{"id": "t-1", "title": "Theme One", "items": [{"id": "item-1"}]}]},
    )
    _write(
        archive / "imports.json",
        {
            "imports": [
                {
                    "id": "import-documents",
                    "kind": "import-review",
                    "title": "The import",
                    "status": "pending",
                    "current": "p-1",
                    "attempts": [
                        {
                            "started": "2026-01-01T00:00:00+00:00",
                            "messages": [{"role": "user", "text": "Yes", "when": "2026-01-01"}],
                            "decisions": [{"person_id": "p-1", "decision": "estimated", "when": "2026-01-01"}],
                        }
                    ],
                }
            ]
        },
    )
    _write(
        archive / "assets" / "item-1" / "item.json",
        {
            "id": "item-1",
            "type": "document",
            "title": "The letter",
            "date": "1960",
            "date_precision": "year",
            "status": "catalogued",
            "assets": [
                {"kind": "transcription", "file": "transcription.txt", "caption": "The transcription"},
                {"kind": "page", "file": "page-1.svg", "caption": "Page 1"},
            ],
            "people": [{"id": "p-1", "status": "confirmed"}],
            "places": [],
            "themes": [],
        },
    )
    _write(archive / "assets" / "item-1" / "transcription.txt", b"Dear friend,\n\nThe words.\n")
    _write(archive / "assets" / "item-1" / "page-1.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>")
    _write(
        workspace / "registry" / "batch-1.json",
        {
            "batch_id": "batch-1",
            "path": "/scans/pile",
            "label": "A pile",
            "source": "external",
            "status": "review",
            "arrived_at": "2026-01-01T00:00:00+00:00",
            "started_at": "",
            "started_pid": 0,
            "started_host": "",
            "pages": {"page-01.jpg": "sha-1"},
            "fingerprint": ["sha-1"],
            "boundaries": [{"pages": ["page-01.jpg"], "greeting": "Dear", "signoff": None}],
        },
    )
    _write(workspace / "work" / "batch-1" / "classify.json", {"page-01.jpg": {"kind": "text"}})
    _write(
        workspace / "work" / "batch-1" / "oriented" / "rotations.json",
        {"page-01.jpg": {"degrees": 0}},
    )
    _write(
        workspace / "work" / "batch-1" / "ocr-guess" / "page-01.rows.json",
        {
            "page": "page-01.jpg",
            "width": 100,
            "height": 200,
            "revision": 1,
            "lines": [
                {
                    "index": 0,
                    "text": "Hello",
                    "box": [1, 2, 3, 4],
                    "orientation": 0,
                    "box_source": "reader",
                    "words": [],
                }
            ],
        },
    )
    _write(workspace / "work" / "batch-1" / "ocr-guess" / "page-01.words.json", {"words": []})
    marker = root / "backup.json"
    marker.write_text(json.dumps({"verified": True}), encoding="utf-8")
    return archive, workspace, marker


def _roots(archive: Path, workspace: Path) -> tuple[Path, Path, Path]:
    return archive, workspace / "registry", workspace / "work"


def _store(tmp_path: Path) -> LiveStore:
    return LiveStore.create(tmp_path / "loft.db", app_version="test")


def test_the_migration_gate_passes_on_the_fixture(tmp_path: Path) -> None:
    archive, workspace, marker = _fixture(tmp_path)
    store = _store(tmp_path)
    try:
        tree = tree_digest(_roots(archive, workspace))
        dry = migrate(store, archive_dir=archive, workspace=workspace, backup_marker=marker, dry_run=True)
        run = migrate(store, archive_dir=archive, workspace=workspace, backup_marker=marker)
        report = verify(
            store,
            run,
            VerificationInputs(
                archive_dir=archive,
                workspace=workspace,
                dry_operations=dry.operations,
                tree_before=tree,
            ),
        )
        assert run.mismatches == ()
        assert report.findings == ()
        assert report.ok
        assert report.digest_before == report.digest_after
        assert report.counts == {
            "people": 1,
            "places": 1,
            "orgs": 1,
            "themes": 1,
            "relationships": 0,
            "items": 1,
            "review_sessions": 1,
            "review_messages": 1,
            "review_decisions": 1,
            "batches": 1,
            "scans": 1,
            "pages": 1,
            "documents": 1,
            "document_pages": 1,
        }
        assert len(dry.operations) == len(run.operations)
    finally:
        store.close()


def test_the_dry_run_writes_nothing(tmp_path: Path) -> None:
    archive, workspace, marker = _fixture(tmp_path)
    store = _store(tmp_path)
    try:
        dry = migrate(store, archive_dir=archive, workspace=workspace, backup_marker=marker, dry_run=True)
        assert dry.dry_run is True
        assert dry.operations
        assert store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert store.connection.execute("SELECT COUNT(*) FROM content").fetchone()[0] == 0
    finally:
        store.close()


def test_a_second_migration_is_a_no_op(tmp_path: Path) -> None:
    archive, workspace, marker = _fixture(tmp_path)
    store = _store(tmp_path)
    try:
        migrate(store, archive_dir=archive, workspace=workspace, backup_marker=marker)
        events = store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        second = migrate(store, archive_dir=archive, workspace=workspace, backup_marker=marker)
        assert second.operations == ()
        assert all(value == 0 for value in second.counts.values())
        assert store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == events
    finally:
        store.close()


def test_a_partial_run_resumes_and_the_gate_still_passes(tmp_path: Path) -> None:
    archive, workspace, marker = _fixture(tmp_path)
    store = _store(tmp_path)
    try:
        import_identities(store, archive, backup_marker=marker)
        tree = tree_digest(_roots(archive, workspace))
        dry = migrate(store, archive_dir=archive, workspace=workspace, backup_marker=marker, dry_run=True)
        run = migrate(store, archive_dir=archive, workspace=workspace, backup_marker=marker)
        assert run.identities.skipped["people"] == 1
        report = verify(
            store,
            run,
            VerificationInputs(
                archive_dir=archive,
                workspace=workspace,
                dry_operations=dry.operations,
                tree_before=tree,
            ),
        )
        assert report.findings == ()
    finally:
        store.close()


def test_the_gate_catches_a_changed_tree(tmp_path: Path) -> None:
    archive, workspace, marker = _fixture(tmp_path)
    store = _store(tmp_path)
    try:
        dry = migrate(store, archive_dir=archive, workspace=workspace, backup_marker=marker, dry_run=True)
        run = migrate(store, archive_dir=archive, workspace=workspace, backup_marker=marker)
        report = verify(
            store,
            run,
            VerificationInputs(
                archive_dir=archive,
                workspace=workspace,
                dry_operations=dry.operations,
                tree_before="not-the-tree",
            ),
        )
        assert any("old tree changed" in finding for finding in report.findings)
    finally:
        store.close()


def test_the_gate_catches_a_dry_run_mismatch(tmp_path: Path) -> None:
    archive, workspace, marker = _fixture(tmp_path)
    store = _store(tmp_path)
    try:
        tree = tree_digest(_roots(archive, workspace))
        run = migrate(store, archive_dir=archive, workspace=workspace, backup_marker=marker)
        report = verify(
            store,
            run,
            VerificationInputs(
                archive_dir=archive,
                workspace=workspace,
                dry_operations=("a different operation",),
                tree_before=tree,
            ),
        )
        assert any("dry-run operations" in finding for finding in report.findings)
    finally:
        store.close()


def test_the_gate_catches_a_count_mismatch(tmp_path: Path) -> None:
    archive, workspace, marker = _fixture(tmp_path)
    store = _store(tmp_path)
    try:
        tree = tree_digest(_roots(archive, workspace))
        dry = migrate(store, archive_dir=archive, workspace=workspace, backup_marker=marker, dry_run=True)
        run = migrate(store, archive_dir=archive, workspace=workspace, backup_marker=marker)
        store.connection.execute("DELETE FROM places")
        report = verify(
            store,
            run,
            VerificationInputs(
                archive_dir=archive,
                workspace=workspace,
                dry_operations=dry.operations,
                tree_before=tree,
            ),
        )
        assert any("count places" in finding for finding in report.findings)
    finally:
        store.close()


def test_the_rebuild_reproduces_every_projection(tmp_path: Path) -> None:
    archive, workspace, marker = _fixture(tmp_path)
    store = _store(tmp_path)
    try:
        migrate(store, archive_dir=archive, workspace=workspace, backup_marker=marker)
        before = Projections.digest(store.connection)
        store.rebuild_all()
        assert Projections.digest(store.connection) == before
    finally:
        store.close()
