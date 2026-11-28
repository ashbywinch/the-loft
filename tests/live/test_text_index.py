"""The archive's text index: words, ranked, punctuation-insensitive."""

from __future__ import annotations

from loft.live.text_index import TextIndex

DOCUMENTS = [
    ("war", "Walter Whitlock died on 15 September 1916, aged 21."),
    ("visit", "We visited Walter in Mallowfield once, when the children were young."),
    ("boats", "Dad built the boats at Iron Wharf; Mum came along sometimes."),
]


def index() -> TextIndex:
    return TextIndex(DOCUMENTS)


def test_every_word_must_appear_in_any_order() -> None:
    assert [doc for doc, _ in index().search("walter 1916")] == ["war"]
    assert [doc for doc, _ in index().search("1916 walter")] == ["war"]


def test_words_need_not_be_adjacent() -> None:
    """'walter mallowfield' finds the visit: the words are far apart in the
    text, and a substring test finds nothing."""
    assert [doc for doc, _ in index().search("walter mallowfield")] == ["visit"]


def test_quotes_and_operators_are_punctuation() -> None:
    for query in ('"walter whitlock" died', "walter AND died", "walter or mallowfield"):
        assert index().search(query), query


def test_a_word_in_no_document_matches_nothing() -> None:
    assert index().search("walter 1917") == []


def test_a_query_with_no_words_matches_nothing() -> None:
    assert index().search('   ""  ') == []


def test_ranking_prefers_the_denser_document() -> None:
    docs = [
        ("short", "Walter died."),
        ("long", "The battalion rested all week and the mail arrived late. Walter died on the fifteenth."),
    ]
    ranked = [doc for doc, _ in TextIndex(docs).search("walter died")]
    assert ranked[0] == "short", ranked  # the same two terms in fewer words ranks higher
