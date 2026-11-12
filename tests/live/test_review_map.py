"""The review session's decision mapping, pinned (A5)."""

from __future__ import annotations

from loft.live.review_map import decision_disposition


def test_an_estimated_decision_becomes_attested_with_recollection() -> None:
    decision, basis = decision_disposition("estimated", {"text": "Mum told me so", "by": "Wren", "when": "2026-08-09"})
    assert decision == "attested"
    assert basis == {
        "basis": "recollection",
        "confidence": "possible",
        "text": "Mum told me so",
        "by": "Wren",
        "when": "2026-08-09",
    }


def test_an_estimated_decision_with_no_basis_still_carries_the_disposition() -> None:
    assert decision_disposition("estimated") == (
        "attested",
        {"basis": "recollection", "confidence": "possible"},
    )


def test_an_attested_decision_is_knowledge_certain_and_keeps_its_words() -> None:
    decision, basis = decision_disposition("attested", {"text": "The certificate", "by": "the curator"})
    assert decision == "attested"
    assert basis == {
        "basis": "knowledge",
        "confidence": "certain",
        "text": "The certificate",
        "by": "the curator",
    }


def test_pending_and_delete_keep_their_names_and_basis() -> None:
    assert decision_disposition("pending") == ("pending", None)
    assert decision_disposition("pending", {"text": "later"}) == ("pending", {"text": "later"})
    assert decision_disposition("delete") == ("delete", None)
