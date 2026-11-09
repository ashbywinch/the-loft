"""The live database: creation from the canonical schema, the connection
pragmas, and the verification `loft verify --schema` runs."""

# lucidlint: ignore-file fakefs sqlite3 opens a real database file — C-level I/O, the standard's real-FS exception

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from loft.live.database import LiveDatabase
from loft.live.schema import SchemaError


def _event(connection: sqlite3.Connection, event_id: str = "e1", event_no: int = 1) -> None:
    connection.execute(
        """INSERT INTO events (event_id, change_id, entity_kind, entity_id, event_no,
           entity_version, event_type, payload, payload_schema, recorded_at, actor_kind,
           actor_id, command_id, app_version, prev_hash, hash)
           VALUES (?, 'c1', 'person', 'p1', ?, 1, 'created', '{}', 1,
                   '2026-01-01T00:00:00Z', 'system', 'test', NULL, 'test', NULL, 'h1')""",
        (event_id, event_no),
    )


def test_create_applies_the_schema_and_records_the_migration(tmp_path: Path) -> None:
    db = LiveDatabase.create(tmp_path / "loft.db", app_version="test")
    try:
        assert db.verify_schema() == ()
        rows = db.connection.execute("SELECT version, app_version FROM schema_migrations").fetchall()
        assert [tuple(row) for row in rows] == [(1, "test")]
    finally:
        db.close()


def test_create_refuses_an_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "loft.db"
    LiveDatabase.create(path, app_version="test").close()
    with pytest.raises(SchemaError, match="exists"):
        LiveDatabase.create(path, app_version="test")


def test_open_refuses_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SchemaError, match="no database"):
        LiveDatabase.open(tmp_path / "absent.db")


def test_open_applies_the_connection_pragmas(tmp_path: Path) -> None:
    path = tmp_path / "loft.db"
    LiveDatabase.create(path, app_version="test").close()
    db = LiveDatabase.open(path)
    try:
        assert db.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert db.connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert db.connection.execute("PRAGMA recursive_triggers").fetchone()[0] == 1
        assert db.connection.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        db.close()


def test_events_refuse_update_and_delete(tmp_path: Path) -> None:
    db = LiveDatabase.create(tmp_path / "loft.db", app_version="test")
    try:
        _event(db.connection)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.connection.execute("UPDATE events SET payload = '{}' WHERE event_id = 'e1'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.connection.execute("DELETE FROM events WHERE event_id = 'e1'")
    finally:
        db.close()


def test_events_refuse_a_duplicate_event(tmp_path: Path) -> None:
    db = LiveDatabase.create(tmp_path / "loft.db", app_version="test")
    try:
        _event(db.connection)
        with pytest.raises(sqlite3.IntegrityError, match="already exists"):
            _event(db.connection, event_no=2)
    finally:
        db.close()


def test_verify_reports_a_missing_projection(tmp_path: Path) -> None:
    db = LiveDatabase.create(tmp_path / "loft.db", app_version="test")
    try:
        db.connection.execute("DROP TABLE people")
        findings = db.verify_schema()
        assert any("people" in finding for finding in findings), findings
    finally:
        db.close()


def test_verify_reports_a_missing_trigger(tmp_path: Path) -> None:
    db = LiveDatabase.create(tmp_path / "loft.db", app_version="test")
    try:
        db.connection.execute("DROP TRIGGER events_no_update")
        findings = db.verify_schema()
        assert any("events_no_update" in finding for finding in findings), findings
    finally:
        db.close()
