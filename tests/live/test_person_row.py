"""The person projection — the row mapping's reader, guarded writer and delete.

`tests/live/test_live_store.py` pins the same SQL through `change.people`;
this suite names the projection itself. The guard is the point: `write` is
handed the version it read and refuses the row when the projection has moved
on, and `People.save` refuses a create that finds one — so a caller can never
reach the "stale" branch for a record that simply already exists.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from loft.live.errors import Conflict, StaleVersion
from loft.live.person_row import PersonProjection, RowPosition
from loft.live.store import LiveStore
from tools.records import Person


@pytest.fixture
def store(tmp_path: Path) -> Iterator[LiveStore]:
    live = LiveStore.create(tmp_path / "loft.db", app_version="test")
    yield live
    live.close()


@pytest.fixture
def projection(store: LiveStore) -> PersonProjection:
    return PersonProjection(store.connection)


def _person(name: str = "Aria Barlow", *, residence: tuple[dict[str, str], ...] = ()) -> Person:
    return Person.from_dict({"id": "p-aria", "name": name, "status": "confirmed", "residence": list(residence)})


def _position(version: int = 1) -> RowPosition:
    return RowPosition(version=version, event_no=version, event_seq=version, updated_at="2026-01-01T00:00:00+00:00")


def test_an_unwritten_person_reads_as_none(projection: PersonProjection) -> None:
    assert projection.get("p-aria") is None


def test_a_write_round_trips_the_record_and_its_position(projection: PersonProjection) -> None:
    projection.write(_person(), _position(version=2), base=None)
    read = projection.get("p-aria")
    assert read is not None
    assert (read.name, read.status, read.version) == ("Aria Barlow", "confirmed", 2)


def test_a_supersede_replaces_the_row_on_the_version_it_read(projection: PersonProjection) -> None:
    projection.write(_person(), _position(version=1), base=None)
    projection.write(_person("Aria Whitlock"), _position(version=2), base=1)
    read = projection.get("p-aria")
    assert read is not None and (read.name, read.version) == ("Aria Whitlock", 2)


def test_a_stale_base_is_refused_with_the_row_as_it_stands(projection: PersonProjection) -> None:
    projection.write(_person(), _position(version=2), base=None)
    with pytest.raises(StaleVersion) as caught:
        projection.write(_person("Other"), _position(version=3), base=1)
    assert caught.value.current is not None and caught.value.current.version == 2
    read = projection.get("p-aria")
    assert read is not None and read.name == "Aria Barlow"  # the refused write changed nothing


def test_a_create_over_an_existing_row_is_stale_not_a_second_insert(projection: PersonProjection) -> None:
    """`write` has no create/supersede mode: `base=None` matches no version,
    so the row it finds is refused. `People.save` checks first and raises the
    honest `Conflict`, which is why this branch is only reachable by a caller
    that skipped the collection."""
    projection.write(_person(), _position(version=1), base=None)
    with pytest.raises(StaleVersion):
        projection.write(_person("Other"), _position(version=1), base=None)
    read = projection.get("p-aria")
    assert read is not None and read.name == "Aria Barlow"


def test_the_collection_refuses_a_create_that_finds_the_person(store: LiveStore) -> None:
    with store.change(actor="test") as change:
        change.people.save(_person())
    with pytest.raises(Conflict, match="exists"), store.change(actor="test") as change:
        change.people.save(_person("Other"))


def test_a_write_replaces_the_residences_rather_than_appending(projection: PersonProjection) -> None:
    first = _person(residence=({"place": "pl-marlock", "from": "1930", "to": "1940"},))
    projection.write(first, _position(version=1), base=None)
    second = _person(residence=({"place": "pl-riverfield", "from": "1940", "to": ""},))
    projection.write(second, _position(version=2), base=1)
    read = projection.get("p-aria")
    assert read is not None
    assert [(entry["place"], entry["from"], entry["to"]) for entry in read.residence] == [("pl-riverfield", "1940", "")]


def test_a_delete_removes_the_person_and_their_residences(projection: PersonProjection, store: LiveStore) -> None:
    residence = {"place": "pl-marlock", "from": "1930", "to": "1940"}
    projection.write(_person(residence=(residence,)), _position(), base=None)
    projection.delete("p-aria")
    assert projection.get("p-aria") is None
    assert store.connection.execute("SELECT COUNT(*) FROM person_residences").fetchone()[0] == 0
