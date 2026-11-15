"""The Houses app's database, read-only — the household's own list of people.

This archive and Houses are the same household, and Houses is where its people
are kept. Reading them here, in the one package that speaks SQL, keeps the
persistence boundary honest (TECHSPEC §19.2): no other module opens a
database.

Houses stores each node's answer as one `node_results` row: the newest
`persons` row holds the people as zlib-compressed JSON (older rows: plain
JSON). Nothing here writes.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import zlib
from pathlib import Path
from typing import Any


class HousesDatabaseError(Exception):
    """The household's list could not be read — the file is missing, locked,
    not a database, or holds no `persons` answer. One error for the caller to
    decide what "no list" means."""


class HousesDatabase:
    """One Houses database, opened read-only per question."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def persons(self) -> list[dict[str, Any]]:
        """The household as the newest `persons` answer holds it, or
        `HousesDatabaseError` — the caller decides what a missing list means."""
        try:
            return self._read()
        except (OSError, sqlite3.Error, ValueError, zlib.error) as exc:
            raise HousesDatabaseError(f"{self.path}: {exc}") from exc

    def _read(self) -> list[dict[str, Any]]:
        # read-only: the archive never writes the other app's database
        # the newest answer wins: Houses appends a row per change and never
        # rewrites the household in place
        latest = (
            "SELECT result_json FROM node_results WHERE node_id = 'persons' AND result_json IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 1"
        )
        conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=2.0)
        try:
            row = conn.execute(latest).fetchone()
        finally:
            conn.close()
        if row is None:
            raise ValueError(f"no persons answer in {self.path}")
        answer = self._json(row[0])
        people = answer.get("value") if isinstance(answer, dict) else answer
        if not isinstance(people, list):
            raise ValueError("the persons answer holds no list of people")
        return [person for person in people if isinstance(person, dict)]

    @staticmethod
    def _json(payload: Any) -> Any:
        """The stored answer, decoded: a row that is not compressed is plain
        JSON (an older build wrote those), so a failed decompress means "read
        it as it stands", not "this row is broken"."""
        raw = payload if isinstance(payload, bytes) else str(payload).encode("utf-8")
        with contextlib.suppress(zlib.error):
            raw = zlib.decompress(raw)
        return json.loads(raw.decode("utf-8"))
