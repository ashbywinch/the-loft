"""The review eval's failure messages.

A condition that says only "expected true, got false" is not diagnosable:
the run's output is kept nowhere else — the model's reasoning lives only in
the gateway's log — and pytest truncates the test's locals, so the CI log
shows the assertion and nothing to judge it by
(docs/testing-standards.md: failure messages never truncate the failing
content). These pin the message carrying the verdict.
"""

from __future__ import annotations

from pipeline.evals.eval_review import ExhaustedUncertaintyFlow, ReviewRun, WrongPersonContradictionFlow
from tools.contradiction import Contradiction
from tools.finding import Finding
from tools.review_verdict import ReviewVerdict


def _wrong_person_verdict() -> ReviewVerdict:
    """The verdict one CI draw actually produced for the wrong-person flow:
    the archive queried, the war record found, and the contradiction still
    not flagged — the case this message has to explain."""
    return ReviewVerdict(
        relevant="true",
        contradiction=Contradiction(found="false", detail=""),
        confidence="think_so",
        note="You recall a living Walter, but the war record says Walter died in 1916.",
        findings=(
            Finding(
                text="The war record says: 'Walter Whitlock died on 15 September 1916, aged 21.'",
                item_id="item-war-record",
            ),
        ),
        question="Which Walter do you remember as alive — the one who died in 1916, or the younger Walter?",
    )


def test_a_failed_contradiction_carries_the_whole_verdict() -> None:
    error = ReviewRun(WrongPersonContradictionFlow(), _wrong_person_verdict()).contradiction()
    assert error is not None
    assert "expected true, got false" in error  # what the condition judged
    assert "Which Walter do you remember as alive" in error  # what the model asked instead
    assert "item-war-record" in error  # the finding it reported
    assert "think_so" in error  # the certainty it read
    assert "You recall a living Walter" in error  # its own account of the claim


def test_a_failed_relevance_and_confidence_carry_it_too() -> None:
    off_topic = ReviewVerdict(relevant="false", confidence="definitely")
    relevance_error = ReviewRun(WrongPersonContradictionFlow(), off_topic).relevant()
    assert relevance_error is not None
    assert "relevant='false'" in relevance_error  # the verdict, not just the field
    assert "confidence='definitely'" in relevance_error

    # the exhausted-uncertainty flow accepts dont_know only; this reads the reviewer as sure
    wrong_certainty = ReviewVerdict(relevant="true", confidence="definitely")
    certainty_error = ReviewRun(ExhaustedUncertaintyFlow(), wrong_certainty).confidence()
    assert certainty_error is not None
    assert "confidence: expected one of ('dont_know',)" in certainty_error
    assert "confidence='definitely'" in certainty_error
