"""The review's determination — one decision, applied to the record as it stands.

The four decisions, and the edges that decide whether anything is written
at all. `tests/live/test_identity_writes.py` drives the same ladder through
the collections on both stores; this suite names the class that holds it, so
a change to the shared ladder fails here by name rather than three times
through its callers.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from loft.live.determination import Determination
from loft.live.identity_map import renders_estimated
from tools.gone_person import GonePerson
from tools.records import Person


class FakeRecords:
    """One person in a dict — the three verbs `Determination` uses, and a log
    of what it was asked to write."""

    def __init__(self, *people: Person) -> None:
        self.rows = {person.id: person for person in people}
        self.saves: list[tuple[Person, int | None]] = []
        self.deleted: list[str] = []

    def get(self, record_id: str) -> Person | None:
        return self.rows.get(record_id)

    def save(self, record: Person, base: int | None = None) -> Person:
        self.saves.append((record, base))
        self.rows[record.id] = record
        return record

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


def test_an_unknown_record_is_left_alone() -> None:
    records = FakeRecords()
    assert _apply(records, "attested") is None
    assert (records.saves, records.deleted) == ([], [])


def test_a_confirmed_record_carries_no_status_and_still_reads_confirmed() -> None:
    """The wire's own rule: `Person.to_dict` omits `status` for a confirmed
    record (the class docstring's "the status appears only when proposed"), so
    the absence *is* the answer — and a rejected record never omits it, so the
    ladder cannot revive one by reading a missing status."""
    confirmed = Person.from_dict({"id": "p-aria", "name": "Aria Barlow"})
    assert "status" not in confirmed.to_dict()
    records = FakeRecords(confirmed)
    resolved = _apply(records, "attested")
    assert isinstance(resolved, Person) and resolved.status == "confirmed"
    assert records.saves == []

    rejected = Person.from_dict({"id": "p-aria", "name": "Aria Barlow", "status": "rejected"})
    assert rejected.to_dict()["status"] == "rejected"
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


def test_renders_estimated_is_total_on_a_missing_basis() -> None:
    """The attested branch asks this of every record, so `None` must answer
    False rather than raise — a record with no basis is not an estimate."""
    assert renders_estimated(None) is False
