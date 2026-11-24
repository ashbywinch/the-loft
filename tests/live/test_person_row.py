"""The person row and its residences are one unit (TECHSPEC/05 §18.4).

`people` and `person_residences` are two tables behind one projection method,
and the connection is autocommit — so the pair must land together whether the
write arrives inside a change's transaction or on its own. A failure in the
second half restores the first, and a caller that already holds a transaction
is joined, never given a second `BEGIN`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from loft.live import person_row
from loft.live.errors import StaleVersion
from loft.live.store import LiveStore
from tools.records import Person

MALLOWFIELD = {"place": "pl-mallowfield", "from": "1960", "to": "1968", "status": "confirmed"}
# The table's key is (person_id, place_id, from_date): the second of these is
# refused by SQLite itself, which is the failure the write must survive.
TWICE_THE_SAME = (MALLOWFIELD, {"place": "pl-mallowfield", "from": "1960", "status": "confirmed"})


@pytest.fixture
def store(tmp_path: Path) -> Iterator[LiveStore]:
    live = LiveStore.create(tmp_path / "loft.db", app_version="test")
    yield live
    live.close()


def _position(version: int) -> person_row.RowPosition:
    return person_row.RowPosition(
        version=version, event_no=version, event_seq=version, updated_at="2026-01-01T00:00:00+00:00"
    )


def _person(name: str = "Alex Hale", residence: tuple[dict[str, Any], ...] = ()) -> Person:
    return Person.from_dict({"id": "p-alex", "name": name, "status": "confirmed", "residence": list(residence)})


def test_a_refused_residence_leaves_no_new_person_row(store: LiveStore) -> None:
    projection = person_row.PersonProjection(store.connection)
    with pytest.raises(sqlite3.IntegrityError):
        projection.write(_person(residence=TWICE_THE_SAME), _position(1), base=None)
    assert projection.get("p-alex") is None
    assert store.connection.execute("SELECT COUNT(*) FROM person_residences").fetchone()[0] == 0
    assert store.connection.in_transaction is False


def test_a_residences_basis_survives_the_write(store: LiveStore) -> None:
    """A residence's provenance is the record's, not the projection's: the
    column is written from the residence and read back, so a rewrite cannot
    silently drop it."""
    attested = {**MALLOWFIELD, "basis": {"text": "the 1960 letter", "by": "Nora", "when": "1960"}}
    projection = person_row.PersonProjection(store.connection)
    projection.write(_person(residence=(attested,)), _position(1), base=None)
    stored = projection.get("p-alex")
    assert stored is not None
    assert stored.residence == (attested,)


def test_a_refused_residence_keeps_the_person_it_would_replace(store: LiveStore) -> None:
    projection = person_row.PersonProjection(store.connection)
    projection.write(_person(residence=(MALLOWFIELD,)), _position(1), base=None)
    with pytest.raises(sqlite3.IntegrityError):
        projection.write(_person("Alexandra Hale", residence=TWICE_THE_SAME), _position(2), base=1)
    kept = projection.get("p-alex")
    assert kept is not None
    assert kept.name == "Alex Hale"
    assert kept.residence == (MALLOWFIELD,)
    assert store.connection.in_transaction is False


def test_a_refused_person_delete_keeps_the_residences_it_would_orphan(store: LiveStore) -> None:
    projection = person_row.PersonProjection(store.connection)
    projection.write(_person(residence=(MALLOWFIELD,)), _position(1), base=None)
    store.connection.execute(
        """CREATE TRIGGER a_person_who_stays BEFORE DELETE ON people
           BEGIN SELECT RAISE(ABORT, 'the person row stays'); END"""
    )
    with pytest.raises(sqlite3.IntegrityError):
        projection.delete("p-alex")
    kept = projection.get("p-alex")
    assert kept is not None
    assert kept.residence == (MALLOWFIELD,)
    assert store.connection.in_transaction is False


def test_a_change_keeps_the_pair_in_its_own_transaction(store: LiveStore) -> None:
    """The change already holds `BEGIN IMMEDIATE`; the projection joins it
    rather than nesting (a nested BEGIN is a Conflict, not an IntegrityError)."""
    with pytest.raises(sqlite3.IntegrityError), store.change(actor="p-editor") as change:
        change.people.save(_person(residence=TWICE_THE_SAME))
    assert store.people.get("p-alex") is None
    assert store.events_for("p-alex") == []
    assert store.connection.in_transaction is False


def test_a_stale_write_takes_the_whole_change_with_it(store: LiveStore) -> None:
    """A change is one unit: a write the version guard refuses rolls back the
    change's own earlier writes too — nothing is half-applied, and no event
    survives the rollback. A per-row rollback inside the change would leave the
    log and the projection disagreeing, which is the state the unit prevents."""
    projection = person_row.PersonProjection(store.connection)
    with pytest.raises(StaleVersion), store.change(actor="p-editor") as change:
        change.people.save(_person(), base=None)  # the change's own write
        projection.write(_person("Alexandra Hale"), _position(2), base=9)  # stale
    assert store.people.get("p-alex") is None
    assert store.events_for("p-alex") == []
    assert store.connection.in_transaction is False
