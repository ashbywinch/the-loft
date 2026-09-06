"""The document grouping scorer (tools/grouping.py, 2026-08-17).

The evidence hierarchy: duplex sides (photo+text, same paper) > paper
size > page numbers > the model's greeting/sign-off flags. These pin
the deterministic contracts; the guess's flags are the fallback input.
"""

from __future__ import annotations

import pytest

from tools.grouping import first_page_number, paper_aspect, same_paper, score_boundaries


def _kinds(*entries: tuple[str, str]) -> dict[str, str]:
    return dict(entries)


def _flag(page: str, starts: bool = False, ends: bool = False, greeting: str | None = None) -> dict[str, object]:
    return {"page": page, "starts_document": starts, "ends_document": ends, "greeting": greeting}


def test_duplex_pairs_a_photo_with_its_text_side() -> None:
    """A photo page adjacent to a text page of the same paper is the two
    sides of one sheet — one document, the picture side first (VR15,
    acceptance 21)."""
    pages = ["p1.jpg", "p2.jpg"]
    docs = score_boundaries(
        pages,
        _kinds(("p1.jpg", "photo"), ("p2.jpg", "text")),
        {"p1.jpg": (3500, 2333), "p2.jpg": (3500, 2215)},  # aspects 0.667 vs 0.633
        {"p1.jpg": None, "p2.jpg": "POST CARD"},
        {},
    )
    assert len(docs) == 1
    assert docs[0]["pages"] == ["p1.jpg", "p2.jpg"]


def test_duplex_reorders_a_text_side_scanned_first() -> None:
    """The postcard batch scans sides in mixed order — the text side at
    …038221 comes BEFORE the picture side at …077468. The picture side is
    still page 1 (user, 2026-08-17)."""
    pages = ["back.jpg", "front.jpg"]
    docs = score_boundaries(
        pages,
        _kinds(("back.jpg", "text"), ("front.jpg", "photo")),
        {"back.jpg": (3500, 2215), "front.jpg": (2333, 3500)},
        {"back.jpg": "POST CARD", "front.jpg": None},
        {},
    )
    assert len(docs) == 1
    assert docs[0]["pages"] == ["front.jpg", "back.jpg"]


def test_duplex_never_fires_across_different_papers() -> None:
    """A photo print next to a large sheet is not the two sides of one
    sheet — the paper size separates them (no random association)."""
    pages = ["photo.jpg", "letter.jpg"]
    docs = score_boundaries(
        pages,
        _kinds(("photo.jpg", "photo"), ("letter.jpg", "text")),
        {"photo.jpg": (2000, 3000), "letter.jpg": (3500, 1500)},  # 0.667 vs 0.429
        {"photo.jpg": None, "letter.jpg": "Dear X"},
        {},
    )
    assert [d["pages"] for d in docs] == [["photo.jpg"], ["letter.jpg"]]


def test_duplex_greedy_consumes_disjoint_pairs() -> None:
    """[back1, front1, back2, front2] — the between-items adjacency
    (front1, back2) must not pair: each consumed pair leaves no page for
    the wrong neighbour."""
    pages = ["b1.jpg", "f1.jpg", "b2.jpg", "f2.jpg"]
    docs = score_boundaries(
        pages,
        _kinds(("b1.jpg", "text"), ("f1.jpg", "photo"), ("b2.jpg", "text"), ("f2.jpg", "photo")),
        {p: (3500, 2215) for p in pages},
        {p: f"text {p}" if "b" in p else None for p in pages},
        {},
    )
    assert [d["pages"] for d in docs] == [["f1.jpg", "b1.jpg"], ["f2.jpg", "b2.jpg"]]


def test_text_pages_of_different_papers_split() -> None:
    """Different paper sizes = probably not the same document — a
    boundary even when the model flags neither. (The 12% tolerance is
    deliberately soft: phone-scan aspect variance is the same order as
    paper differences, so the test pins the clearly-different case.)"""
    pages = ["a4.jpg", "postcard.jpg"]
    docs = score_boundaries(
        pages,
        _kinds(("a4.jpg", "text"), ("postcard.jpg", "text")),
        {"a4.jpg": (2480, 3508), "postcard.jpg": (3500, 1500)},  # 0.707 vs 0.429
        {"a4.jpg": "page one", "postcard.jpg": "POST CARD"},
        {},
    )
    assert len(docs) == 2


