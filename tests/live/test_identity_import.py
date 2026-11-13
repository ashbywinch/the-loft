# lucidlint: ignore-file fakefs the import reads a real archive tree and writes a real
# SQLite database — C-level I/O, the testing standard's real-FS exception.
"""A3 — the identity import: dry run, marker, mapping, idempotency, read-back."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from loft.live.backup import BackupMarkerError
from loft.live.errors import LiveError
from loft.live.import_identity import import_identities
from loft.live.store import LiveStore


def _archive(root: Path, *, people: int = 5) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = [
        {"id": f"p-{index}", "name": f"Person {index}", "status": "confirmed"} for index in range(people)
    ]
    records[1] = {
        "id": "p-1",
        "name": "Person 1",
        "status": "estimated",
        "basis": {"text": "Aunt Nora's memory", "by": "Nora", "when": "2026"},
        "dob": {"date": "1963-05-14", "precision": "exact"},
    }
    (root / "people.json").write_text(
        json.dumps(
            {
                "people": records,
                "relationships": [{"a": "p-0", "b": "p-1", "kind": "parent", "label_a": "father", "label_b": "son"}],
            }
        ),
        encoding="utf-8",
    )
    (root / "places.json").write_text(
        json.dumps({"places": [{"id": "pl-mallowfield", "name": "Mallowfield", "lat": 51.5, "lng": -0.18}]}),
        encoding="utf-8",
    )
    (root / "orgs.json").write_text(
        json.dumps({"orgs": [{"id": "org-ministry", "name": "Ministry of Supply", "address": "Ivybridge House"}]}),
        encoding="utf-8",
    )
    (root / "themes.json").write_text(
        json.dumps({"themes": [{"id": "t-boats", "title": "The boats", "items": [{"id": "object-sunlight"}]}]}),
        encoding="utf-8",
    )
    marker = root / "backup.json"
    marker.write_text(json.dumps({"verified": True, "created_at": "2026-11-12T00:00:00Z"}), encoding="utf-8")
    return marker


def test_the_identity_import_maps_statuses_and_counts(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    marker = _archive(archive)
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        report = import_identities(store, archive, backup_marker=marker)
        assert report.counts == {"people": 5, "relationships": 1, "places": 1, "orgs": 1, "themes": 1}
        assert report.mismatches == ()
        assert store.people.require("p-1").status == "confirmed"
        basis = store.people.require("p-1").basis
        assert basis is not None and basis["basis"] == "recollection" and basis["text"] == "Aunt Nora's memory"
        dob = store.people.require("p-1").dob
        assert dob is not None
        assert dob.date == "1963-05-14"
        assert store.places.require("pl-mallowfield").lat == 51.5
        assert store.orgs.require("org-ministry").name == "Ministry of Supply"
        assert store.themes.require("t-boats").title == "The boats"
        assert store.relationships.require("rel-p-0-p-1-parent").kind == "parent"
        assert store.verify_chain() == ()
    finally:
        store.close()


def test_five_people_read_back_through_the_store(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    marker = _archive(archive)
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        import_identities(store, archive, backup_marker=marker)
        for index in range(5):
            assert store.people.require(f"p-{index}").name == f"Person {index}"
    finally:
        store.close()


def test_a_dry_run_writes_nothing(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    marker = _archive(archive)
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        report = import_identities(store, archive, backup_marker=marker, dry_run=True)
        assert report.dry_run is True
        assert report.operations
        assert store.people.get("p-0") is None
        assert store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    finally:
        store.close()


def test_a_rerun_is_a_no_op(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    marker = _archive(archive)
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        first = import_identities(store, archive, backup_marker=marker)
        second = import_identities(store, archive, backup_marker=marker)
        assert second.counts == {kind: 0 for kind in first.counts}
        assert second.skipped == first.counts
        assert second.operations == ()
        assert store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == first.counts["people"] + 4
    finally:
        store.close()


def test_the_import_refuses_without_a_verified_marker(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    _archive(archive)
    store = LiveStore.create(tmp_path / "loft.db", app_version="test")
    try:
        with pytest.raises(BackupMarkerError):
            import_identities(store, archive, backup_marker=tmp_path / "missing.json")
        bad = tmp_path / "bad.json"
        bad.write_text('{"verified": false}', encoding="utf-8")
        with pytest.raises(BackupMarkerError):
            import_identities(store, archive, backup_marker=bad)
        with pytest.raises(LiveError):
            import_identities(store, archive, backup_marker=bad)
    finally:
        store.close()
