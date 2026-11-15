"""The family list: who may read the archive.

The household lives in the Houses app's database — this archive reads it there
rather than keeping a second list (user, 2026-11-15).
"""

from __future__ import annotations

import json
import sqlite3
import zlib
from pathlib import Path

from pipeline.api.members import family_members, houses_db_path


def _houses_db(path: Path, people: list[dict[str, object]], *, compress: bool = True) -> Path:
    """A Houses database with one `persons` answer — the table and the row
    shape the other app writes."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE node_results (id INTEGER PRIMARY KEY, node_id TEXT, result_json BLOB, "
        "created_at TEXT NOT NULL, status TEXT)"
    )
    payload = json.dumps({"status": "succeeded", "value": people, "source_label": "user"}).encode("utf-8")
    conn.execute(
        "INSERT INTO node_results (node_id, result_json, created_at, status) VALUES (?, ?, ?, ?)",
        ("persons", zlib.compress(payload) if compress else payload, "2026-09-18T11:39:58+00:00", "succeeded"),
    )
    conn.commit()
    conn.close()
    return path


def test_the_family_is_the_households_people(tmp_path: Path) -> None:
    """The emails Houses holds are the archive's family, casefolded — and a
    person with no account (a child) is not a user."""
    db = _houses_db(
        tmp_path / "houses.db",
        [
            {"name": "Aria", "email": "aria@example.com"},
            {"name": "Meg", "email": "Meg@Example.com"},
            {"name": "Pip", "email": ""},
            {"name": "No email at all"},
        ],
    )
    assert family_members(db) == frozenset({"aria@example.com", "meg@example.com"})


def test_a_plain_json_answer_is_read_too(tmp_path: Path) -> None:
    """An older row holds the same JSON uncompressed — the reader takes both,
    so a database written before the compression changed still names the
    family."""
    db = _houses_db(tmp_path / "houses.db", [{"name": "Aria", "email": "aria@example.com"}], compress=False)
    assert family_members(db) == frozenset({"aria@example.com"})


def test_no_database_means_nobody(tmp_path: Path) -> None:
    """A missing file — or one with no `persons` answer — refuses everyone.
    The private layer must never open because a file is absent or unreadable."""
    assert family_members(tmp_path / "absent.db") == frozenset()
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    assert family_members(empty) == frozenset()
    # and a path that is not a database at all
    (tmp_path / "junk.db").write_text("not a database")
    assert family_members(tmp_path / "junk.db") == frozenset()


def test_the_path_is_the_archives_own_then_houses_then_the_checkout() -> None:
    """One machine's configuration is written once: the archive's variable
    wins, Houses' own setting serves next, and the checkout beside this one is
    the default."""
    assert houses_db_path({"THE_LOFT_HOUSES_DB": "/tmp/the-loft.db", "HOUSES_SQLITE_PATH": "/tmp/houses.db"}) == Path(
        "/tmp/the-loft.db"
    )
    assert houses_db_path({"HOUSES_SQLITE_PATH": "/tmp/houses.db"}) == Path("/tmp/houses.db")
    assert houses_db_path({}) == Path("~/Documents/code/houses/data/houses.db").expanduser()