def test_page_number_two_continues_despite_a_model_start_flag() -> None:
    """A page starting "2" continues its document — the page number
    outvotes the model's starts_document flag (evidence priority)."""
    pages = ["p1.jpg", "p2.jpg"]
    docs = score_boundaries(
        pages,
        _kinds(("p1.jpg", "text"), ("p2.jpg", "text")),
        {p: (2480, 3508) for p in pages},
        {"p1.jpg": "Dear X", "p2.jpg": "2"},
        {"p2.jpg": _flag("p2.jpg", starts=True)},  # the model misread it
    )
    assert len(docs) == 1


def test_page_number_one_starts_a_new_document() -> None:
    """A fresh numbered "1" starts a document even when the model said
    continue (the priority order: page numbers before model flags)."""
    pages = ["p1.jpg", "p2.jpg"]
    docs = score_boundaries(
        pages,
        _kinds(("p1.jpg", "text"), ("p2.jpg", "text")),
        {p: (2480, 3508) for p in pages},
        {"p1.jpg": "…mid-letter", "p2.jpg": "1"},
        {},
    )
    assert len(docs) == 2


def test_model_flags_boundary_without_other_evidence() -> None:
    """With no physical cues, the model's greeting/sign-off decide — a
    starts_document page opens a new document."""
    pages = ["a.jpg", "b.jpg"]
    docs = score_boundaries(
        pages,
        _kinds(("a.jpg", "text"), ("b.jpg", "text")),
        {p: (2480, 3508) for p in pages},
        {"a.jpg": "page one", "b.jpg": "Dear Maman"},
        {"b.jpg": _flag("b.jpg", starts=True, greeting="Chère Maman.")},
    )
    assert len(docs) == 2
    assert docs[1]["greeting"] == "Chère Maman."


def test_model_flags_join_without_boundary_cues() -> None:
    """Consecutive same-paper text pages with no boundary cue continue
    the document (a multi-page letter)."""
    pages = ["a.jpg", "b.jpg"]
    docs = score_boundaries(
        pages,
        _kinds(("a.jpg", "text"), ("b.jpg", "text")),
        {p: (2480, 3508) for p in pages},
        {"a.jpg": "page one", "b.jpg": "more of the letter"},
        {},
    )
    assert len(docs) == 1


def test_standalone_photo_is_its_own_document() -> None:
    """Two adjacent photo pages have no duplex cue — each is its own
    single-page document (never merged randomly)."""
    pages = ["f1.jpg", "f2.jpg"]
    docs = score_boundaries(
        pages,
        _kinds(("f1.jpg", "photo"), ("f2.jpg", "photo")),
        {p: (3500, 2333) for p in pages},
        {p: None for p in pages},
        {},
    )
    assert [d["pages"] for d in docs] == [["f1.jpg"], ["f2.jpg"]]


def test_first_page_number_ignores_dates_and_greetings() -> None:
    """Only a plain page number fires — a date, a greeting, or a letter
    opening never do."""
    assert first_page_number("2") == 2
    assert first_page_number("page 2") == 2
    assert first_page_number("2.") == 2
    assert first_page_number("23.11.63") is None
    assert first_page_number("Dear Maman,") is None
    assert first_page_number(None) is None
    assert first_page_number("") is None


def test_greeting_and_signoff_carry_into_duplex_docs() -> None:
    """The duplex doc opens with the picture side (no flags) — the text
    side's model greeting/sign-off still land on the document."""
    pages = ["front.jpg", "back.jpg"]
    docs = score_boundaries(
        pages,
        _kinds(("front.jpg", "photo"), ("back.jpg", "text")),
        {p: (3500, 2215) for p in pages},
        {"front.jpg": None, "back.jpg": "POST CARD"},
        {"back.jpg": _flag("back.jpg", starts=True, greeting="Chère Maman.")},
    )
    assert docs[0]["pages"] == ["front.jpg", "back.jpg"]
    assert docs[0]["greeting"] == "Chère Maman."


def test_paper_aspect_is_rotation_invariant() -> None:
    assert paper_aspect(3500, 2215) == pytest.approx(paper_aspect(2215, 3500))
    assert same_paper((3500, 2215), (2333, 3500))  # the postcard's two sides
    assert not same_paper((2480, 3508), (3500, 1500))  # 0.707 vs 0.429
