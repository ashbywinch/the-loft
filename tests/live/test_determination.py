"""The review's determination — one decision, applied to the record as it stands.

The four decisions, and the edges that decide whether anything is written
at all. `tests/live/test_identity_writes.py` drives the same ladder through
the collections on both stores; this suite names the class that holds it, so
a change to the shared ladder fails here by name rather than three times
through its callers.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TypeVar, override

import pytest

from loft.live.determination import Determination, IdentityRecords
from loft.live.errors import StaleVersion
from tools.gone_person import GonePerson
from tools.gone_place import GonePlace
from tools.records import Person, Place

Record = TypeVar("Record", bound=Person | Place)


class FakeRecords(IdentityRecords[Record]):
    """Records in a dict — the three verbs `Determination` uses, and a log of
    what it was asked to write. It subclasses the protocol, so the type
    checker holds a fake to the same three verbs as the real collections
    (`testing-standards.md`: "fakes subclass the real classes so type checking
    still holds"), and it is generic over the two record kinds for the same
    reason the ladder is."""

    def __init__(self, *records: Record) -> None:
        self.rows: dict[str, Record] = {record.id: record for record in records}
        self.saves: list[tuple[Record, int | None]] = []
        self.deleted: list[str] = []

    @override
    def get(self, record_id: str) -> Record | None:
        return self.rows.get(record_id)

    @override
    def save(self, record: Record, base: int | None = None) -> Record:
        self.saves.append((record, base))
        self.rows[record.id] = record
        return record

    @override
    def delete(self, record_id: str) -> None:
        self.deleted.append(record_id)
        self.rows.pop(record_id, None)


def _person(status: str = "proposed", *, basis: dict[str, str] | None = None, version: int = 1) -> Person:
    raw: dict[str, object] = {"id": "p-aria", "name": "Aria Barlow", "status": status}
    if basis is not None:
        raw["basis"] = basis
    return replace(Person.from_dict(raw), version=version)


def _apply(records: FakeRecords, decision: str, basis: dict[str, str] | None = None) -> Person | GonePerson | None:
    return Determination(decision, basis).apply(records, "p-aria", gone=GonePerson)


# -- the edges: nothing to decide, or nothing left to decide ------------------


def test_the_gone_marker_is_made_only_for_a_delete() -> None:
    """`gone` is the delete's marker: no other decision calls it, so a
    determination that keeps the record cannot hand a tombstone back."""
    calls: list[str] = []

    def gone(record_id: str) -> GonePerson:
        calls.append(record_id)
        return GonePerson(record_id)

    for decision in ("attested", "estimated", "pending"):
        basis = {"text": "She told me so", "by": "Aria", "when": "2026-08-09"} if decision == "estimated" else None
        resolved = Determination(decision, basis).apply(FakeRecords(_person()), "p-aria", gone=gone)
        assert isinstance(resolved, Person)
    assert calls == []

    resolved = Determination("delete").apply(FakeRecords(_person()), "p-aria", gone=gone)
    assert resolved == GonePerson("p-aria")
    assert calls == ["p-aria"]


def test_a_stale_save_propagates() -> None:
    """The save is on the version the ladder read: a store that finds the
    record moved on raises, and the determination does not swallow it."""

    class StaleRecords(FakeRecords[Person]):
        @override
        def save(self, record: Person, base: int | None = None) -> Person:
            raise StaleVersion(current=record, base=base)

    with pytest.raises(StaleVersion):
        _apply(StaleRecords(_person("proposed", version=3)), "attested")


def test_an_unknown_record_is_left_alone() -> None:
    records = FakeRecords()
    assert _apply(records, "attested") is None
    assert (records.saves, records.deleted) == ([], [])


def test_a_record_whose_wire_omits_status_is_read_as_confirmed() -> None:
    """The wire's rule (`Person.to_dict` omits `status` when it is confirmed,
    pinned in `tests/test_records.py`) meets the ladder here: a record parsed
    without a status is confirmed, left alone by `attested` and never treated
    as a proposal to re-confirm."""
    confirmed = Person.from_dict({"id": "p-aria", "name": "Aria Barlow"})
    records = FakeRecords(confirmed)
    resolved = _apply(records, "attested")
    assert isinstance(resolved, Person) and resolved.status == "confirmed"
    assert records.saves == []

    rejected = Person.from_dict({"id": "p-aria", "name": "Aria Barlow", "status": "rejected"})
    assert _apply(FakeRecords(rejected), "attested") == rejected


@pytest.mark.parametrize("decision", ["attested", "estimated", "pending", "delete"])
def test_a_rejected_proposal_is_terminal_whatever_the_decision(decision: str) -> None:
    """A rejected proposal is terminal before the decision is even read: no
    decision revives it, and none writes over it."""
    records = FakeRecords(_person("rejected"))
    resolved = _apply(records, decision)
    assert isinstance(resolved, Person) and resolved.status == "rejected"
    assert (records.saves, records.deleted) == ([], [])


def test_pending_decides_nothing() -> None:
    records = FakeRecords(_person())
    resolved = _apply(records, "pending")
    assert isinstance(resolved, Person) and resolved.status == "proposed"
    assert (records.saves, records.deleted) == ([], [])


# -- attested ---------------------------------------------------------------


def test_attested_confirms_a_proposal_on_the_version_it_read() -> None:
    records = FakeRecords(_person("proposed", version=3))
    resolved = _apply(records, "attested")
    assert isinstance(resolved, Person)
    assert resolved.status == "confirmed"
    assert resolved.basis == {"basis": "knowledge", "confidence": "certain"}
    assert records.saves == [(resolved, 3)]  # the read's own version, not a guess


def test_attested_leaves_a_confirmed_record_alone() -> None:
    records = FakeRecords(_person("confirmed", version=2))
    resolved = _apply(records, "attested")
    assert isinstance(resolved, Person) and resolved.status == "confirmed"
    assert records.saves == []


def test_attested_reconfirms_a_record_that_renders_estimated() -> None:
    """A confirmed record whose basis is recollection below certainty still
    renders as estimated: the reviewer's attestation is what makes it known."""
    records = FakeRecords(_person("confirmed", basis={"basis": "recollection", "confidence": "possible"}))
    resolved = _apply(records, "attested")
    assert isinstance(resolved, Person)
    assert resolved.basis == {"basis": "knowledge", "confidence": "certain"}
    assert len(records.saves) == 1


