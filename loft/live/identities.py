"""The identity service — one change per review action (TECHSPEC/08 §19.4).

The archive facade's identity verbs move here: confirm, resolve, reject,
promote and merge. Each method opens exactly one `Change`, so one action is
one change, its events and its projection rows; the caller never sees a
partial action (TECHSPEC/05 §18.5). `estimated` is a rendering of a confirmed
record with a recollection basis, not a status (TECHSPEC/05 §18.2).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from loft.live.errors import Conflict
from loft.live.identity_map import BasisKinds, basis_after, renders_estimated
from loft.live.protocols import IdentityStore
from tools.gone_person import GonePerson
from tools.gone_place import GonePlace
from tools.records import Person, Place


class Identities:
    """The identity write surface: the review's verbs, each one change."""

    def __init__(self, store: IdentityStore) -> None:
        self.store = store

    # -- reads -------------------------------------------------------------

    def person(self, person_id: str) -> Person | None:
        with self.store.lock:
            return self.store.people.get(person_id)

    def place(self, place_id: str) -> Place | None:
        with self.store.lock:
            return self.store.places.get(place_id)

    # -- the review's determinations ---------------------------------------

    def confirm_person(self, person_id: str, relation: str | None = None, *, actor: str) -> Person:
        with self.store.change(actor=actor, note=f"confirm {person_id}") as change:
            return change.people.confirm(person_id, relation)

    def resolve_person(
        self, person_id: str, decision: str, basis: dict[str, str] | None = None, *, actor: str
    ) -> Person | GonePerson | None:
        with self.store.change(actor=actor, note=f"{decision} {person_id}") as change:
            return change.people.resolve(person_id, decision, basis)

    def resolve_place(
        self, place_id: str, decision: str, basis: dict[str, str] | None = None, *, actor: str
    ) -> Place | GonePlace | None:
        with self.store.change(actor=actor, note=f"{decision} {place_id}") as change:
            current = change.places.get(place_id)
            if current is None:
                return None
            if decision == "pending":
                return current
            if decision == "delete":
                change.places.delete(place_id)
                return GonePlace(place_id)
            if decision == "attested":
                if current.status != "proposed" and not renders_estimated(current.basis):
                    return current
                updated = replace(current, status="confirmed", basis=basis_after(current.basis, BasisKinds.KNOWN))
            elif decision == "estimated":
                if basis is None or not str(basis.get("text", "")).strip():
                    raise ValueError(f"estimated needs a basis: {place_id}")
                updated = replace(
                    current, status="confirmed", basis=basis_after(current.basis, BasisKinds.RECOLLECTED, basis)
                )
            else:
                raise ValueError(f"unknown decision: {decision!r}")
            return current if updated == current else change.places.save(updated, base=current.version)

    def reject_person(self, person_id: str, *, actor: str) -> Person:
        with self.store.change(actor=actor, note=f"reject {person_id}") as change:
            self._refuse_referenced(change, person_id, "person")
            return change.people.reject(person_id)

    def reject_place(self, place_id: str, *, actor: str) -> Place:
        with self.store.change(actor=actor, note=f"reject {place_id}") as change:
            self._refuse_referenced(change, place_id, "place")
            return change.places.reject(place_id)

    def promote_person(self, person_id: str, *, actor: str) -> Person:
        with self.store.change(actor=actor, note=f"promote {person_id}") as change:
            return change.people.promote(person_id)

    def promote_place(self, place_id: str, *, actor: str) -> Place:
        with self.store.change(actor=actor, note=f"promote {place_id}") as change:
            return change.places.promote(place_id)

    # -- merge -------------------------------------------------------------

    def merge_people(self, loser_id: str, survivor_id: str, *, by: str, actor: str) -> Person:
        """Merge one id into another. A catalogued item still naming the
        loser is refused: re-pointing item refs is the item write path (B2),
        and a dangling ref would fail the old publish."""
        with self.store.change(actor=actor, note=f"merge {loser_id} into {survivor_id}") as change:
            self._refuse_referenced(change, loser_id, "person")
            return change.people.merge(loser_id, survivor_id, by)

    # -- the identification pass's proposals -------------------------------

    def propose(self, *, people: tuple[Person, ...] = (), places: tuple[Place, ...] = (), actor: str) -> int:
        """Write the pass's newly minted proposals in one change — the tables
        first, so a crash leaves proposals nothing references."""
        written = 0
        with self.store.change(actor=actor, note="identification proposals") as change:
            for person in people:
                if change.people.get(person.id) is None:
                    change.people.save(replace(person, status="proposed"))
                    written += 1
            for place in places:
                if change.places.get(place.id) is None:
                    change.places.save(replace(place, status="proposed"))
                    written += 1
        return written

    # -- guards ------------------------------------------------------------

    def _refuse_referenced(self, change: Any, record_id: str, kind: str) -> None:
        """A record a catalogued item still names is refused: relink the
        stories first (the old reject seam's rule, kept for the new one)."""
        attribute = {"person": "people_refs", "place": "place_refs"}[kind]
        referrers = [
            item.id
            for item in change.items.all()
            if item.status == "catalogued" and any(ref.id == record_id for ref in getattr(item, attribute, ()))
        ]
        if referrers:
            raise Conflict(
                f"cannot delete {kind} {record_id}: catalogued stories still reference it "
                f"({', '.join(sorted(referrers))}) — relink the stories or keep the record"
            )
