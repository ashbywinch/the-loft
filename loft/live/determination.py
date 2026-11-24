"""The review's determination — one decision, applied to the record as it stands.

The words have one owner each: a **decision** is `Decision` (one of the four,
written to `review_decisions.decision`), the record's **status** is its own
field (`proposed`/`confirmed`/`rejected`, what `_status` reads), and the
migration's mapping between the old and target outcomes is
`decision_disposition` in `review_map`.

TECHSPEC/05 §18.2: ``attested`` confirms; ``estimated`` confirms on the
reviewer's own recollection (``estimated`` is a rendering, not a status);
``pending`` decides nothing; ``delete`` ends the record and its edges. A
rejected proposal is terminal, and a determination that leaves the record
identical writes nothing. One implementation for every identity collection:
the collections differ in how they store a record, never in what a decision
means.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal, Protocol, TypeVar, cast, get_args

from loft.live.identity_map import BasisKinds, basis_after, renders_estimated
from tools.records import Person, Place, RecordStatus

Record = TypeVar("Record", bound=Person | Place)
Marker = TypeVar("Marker")

#: The reviewer's four decisions — the closed set the review offers.
Decision = Literal["attested", "estimated", "pending", "delete"]
DECISIONS = get_args(Decision)  # the same four, spelled once
#: The two decisions that confirm a record; `_confirm` takes only these, so an
#: unknown decision is not a value it can be handed.
Attestation = Literal["attested", "estimated"]


@dataclass(frozen=True)
class Resolved[Kept: Person | Place]:
    """A determination's answer when there was a record to apply it to: the
    record as it stands — unchanged when the decision changed nothing, the
    saved one when it did."""

    record: Kept


@dataclass(frozen=True)
class Removed[Marker]:
    """A delete determination's answer: the marker naming the record that left
    the collection. It holds a marker, never a record, so a caller cannot read
    a deleted record out of it."""

    marker: Marker


@dataclass(frozen=True)
class Absent:
    """The collection holds no such record: nothing was applied and nothing
    was written — a decision for an unknown id is not an error."""

    record_id: str


#: What one determination answers: a record that stands, a record that was
#: removed, or no record at all. Three cases, named, so a caller never reads
#: ``None`` as "unchanged" or as "deleted".
Outcome = Resolved[Record] | Removed[Marker] | Absent


class IdentityRecords(Protocol[Record]):
    """What a determination needs from an identity collection — the collection
    holding a person or a place.

    The three verbs are the identity repositories' shared surface (`People`,
    `Collection`, and the memory store's twin), so the determination's
    vocabulary travels, not a class. `get` returns the record the projection
    holds or ``None``: a ``GonePerson``/``GonePlace`` is what ``gone()`` makes
    and is never stored, so the type leaves no way for a delete marker to
    reach `_status`. The record and id are positional-only: each collection
    names them for its own kind (`person_id`, `entity_id`)."""

    def get(self, record_id: str, /) -> Record | None: ...

    def save(self, record: Record, /, base: int | None = None) -> Record: ...

    def delete(self, record_id: str, /) -> None: ...


class Determination:
    """One reviewer decision, applied to a record: attested, estimated, pending
    or delete — the ladder every identity collection reads through."""

    def __init__(self, decision: str, basis: dict[str, str] | None = None) -> None:
        """One decision and its basis. The decision crosses JSON at the API, so
        the closed set is checked at the door: an unknown decision is refused
        here, whatever record the determination is later applied to."""
        if decision not in DECISIONS:
            raise ValueError(f"unknown decision: {decision!r}")
        self.decision: Decision = cast(Decision, decision)  # the check above is the proof
        self.basis = basis

    def apply(
        self, records: IdentityRecords[Record], record_id: str, *, gone: Callable[[str], Marker]
    ) -> Outcome[Record, Marker]:
        """The determination applied to the record as it stands — one of
        `Outcome`'s three named cases: `Resolved` (the record, written or
        unchanged), `Removed` (the delete's marker) or `Absent` (no such
        record, nothing written).

        ``records`` is typed by `IdentityRecords`: the ladder can only ever
        read a record the projection holds (or ``None``), so the delete marker
        in `Removed` cannot come back in through `get`. Every arm below names
        its answer, so no case is spelled ``None``."""
        current = records.get(record_id)
        if current is None:
            return Absent(record_id)
        if _status(current) == "rejected":
            return Resolved(current)  # a rejected proposal is terminal (TECHSPEC/05 §18.2)
        decision = self.decision
        if decision == "pending":
            return Resolved(current)
        if decision == "delete":
            records.delete(record_id)
            return Removed(gone(record_id))
        confirmed = self._confirm(current, decision, record_id)
        if confirmed == current:
            return Resolved(current)
        return Resolved(records.save(confirmed, base=current.version))

    def _confirm(self, current: Record, decision: Attestation, record_id: str) -> Record:
        """The record after an attested/estimated determination — the record
        itself when the decision leaves it as it stands.

        The decision is `Attestation`, not `Decision`: the two arms that write
        nothing or a delete are settled by the caller, so the only refusal left
        here is an estimate without a basis."""
        if decision == "attested":
            if current.status != "proposed" and not renders_estimated(current.basis):
                return current
            return replace(current, status="confirmed", basis=basis_after(current.basis, BasisKinds.KNOWN))
        if self.basis is None or not str(self.basis.get("text", "")).strip():
            raise ValueError(f"estimated needs a basis: {record_id}")
        return replace(
            current,
            status="confirmed",
            basis=basis_after(current.basis, BasisKinds.RECOLLECTED, self.basis),
        )


def _status(record: Person | Place) -> RecordStatus:
    """The record's status — the record's own field, already a closed set.

    The wire may omit a status (`Person.to_dict` omits ``confirmed``); that is
    the parser's seam, and `Person.from_dict`/`Place.from_dict` fill it there.
    Reading `to_dict()` here would put a default back in front of a field that
    cannot be absent."""
    return record.status