# -- estimated --------------------------------------------------------------


def test_estimated_confirms_on_the_reviewers_own_words() -> None:
    basis = {"text": "She told me so at the wake.", "by": "Aria", "when": "2026-08-09"}
    records = FakeRecords(_person())
    resolved = _apply(records, "estimated", basis)
    assert isinstance(resolved, Person)
    assert resolved.status == "confirmed"  # estimated is a rendering, not a status
    assert resolved.basis == {"basis": "recollection", "confidence": "possible", **basis}
    assert records.saves == [(resolved, 1)]


def test_estimated_without_a_basis_is_refused_and_writes_nothing() -> None:
    records = FakeRecords(_person())
    with pytest.raises(ValueError, match="basis"):
        _apply(records, "estimated")
    assert records.saves == []
    assert records.rows["p-aria"].status == "proposed"


def test_estimated_with_a_blank_basis_is_refused() -> None:
    records = FakeRecords(_person())
    with pytest.raises(ValueError, match="basis"):
        _apply(records, "estimated", {"text": "   "})
    assert records.saves == []


# -- delete -----------------------------------------------------------------


def test_delete_removes_the_record_and_returns_the_marker() -> None:
    records = FakeRecords(_person("confirmed"))
    resolved = _apply(records, "delete")
    assert isinstance(resolved, GonePerson) and resolved.id == "p-aria"
    assert records.deleted == ["p-aria"]
    assert records.saves == []


# -- the decision itself ----------------------------------------------------


def test_an_unknown_decision_is_refused() -> None:
    """At the door: the closed set is checked when the determination is made,
    so an unknown decision cannot pass quietly through a record that is not
    there (the ladder would otherwise return None before reaching any arm)."""
    records = FakeRecords()
    with pytest.raises(ValueError, match="unknown decision"):
        _apply(records, "promote")
    assert (records.saves, records.deleted) == ([], [])


def test_a_place_is_confirmed_on_the_version_it_read() -> None:
    """The ladder is generic over the two record kinds: a place's status and
    basis go through the same arms, and `_status` reads the same field — so the
    Place arm is pinned here, not only through `Identities.resolve_place`."""
    place = Place.from_dict({"id": "pl-marlock", "name": "Marlock", "status": "proposed"})
    places: FakeRecords[Place] = FakeRecords(place)

    resolved = Determination("attested").apply(places, "pl-marlock", gone=GonePlace)

    assert isinstance(resolved, Place)
    assert resolved.status == "confirmed"
    assert resolved.basis == {"basis": "knowledge", "confidence": "certain"}
    assert places.saves == [(resolved, 0)]
