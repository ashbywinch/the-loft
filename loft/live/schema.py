"""The canonical schema and its verification.

`schema/truth.sql` and `schema/projections.sql` are the one definition of the
tables, triggers and indexes; this module applies them to a new database and
checks an installed database against them. It does not restate the schema.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TRUTH = REPO / "schema" / "truth.sql"
PROJECTIONS = REPO / "schema" / "projections.sql"
SCHEMA_VERSION = 1

_TABLE = re.compile(r"CREATE\s+(?:VIRTUAL\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_]\w*)", re.IGNORECASE)
_TRIGGER = re.compile(r"CREATE\s+TRIGGER\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_]\w*)", re.IGNORECASE)
_INDEX = re.compile(r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_]\w*)", re.IGNORECASE)


class SchemaError(RuntimeError):
    """The database is missing, already exists, or does not match the schema."""


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _declared(kind: re.Pattern[str], sql: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(kind.findall(sql)))


def apply_initial_schema(connection: sqlite3.Connection, app_version: str) -> None:
    """Apply `truth.sql` + `projections.sql` and record migration 1."""
    truth = _read(TRUTH)
    projections = _read(PROJECTIONS)
    connection.executescript(truth)
    connection.executescript(projections)
    digest = hashlib.sha256(f"{truth}\n{projections}".encode()).hexdigest()
    connection.execute(
        "INSERT INTO schema_migrations (version, applied_at, app_version, sql_sha256, note) VALUES (?, ?, ?, ?, ?)",
        (SCHEMA_VERSION, datetime.now(UTC).isoformat(), app_version, digest, "initial schema"),
    )
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()


def verify_schema(connection: sqlite3.Connection) -> tuple[str, ...]:
    """Return every way the database departs from the canonical schema."""
    findings: list[str] = []
    installed = {(row[0], row[1]) for row in connection.execute("SELECT type, name FROM sqlite_master")}
    truth = _read(TRUTH)
    projections = _read(PROJECTIONS)
    declarations = (
        ("table", _declared(_TABLE, truth + projections)),
        ("trigger", _declared(_TRIGGER, truth)),
        ("index", _declared(_INDEX, truth + projections)),
    )
    for kind, names in declarations:
        for name in names:
            if (kind, name) not in installed:
                findings.append(f"missing {kind}: {name}")

    journal = connection.execute("PRAGMA journal_mode").fetchone()[0]
    if str(journal).lower() != "wal":
        findings.append(f"journal_mode is {journal!r}, not wal")
    synchronous = connection.execute("PRAGMA synchronous").fetchone()[0]
    if synchronous != 2:
        findings.append(f"synchronous is {synchronous}, not 2 (FULL)")
    recursive = connection.execute("PRAGMA recursive_triggers").fetchone()[0]
    if recursive != 1:
        findings.append(f"recursive_triggers is {recursive}, not 1")
    user_version = connection.execute("PRAGMA user_version").fetchone()[0]
    if user_version != SCHEMA_VERSION:
        findings.append(f"user_version is {user_version}, not {SCHEMA_VERSION}")

    if ("table", "schema_migrations") in installed:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
        if versions != [SCHEMA_VERSION]:
            findings.append(f"schema_migrations is {versions}, not [{SCHEMA_VERSION}]")
    return tuple(findings)
