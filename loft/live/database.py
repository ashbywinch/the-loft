"""The live database connection and its lifecycle.

`LiveDatabase.create` builds a new database from the canonical schema and
`LiveDatabase.open` opens an existing one; both apply the connection pragmas
from `docs/TECHSPEC/05-schema.md` §18.5. The write seam and the store facade
land in A2.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Self

from loft.live.schema import SchemaError, apply_initial_schema, verify_schema

_PRAGMAS = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA synchronous = FULL",
    "PRAGMA busy_timeout = 5000",
    "PRAGMA wal_autocheckpoint = 1000",
    "PRAGMA recursive_triggers = ON",
)


class LiveDatabase:
    """One open SQLite database with the canonical schema and pragmas."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    @classmethod
    def create(
        cls,
        path: Path,
        *,
        app_version: str,
        verify: Callable[[sqlite3.Connection], tuple[str, ...]] = verify_schema,
    ) -> Self:
        if path.exists():
            raise SchemaError(f"{path} exists — refusing to overwrite")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Build a hidden sibling and publish it only when the whole schema
        # verifies: a kill mid-init leaves no half-created `loft.db` to trick
        # the next run into "already exists — refusing to overwrite".
        temporary = path.with_name(f".{path.name}.{os.urandom(8).hex()}.init")
        connection = sqlite3.connect(temporary, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            cls._apply_pragmas(connection)
            apply_initial_schema(connection, app_version)
            findings = verify(connection)
            if findings:
                raise SchemaError("; ".join(findings))
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except BaseException:
            connection.close()
            for suffix in ("", "-wal", "-shm"):
                temporary.with_name(temporary.name + suffix).unlink(missing_ok=True)
            raise
        connection.close()
        for suffix in ("-wal", "-shm"):
            temporary.with_name(temporary.name + suffix).unlink(missing_ok=True)
        os.replace(temporary, path)
        return cls.open(path)

    @classmethod
    def open(cls, path: Path) -> Self:
        if not path.is_file():
            raise SchemaError(f"no database at {path}")
        connection = sqlite3.connect(path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            cls._apply_pragmas(connection)
        except Exception:
            connection.close()
            raise
        return cls(connection)

    @staticmethod
    def _apply_pragmas(connection: sqlite3.Connection) -> None:
        for pragma in _PRAGMAS:
            connection.execute(pragma).fetchall()

    def verify_schema(self) -> tuple[str, ...]:
        return verify_schema(self.connection)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
