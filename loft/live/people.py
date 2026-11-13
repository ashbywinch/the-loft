"""The people collection — the repository both the store and a change expose.

TECHSPEC/08 §19.4: `store.people` reads current state; `change.people` writes
inside the change. One class owns both halves, so the collection has one name
and the write half cannot be used outside a transaction.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from loft.live import person_row
from loft.live.aliases import Aliases
from loft.live.errors import Conflict, NotFound, StaleVersion
from loft.live.identity import relationship_id
from loft.live.identity_map import BasisKinds, basis_after, renders_estimated
from tools.gone_person import GonePerson
from tools.records import Person

if TYPE_CHECKING:
    from loft.live.change import Change


class People:
    """The person collection: read through the store, write through a change."""

    def __init__(self, connection: sqlite3.Connection, change: Change | None = None) -> None:
        self.connection = connection
        self.change = change
        self.aliases = Aliases(connection)

    def get(self, person_id: str) -> Person | None:
        return person_row.read_row(self.connection, person_id)

    def all(self) -> tuple[Person, ...]:
        """Every person in the archive's own order — the create sequence, so a
        supersede keeps its position (B1's compatibility export preserves the
        curated cast order)."""
        rows = self.connection.execute(
            """SELECT p.person_id FROM people p
               LEFT JOIN (SELECT entity_id, MIN(seq) AS first_seq FROM events
                          WHERE entity_kind = 'person' GROUP BY entity_id) e
                 ON e.entity_id = p.person_id
               ORDER BY COALESCE(e.first_seq, 0), p.person_id"""
        ).fetchall()
        return tuple(self.require(row["person_id"]) for row in rows)

    def require(self, person_id: str) -> Person:
        person = self.get(person_id)
        if person is None:
            raise NotFound(f"no person {person_id}")
        return person

    def save(self, person: Person, base: int | None = None) -> Person:
        """Write a create (base None) or a supersede, version-checked."""
        if self.change is None:
            raise Conflict("people.save needs a change")
        current = self.get(person.id)
        if base is None:
            if current is not None:
                raise Conflict(f"person {person.id} exists")
            event_type = "created"
            version = 1
        else:
            if current is None:
                raise NotFound(f"no person {person.id}")
            if current.version != base:
                raise StaleVersion(current=current, base=base)
            event_type = "superseded"
            version = base + 1
        payload = json.dumps(person.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        event = self.change.append(
            entity_kind="person",
            entity_id=person.id,
            event_type=event_type,
            entity_version=version,
            payload=payload,
        )
        saved = replace(person, version=version)
        person_row.write_row(
            self.connection,
            saved,
            person_row.RowPosition(
                version=version,
                event_no=event["event_no"],
                event_seq=event["seq"],
                updated_at=event["recorded_at"],
            ),
            base=base,
        )
        return saved

    # -- the identity verbs (TECHSPEC/08 §19.4) -----------------------------

    def confirm(self, person_id: str, relation: str | None = None) -> Person:
        """A proposal the review confirmed: the record keeps its evidence and
        drops ``proposed``. Confirming a confirmed person writes nothing —
        there is no byte-identical version to add."""
        current = self.require(person_id)
        if current.status != "proposed":
            return current
        updated = replace(current, status="confirmed")
        if relation:
            updated = replace(updated, relation=relation)
        return self.save(updated, base=current.version)

    def promote(self, person_id: str) -> Person:
        """A queued proposal joins the table as confirmed; a confirmed record
        is a contradiction, never a silent no-op."""
        current = self.require(person_id)
        if current.status != "proposed":
            raise Conflict(f"person {person_id} is {current.status}, not a proposal")
        return self.save(replace(current, status="confirmed"), base=current.version)

    def resolve(self, person_id: str, decision: str, basis: dict[str, str] | None = None) -> Person | GonePerson | None:
        """One review determination, applied to the record as it stands.

        ``attested`` confirms; ``estimated`` confirms with the reviewer's own
        recollection (``estimated`` is a rendering, not a status);
        ``pending`` changes nothing; ``delete`` removes the record and its
        edges. A determination that leaves the record identical writes
        nothing; a determination for an id the table does not hold returns
        None (TECHSPEC/05 §18.2).
        """
        current = self.get(person_id)
        if current is None or current.status == "rejected":
            return current  # a rejected proposal is terminal (TECHSPEC/05 §18.2)
        if decision == "pending":
            return current
        if decision == "delete":
            self.delete(person_id)
            return GonePerson(person_id)
        if decision == "attested":
            if current.status != "proposed" and not renders_estimated(current.basis):
                return current
            return self._save_if_changed(
                current, replace(current, status="confirmed", basis=basis_after(current.basis, BasisKinds.KNOWN))
            )
        if decision == "estimated":
            if basis is None or not str(basis.get("text", "")).strip():
                raise ValueError(f"estimated needs a basis: {person_id}")
            return self._save_if_changed(
                current,
                replace(current, status="confirmed", basis=basis_after(current.basis, BasisKinds.RECOLLECTED, basis)),
            )
        raise ValueError(f"unknown decision: {decision!r}")

    def reject(self, person_id: str) -> Person:
        """End a proposal: the row stays marked ``rejected`` (terminal) and
        its edges end, so no browse or reference resolves it."""
        current = self.require(person_id)
        if current.status != "proposed":
            raise Conflict(f"person {person_id} is {current.status}, not a proposal")
        rejected = replace(current, status="rejected")
        self._write_event(rejected, "rejected")
        self._delete_edges(person_id)
        return rejected

    def delete(self, person_id: str) -> None:
        """Remove the record from the projection — the import review's
        ``delete``. The log keeps the record it deletes; its edges go too."""
        current = self.require(person_id)
        self._write_event(current, "deleted")
        person_row.delete_row(self.connection, person_id)
        self._delete_edges(person_id)

    def merge(self, loser_id: str, survivor_id: str, by: str) -> Person:
        """Merge one person id into another: a ``merged`` event names the
        survivor and the alias projection redirects the loser. The loser's
        row stays for the log; readers resolve it away through ``aliases``."""
        if loser_id == survivor_id:
            raise Conflict("a record cannot merge into itself")
        survivor = self.require(survivor_id)
        loser = self.require(loser_id)
        event = self._write_event(
            loser,
            "merged",
            extra={"merged_into": survivor_id, "by": by},
        )
        self.aliases.write(
            loser_kind="person",
            loser_id=loser_id,
            survivor_kind="person",
            survivor_id=survivor_id,
            event_seq=event["seq"],
        )
        self._move_edges(loser_id, survivor_id)
        return survivor

    def _move_edges(self, loser_id: str, survivor_id: str) -> None:
        """A merged person's edges follow the survivor: the old edge ends and
        its re-pointed twin is created in the same change."""
        relationships = self._change().relationships
        for edge in list(relationships.all()):
            if loser_id not in (edge.a, edge.b):
                continue
            moved = replace(
                edge,
                a=survivor_id if edge.a == loser_id else edge.a,
                b=survivor_id if edge.b == loser_id else edge.b,
            )
            relationships.delete(relationship_id(edge))
            relationships.save(moved)

    def _write_event(self, person: Person, event_type: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """One version advance of the person's own state, projected."""
        change = self._change()
        version = person.version + 1
        record = replace(person, version=version)
        payload_record = {"person": record.to_dict(), **(extra or {})} if event_type == "merged" else record.to_dict()
        event = change.append(
            entity_kind="person",
            entity_id=person.id,
            event_type=event_type,
            entity_version=version,
            payload=json.dumps(payload_record, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        )
        person_row.write_row(
            self.connection,
            record,
            person_row.RowPosition(
                version=version,
                event_no=event["event_no"],
                event_seq=event["seq"],
                updated_at=event["recorded_at"],
            ),
            base=person.version,
        )
        return event

    def _save_if_changed(self, current: Person, updated: Person) -> Person:
        if updated == current:
            return current
        return self.save(updated, base=current.version)

    def _delete_edges(self, person_id: str) -> None:
        change = self._change()
        for edge in change.relationships.all():
            if person_id in (edge.a, edge.b):
                change.relationships.delete(relationship_id(edge))

    def _change(self) -> Change:
        if self.change is None:
            raise Conflict("people needs a change")
        return self.change
