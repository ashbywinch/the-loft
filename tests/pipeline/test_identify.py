"""The identification pass (stage 7): a document's text read for the people
and places it names, resolved against the standing knowledge."""

from __future__ import annotations

import json

import pytest

from pipeline.identify import IdentificationError, identify
from tools.memory import Knowledge
from tools.records import Item, Person, Place


def _item(**overrides: object) -> Item:
    """An agreed document — the pass's input."""
    defaults: dict[str, object] = {
        "id": "doc-1971-05-01",
        "type": "document",
        "title": "A letter from Fern",
        "date": "1971-05-01",
        "date_precision": "exact",
        "status": "catalogued",
        "assets": [],
        "people": [],
        "places": [],
        "themes": [],
    }
    defaults.update(overrides)
    return Item.from_dict(defaults)


class FakeChat:
    """The model seam — the answer the pass parses."""

    def __init__(self, answer: object) -> None:
        self._answer = answer
        self.calls: list[tuple[str, str]] = []

    def chat(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self._answer if isinstance(self._answer, str) else json.dumps(self._answer)


def _knowledge(people: tuple[Person, ...] = (), places: tuple[Place, ...] = ()) -> Knowledge:
    return Knowledge(people=people, places=places)


FERN = Person.from_dict({"id": "p-fern", "name": "Fern", "aliases": ["mamie"]})
MARLOCK = Place.from_dict({"id": "pl-marlock", "name": "Marlock"})


def test_a_known_name_links_its_record_and_mints_nothing() -> None:
    """Rule A (propose when obvious): a name the archive holds is linked to
    its record — the review still agrees the mention, but no second record
    is proposed."""
    client = FakeChat({"people": [{"name": "Fern", "match": "p-fern", "quote": "Dear Fern"}]})
    identification = identify(client, item=_item(), text="Dear Fern", knowledge=_knowledge((FERN,)))

    assert [person.id for person in identification.people] == ["p-fern"]
    assert identification.people[0] is FERN
    assert identification.people_refs()[0].status == "proposed"


def test_an_unknown_name_becomes_a_proposed_record_with_the_documents_words() -> None:
    """A name the archive lacks is proposed — never asserted — and carries
    the document's own quote as its evidence."""
    client = FakeChat(
        {
            "people": [{"name": "Owen", "match": None, "quote": "tell Owen I saw the boat"}],
            "places": [{"name": "Mallowfield", "match": None, "quote": "we swam at Mallowfield"}],
        }
    )
    identification = identify(client, item=_item(), text="tell Owen I saw the boat", knowledge=_knowledge())

    assert [(person.id, person.status) for person in identification.people] == [("p-owen", "proposed")]
    assert identification.people[0].basis == {
        "text": "tell Owen I saw the boat",
        "by": "the document",
        "when": "1971-05-01",
    }
    assert [(place.id, place.status) for place in identification.places] == [("pl-mallowfield", "proposed")]
    assert identification.places[0].basis is not None
    assert identification.places[0].basis["text"] == "we swam at Mallowfield"


def test_a_kinship_term_is_never_matched_to_a_record() -> None:
    """A bare kinship term is the family's own word, not an identity: the
    alias on a record does not make "Mum" that person. The term is proposed
    as a record of its own (no id collision with the standing one)."""
    mum = Person.from_dict({"id": "p-mum", "name": "Mum"})
    client = FakeChat({"people": [{"name": "Mum", "match": "p-mum", "quote": "Mum said"}]})
    identification = identify(client, item=_item(), text="Mum said", knowledge=_knowledge((mum,)))

    person = identification.people[0]
    assert person.id == "p-mum-2"
    assert person.status == "proposed"


def test_a_match_the_archive_does_not_hold_falls_back_to_the_name() -> None:
    """The model can name a record id that does not exist; the name's own
    record wins, never a dangling id."""
    client = FakeChat({"people": [{"name": "Fern", "match": "p-ghost", "quote": "Fern"}]})
    identification = identify(client, item=_item(), text="Fern", knowledge=_knowledge((FERN,)))

    assert [person.id for person in identification.people] == ["p-fern"]


def test_two_documents_naming_one_place_share_the_proposed_record() -> None:
    """The standing knowledge the pass reads carries the proposals already
    made, so a second document reuses the same record — one place, one id."""
    proposed = Place.from_dict({"id": "pl-mallowfield", "name": "Mallowfield", "status": "proposed"})
    client = FakeChat({"places": [{"name": "Mallowfield", "match": None, "quote": "Mallowfield"}]})
    identification = identify(client, item=_item(), text="Mallowfield", knowledge=_knowledge(places=(proposed,)))

    assert [place.id for place in identification.places] == ["pl-mallowfield"]


def test_a_malformed_answer_fails_loudly() -> None:
    with pytest.raises(IdentificationError, match="identification failed"):
        identify(FakeChat("[]"), item=_item(), text="x", knowledge=_knowledge())


def test_the_prompt_names_the_document_and_its_standing_knowledge() -> None:
    client = FakeChat({"people": [], "places": []})
    identify(client, item=_item(), text="Dear Fern,", knowledge=_knowledge((FERN,)))

    system, user = client.calls[0]
    assert "Do not list a name the document does not contain." in system
    assert "A letter from Fern (1971-05-01)" in user
    assert "p-fern — Fern" in user
    assert "Dear Fern," in user
