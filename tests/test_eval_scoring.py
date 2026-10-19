"""The eval scoring contract: WORD-TOKEN LCS coverage. Exact per-line
matching is the wrong contract — the layout splits by HANDWRITING line
while any fixed reference granularity differs, so exact line matching
scored page-03 at 0.02. Words are granularity-invariant; the LCS over
normalized tokens still penalizes reordering and captures write-skip."""

from __future__ import annotations

from pipeline.evals.eval_scoring import score_page
from pipeline.layout import Layout


def _served(*texts: str) -> Layout:
    """A page's served layout carrying one line per text — the artefact
    the scorer reads, built by the layout's own class."""
    return Layout.from_dict({"lines": [{"text": t} for t in texts]})


def test_perfect_match_scores_full() -> None:
    s = score_page("one two three four", _served("one two", "three four"))
    assert s.coverage == 1.0 and s.matched == 4 and s.refused == 0


def test_partial_coverage_counts_misses() -> None:
    s = score_page("one two three five", _served("one two", "three four"))
    assert s.coverage == 3 / 4 and s.matched == 3


def test_order_shift_is_penalized() -> None:
    # same words, wrong order: LCS over tokens scores the overlap only
    s = score_page("one two three four", _served("three four one two"))
    assert s.coverage == 0.5 and s.matched == 2


def test_handwriting_line_split_is_tolerated() -> None:
    # the reference is one paragraph; the layout splits it at arbitrary
    # handwriting wraps — the contract must not care
    layout = _served(
        "P.S ] I had a whole Grade 5th",
        "theory paper to work before",
        "my first theory lesson today.",
    )
    truth = ["P.S ] I had a whole Grade 5th theory paper to work before my first theory lesson today."]
    assert score_page(" ".join(truth), layout).coverage == 1.0


def test_refused_page_is_captured_not_failed() -> None:
    s = score_page("one two", None)
    assert s.refused == 1 and s.matched == 0 and s.coverage == 0.0


def test_normalized_matching_tolerates_the_engines_losses() -> None:
    assert score_page("Chère Maman", _served("Chere Maman.")).matched == 2


def test_duplicates_shift_the_remainder() -> None:
    s = score_page("one two three", _served("one one three"))
    assert s.matched == 2
