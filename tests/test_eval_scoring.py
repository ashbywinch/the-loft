"""The eval scoring contract (2026-08-26, second settlement): WORD-TOKEN
LCS coverage. The first settlement (exact per-line matching) scored
page-03 at 0.02 — the layout splits by HANDWRITING line while any
fixed reference granularity differs, so exact line matching is the
wrong contract. Words are granularity-invariant; the LCS over
normalized tokens still penalizes reordering and captures write-skip."""

from __future__ import annotations

from tools.eval_scoring import score_page


def test_perfect_match_scores_full() -> None:
    layout = {"lines": [{"text": t} for t in ["one two", "three four"]]}
    s = score_page("one two three four", layout)
    assert s["coverage"] == 1.0 and s["matched"] == 4 and s["refused"] == 0


def test_partial_coverage_counts_misses() -> None:
    layout = {"lines": [{"text": t} for t in ["one two", "three four"]]}
    s = score_page("one two three five", layout)
    assert s["coverage"] == 3 / 4 and s["matched"] == 3


def test_order_shift_is_penalized() -> None:
    # same words, wrong order: LCS over tokens scores the overlap only
    layout = {"lines": [{"text": "three four one two"}]}
    s = score_page("one two three four", layout)
    assert s["coverage"] == 0.5 and s["matched"] == 2


def test_handwriting_line_split_is_tolerated() -> None:
    # the reference is one paragraph; the layout splits it at arbitrary
    # handwriting wraps — the contract must not care
    layout = {
        "lines": [
            {"text": "P.S ] I had a whole Grade 5th"},
            {"text": "theory paper to work before"},
            {"text": "my first theory lesson today."},
        ]
    }
    truth = ["P.S ] I had a whole Grade 5th theory paper to work before my first theory lesson today."]
    assert score_page(" ".join(truth), layout)["coverage"] == 1.0


def test_refused_page_is_captured_not_failed() -> None:
    s = score_page("one two", None)
    assert s["refused"] == 1 and s["matched"] == 0 and s["coverage"] == 0.0


def test_normalized_matching_tolerates_the_engines_losses() -> None:
    layout = {"lines": [{"text": "Chere Maman."}]}
    assert score_page("Chère Maman", layout)["matched"] == 2


def test_duplicates_shift_the_remainder() -> None:
    layout = {"lines": [{"text": "one one three"}]}
    s = score_page("one two three", layout)
    assert s["matched"] == 2
