"""A document's identified entities — stage 7's result, the stage-8 review's input.

The identification pass reads an agreed document's text for the people and
places it names; this record is its answer: every record the document names,
existing (matched against the standing knowledge) or freshly proposed, in the
order the pass resolved them. The item's refs are one per record, proposed;
the review agrees them (stage 8). Its wire form is this class's dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.records import Person, Place
from tools.ref import Ref


@dataclass(frozen=True)
class Identification:
    """One document's people and places, as the pass read them."""

    item_id: str
    people: tuple[Person, ...] = ()
    places: tuple[Place, ...] = ()

    def people_refs(self) -> tuple[Ref, ...]:
        """The item's people links — one proposed ref per identified person."""
        return tuple(Ref(person.id, "proposed") for person in self.people)

    def place_refs(self) -> tuple[Ref, ...]:
        """The item's place links — one proposed ref per identified place."""
        return tuple(Ref(place.id, "proposed") for place in self.places)

    def to_dict(self) -> dict[str, Any]:
        """The identification as its wire record."""
        return {
            "item_id": self.item_id,
            "people": [person.to_dict() for person in self.people],
            "places": [place.to_dict() for place in self.places],
        }
