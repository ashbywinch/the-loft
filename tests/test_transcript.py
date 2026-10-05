"""The page's transcript: the row-by-row reading contract.

The contract's whole point is that a half-read page is refused rather than
presented as read, so the cases below are the refusals as much as the
assembly: a missing row, a row claimed twice, an injection without a target,
a target on writing that injects nowhere, a kind that is not writing.
"""

from __future__ import annotations

import json

import pytest

from document.transcript import ReadingError, Transcript


def _answer(*segments: dict) -> str:
    return json.dumps({"segments": list(segments)})


def test_the_rows_are_read_one_by_one() -> None:
    """Each numbered row gets its own reading: the text, the kind, and — for
    the writing's own rows — nothing that injects anywhere."""
    transcript = Transcript.from_answer(
        _answer(
            {"rows": [1], "type": "body", "transcript": "London Opera Centre"},
            {"rows": [2], "type": "body", "transcript": "my dear Jean"},
            {"rows": [3], "type": "marginalia", "transcript": "Send this first"},
        ),
        rows=3,
    )
    assert transcript.text_of(1) == "London Opera Centre"
    assert transcript.kind_of(3) == "marginalia"
    assert [reading.rows for reading in transcript.readings] == [(1,), (2,), (3,)]


def test_an_injection_names_the_row_it_follows() -> None:
    """A row squeezed in above another is an injection: it must say which row
    it injects after, and a body row must not carry a point at all."""
    transcript = Transcript.from_answer(
        _answer(
            {"rows": [1], "type": "body", "transcript": "I went to the"},
            {"rows": [2], "type": "injection", "transcript": "very cold", "injection_after": 1},
        ),
        rows=2,
    )
    assert transcript.readings[1].injection_after == 1


def test_a_page_read_in_part_is_refused() -> None:
    """Three rows numbered, two read: the answer is refused, naming the rows
    it left — never a page presented as read when it was not."""
    with pytest.raises(ReadingError, match=r"leaves 1 row\(s\) unread: \[3\]"):
        Transcript.from_answer(
            _answer(
                {"rows": [1], "type": "body", "transcript": "one"},
                {"rows": [2], "type": "body", "transcript": "two"},
            ),
            rows=3,
        )


def test_a_row_claimed_twice_is_refused() -> None:
    with pytest.raises(ReadingError, match="row 1 is claimed twice"):
        Transcript.from_answer(
            _answer(
                {"rows": [1], "type": "body", "transcript": "one"},
                {"rows": [1], "type": "body", "transcript": "one again"},
                {"rows": [2], "type": "body", "transcript": "two"},
            ),
            rows=2,
        )


def test_an_injection_needs_its_target_and_writing_does_not_want_one() -> None:
    with pytest.raises(ReadingError, match="injection without a row to inject after"):
        Transcript.from_answer(_answer({"rows": [1], "type": "injection", "transcript": "aside"}), rows=1)
    with pytest.raises(ReadingError, match="must carry no injection point"):
        Transcript.from_answer(
            _answer({"rows": [1], "type": "body", "transcript": "one", "injection_after": 1}), rows=1
        )


def test_only_writing_kinds_are_read() -> None:
    """A rule is a detector artefact, not writing: its kind is not in the
    vocabulary, and a segment with no transcript is refused."""
    with pytest.raises(ReadingError, match="unknown type 'rule'"):
        Transcript.from_answer(_answer({"rows": [1], "type": "rule", "transcript": "—"}), rows=1)
    with pytest.raises(ReadingError, match="has no transcript"):
        Transcript.from_answer(_answer({"rows": [1], "type": "body"}), rows=1)
    with pytest.raises(ReadingError, match="names a row outside 1..1"):
        Transcript.from_answer(_answer({"rows": [4], "type": "body", "transcript": "gone"}), rows=1)


def test_a_fenced_answer_is_read() -> None:
    """The model sometimes wraps its JSON in a markdown fence; that is
    tolerated, because the fence is formatting, not content."""
    fenced = "```json\n" + _answer({"rows": [1], "type": "body", "transcript": "one"}) + "\n```"
    assert Transcript.from_answer(fenced, rows=1).text_of(1) == "one"
