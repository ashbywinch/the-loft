"""The mention record — one entity a document's text names, as the pass
proposes it."""

from __future__ import annotations

import pytest

from pipeline.mention import Mention


def test_a_mention_round_trips_its_wire_record() -> None:
    mention = Mention.from_dict({"kind": "place", "name": "Seascale", "match": "pl-seascale", "quote": "at Seascale"})
    assert mention.to_dict() == {
        "kind": "place",
        "name": "Seascale",
        "match": "pl-seascale",
        "quote": "at Seascale",
    }


def test_a_mention_needs_a_known_kind_and_a_name() -> None:
    with pytest.raises(ValueError, match="known kind and a name"):
        Mention.from_dict({"kind": "org", "name": "The Ministry"})
    with pytest.raises(ValueError, match="known kind and a name"):
        Mention.from_dict({"kind": "person", "name": "   "})


def test_a_list_drops_entries_it_cannot_place() -> None:
    mentions = Mention.from_list(
        [
            {"kind": "person", "name": "Fern"},
            {"kind": "object", "name": "a medal"},
            "not an entry",
            {"kind": "place", "name": "Marlock"},
        ]
    )
    assert [mention.name for mention in mentions] == ["Fern", "Marlock"]


def test_one_entity_is_one_mention() -> None:
    """The model repeating a name must not mint two proposals."""
    mentions = Mention.from_list(
        [{"kind": "person", "name": "Fern"}, {"kind": "person", "name": "fern"}, {"kind": "place", "name": "Fern"}]
    )
    assert [(mention.kind, mention.name) for mention in mentions] == [("person", "Fern"), ("place", "Fern")]


@pytest.mark.parametrize("name", ["Mum", "dad", "GRAN", "auntie"])
def test_a_kinship_term_is_recognised(name: str) -> None:
    assert Mention.from_dict({"kind": "person", "name": name}).is_kinship_term()


def test_a_name_is_recognised_as_a_kinship_term_only_for_people() -> None:
    assert not Mention.from_dict({"kind": "place", "name": "Mum"}).is_kinship_term()
    assert not Mention.from_dict({"kind": "person", "name": "Fern"}).is_kinship_term()
