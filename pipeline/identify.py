"""The identification pass (stage 7): an agreed document's text read for the
people and places it names.

The pass is the machine's reading, proposed for the stage-8 review (UR1 7→8):
the model names the entities, and this module resolves each name against the
standing knowledge — a known person or place is linked to its record, an
unknown one becomes a proposed record carrying the document's own words. The
model never asserts a relationship or a fact: the review asks the family.
"""

from __future__ import annotations

import re
from typing import Any

from pipeline.identification import Identification
from pipeline.mention import Mention
from pipeline.model.ai_client import AIClientError, json_object
from tools.memory import ChatClient, Knowledge
from tools.records import Item, Person, Place


class IdentificationError(RuntimeError):
    """Raised when the identification cannot be produced or is malformed."""


def _entries(parsed: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """One list of the model's answer, each entry carrying its kind — the
    list's key is what makes an entry a person or a place."""
    raw = parsed.get(key)
    if not isinstance(raw, list):
        return []
    kind = "person" if key == "people" else "place"
    return [{"kind": kind, **entry} for entry in raw if isinstance(entry, dict)]


def _slug(name: str) -> str:
    """An id fragment from a name — lowercase letters, digits and hyphens."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:40] or "new"


class Identifier:
    """The pass over one agreed document: the model's mentions, resolved
    against the standing knowledge, as the records the review will agree.

    One class, because the model call and the resolution are one reading with
    one standing knowledge and one id space (docs/coding-standards.md: groups
    that travel together are a type).
    """

    max_people = 40
    max_places = 25
    system = """\
You read one document's transcription for a private family archive and list \
the people and places it names.

Return ONLY this JSON: {"people": [{"name": string, "match": string|null, \
"quote": string}], "places": [{"name": string, "match": string|null, \
"quote": string}]}

- "name" is the name as the document uses it.
- "match" is the id of the standing record the name refers to, or null.
- "quote" is the document's own words that name the entity — never a
  paraphrase.
- Do not list a name the document does not contain.
- Do not match a bare kinship term ("Mum", "Dad", "Gran", "Auntie") to a
  record: the family's own word does not identify the person.
- Do not match on the name alone when the match is uncertain — an unmatched
  name becomes a proposal to create a record, which the family reviews.
- Do not infer a relationship between two people, and do not add a fact the
  document does not state.
- Do not list the same entity twice.
"""

    def __init__(self, *, item: Item, text: str, knowledge: Knowledge) -> None:
        self._item = item
        self._text = text
        self._knowledge = knowledge
        self._used = {person.id for person in knowledge.people} | {place.id for place in knowledge.places}

    def read(self, client: ChatClient) -> Identification:
        """The document's people and places, or a loud IdentificationError —
        a malformed answer never reaches the archive."""
        try:
            parsed = json_object(client.chat(self.system, self._context()))
        except AIClientError as e:
            raise IdentificationError(f"identification failed: {e}") from e
        if not isinstance(parsed, dict):
            raise IdentificationError(f"identification is not an object: {parsed!r}")
        mentions = Mention.from_list(_entries(parsed, "people")) + Mention.from_list(_entries(parsed, "places"))
        people: dict[str, Person] = {}
        places: dict[str, Place] = {}
        for mention in mentions:
            if mention.kind == "person":
                person = self._person(mention)
                people.setdefault(person.id, person)
            else:
                place = self._place(mention)
                places.setdefault(place.id, place)
        return Identification(
            item_id=self._item.id,
            people=tuple(people.values())[: self.max_people],
            places=tuple(places.values())[: self.max_places],
        )

    def _context(self) -> str:
        return "\n\n".join(
            [
                f"The document: {self._item.title or self._item.id} ({self._item.date}).",
                "Standing knowledge:\n" + self._knowledge.render(),
                "The document's text, verbatim:\n" + self._text,
            ]
        )

    def _person(self, mention: Mention) -> Person:
        """The record a person mention names: the model's match, a standing
        record named the same, or a proposed record minted for the review.
        A kinship term is never resolved to a standing record — the alias
        could be the wrong relative — but two documents mentioning the same
        "Gran" share ONE proposed record."""
        matched = self._matched(mention)
        if isinstance(matched, Person):
            return matched
        return Person(
            id=self._unique_id("p", _slug(mention.name)),
            name=mention.name,
            relation=f"Mentioned in {self._item.title or self._item.id}",
            status="proposed",
            basis=self._basis(mention),
        )

    def _place(self, mention: Mention) -> Place:
        """The record a place mention names: the model's match, a standing
        place named the same, or a proposed record minted for the review."""
        matched = self._matched(mention)
        if isinstance(matched, Place):
            return matched
        return Place(
            id=self._unique_id("pl", _slug(mention.name)),
            name=mention.name,
            note=f"Mentioned in {self._item.title or self._item.id} — location unknown.",
            status="proposed",
            basis=self._basis(mention),
        )

    def _matched(self, mention: Mention) -> Person | Place | None:
        """The standing record a mention already names — the model's match
        when it holds, else the record named the same. A bare kinship term
        resolves to nothing, and neither does a name the archive lacks."""
        if mention.kind == "person" and mention.is_kinship_term():
            return None
        if mention.match:
            matched = (
                self._knowledge.person(mention.match)
                if mention.kind == "person"
                else self._knowledge.place(mention.match)
            )
            if matched is not None:
                return matched
        if mention.kind == "person":
            return self._knowledge.person_named(mention.name)
        return self._knowledge.place_named(mention.name)

    def _basis(self, mention: Mention) -> dict[str, str]:
        """The proposal's evidence — the document's words, its name and its
        date. A mention the model did not quote still carries the name it
        read; the review reads the text beside it."""
        return {"text": mention.quote or mention.name, "by": "the document", "when": self._item.date}

    def _unique_id(self, prefix: str, slug: str) -> str:
        """The next free id for the slug — the id is minted once and never
        changes."""
        candidate = f"{prefix}-{slug}"
        if candidate not in self._used:
            self._used.add(candidate)
            return candidate
        n = 2
        while f"{candidate}-{n}" in self._used:
            n += 1
        unique = f"{candidate}-{n}"
        self._used.add(unique)
        return unique


def identify(client: ChatClient, *, item: Item, text: str, knowledge: Knowledge) -> Identification:
    """Read one agreed document's text for the people and places it names.
    The module's face over `Identifier`, which owns the model call and the
    resolution."""
    return Identifier(item=item, text=text, knowledge=knowledge).read(client)
