"""The review's determination — one decision, applied to the record as it stands.

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
from dataclasses import replace
from typing import Protocol, TypeVar

from loft.live.identity_map import BasisKinds, basis_after, renders_estimated
from tools.records import Person, Place

Record = TypeVar("Record", bound=Person | Place)
Gone = TypeVar("Gone")


class Records(Protocol[Record]):
    """What a determination needs from the collection holding the record.

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
    """One reviewer decision — the four dispositions shared by every record."""

    def __init__(self, decision: str, basis: dict[str, str] | None = None) -> None:
        self.decision = decision
        self.basis = basis

    def apply(self, records: Records[Record], record_id: str, *, gone: Callable[[str], Gone]) -> Record | Gone | None:
        """The determination applied to the record as it stands — the updated
        record, the ``gone`` marker for a delete, or the record unchanged.

        ``records`` is typed by `Records`: the ladder can only ever read a
        record the projection holds (or ``None``), so the delete marker this
        method returns cannot come back in through `get`."""
        current = records.get(record_id)
        if current is None or _status(current) == "rejected":
            return current  # a rejected proposal is terminal (TECHSPEC/05 §18.2)
        if self.decision == "pending":
            return current
        if self.decision == "delete":
            records.delete(record_id)
            return gone(record_id)
        updated = self._confirmed(current, record_id)
        if updated is None or updated == current:
            return current
        return records.save(updated, base=current.version)

    def _confirmed(self, current: Record, record_id: str) -> Record | None:
        """The record after an attested/estimated determination — None when the
        decision leaves an already-confirmed record as it stands."""
        if self.decision == "attested":
            if current.status != "proposed" and not renders_estimated(current.basis):
                return None
            return replace(current, status="confirmed", basis=basis_after(current.basis, BasisKinds.KNOWN))
        if self.decision == "estimated":
            if self.basis is None or not str(self.basis.get("text", "")).strip():
                raise ValueError(f"estimated needs a basis: {record_id}")
            return replace(
                current,
                status="confirmed",
                basis=basis_after(current.basis, BasisKinds.RECOLLECTED, self.basis),
            )
        raise ValueError(f"unknown decision: {self.decision!r}")


def _status(record: Person | Place) -> str:
    """The record's disposition — a missing status is an asserted record."""
    return str(record.to_dict().get("status", "confirmed"))
