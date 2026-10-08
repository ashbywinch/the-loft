"""The page's transcript: the row-by-row contract.

The contract's whole point is that a half-read page is refused rather than
presented as read, so the cases below are the refusals as much as the
assembly: a missing row, a row claimed twice, an injection without a target,
a target on writing that injects nowhere, a kind that is not writing.
"""

from __future__ import annotations

import json

import pytest

from document.transcript import Transcript, TranscriptError


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
    assert [one.rows for one in transcript.row_transcripts] == [(1,), (2,), (3,)]


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
    assert transcript.row_transcripts[1].injection_after == 1


def test_a_page_read_in_part_is_refused() -> None:
    """Three rows numbered, two read: the answer is refused, naming the rows
    it left — never a page presented as read when it was not."""
    with pytest.raises(TranscriptError, match=r"leaves 1 row\(s\) unread: \[3\]"):
        Transcript.from_answer(
            _answer(
                {"rows": [1], "type": "body", "transcript": "one"},
                {"rows": [2], "type": "body", "transcript": "two"},
            ),
            rows=3,
        )


def test_a_row_claimed_twice_is_refused() -> None:
    with pytest.raises(TranscriptError, match="row 1 is claimed twice"):
        Transcript.from_answer(
            _answer(
                {"rows": [1], "type": "body", "transcript": "one"},
                {"rows": [1], "type": "body", "transcript": "one again"},
                {"rows": [2], "type": "body", "transcript": "two"},
            ),
            rows=2,
        )


def test_an_injection_needs_its_target_and_writing_does_not_want_one() -> None:
    with pytest.raises(TranscriptError, match="injection without a row to inject after"):
        Transcript.from_answer(_answer({"rows": [1], "type": "injection", "transcript": "aside"}), rows=1)
    with pytest.raises(TranscriptError, match="must carry no injection point"):
        Transcript.from_answer(
            _answer({"rows": [1], "type": "body", "transcript": "one", "injection_after": 1}), rows=1
        )


def test_only_writing_kinds_are_read() -> None:
    """A rule is a detector artefact, not writing: its kind is not in the
    vocabulary, and a segment with no transcript field at all is refused."""
    with pytest.raises(TranscriptError, match="unknown type 'rule'"):
        Transcript.from_answer(_answer({"rows": [1], "type": "rule", "transcript": "—"}), rows=1)
    with pytest.raises(TranscriptError, match="has no transcript"):
        Transcript.from_answer(_answer({"rows": [1], "type": "body"}), rows=1)
    with pytest.raises(TranscriptError, match="names a row outside 1..1"):
        Transcript.from_answer(_answer({"rows": [4], "type": "body", "transcript": "gone"}), rows=1)


def test_an_empty_transcript_is_an_unread_row_not_a_refusal() -> None:
    """A row the model looked at and could not read comes back with an empty
    transcript. The page is still read — the row is recorded as unread, so
    nothing unconfirmed becomes the document's words and the reviewer is shown
    it — where a row ABSENT from the answer is a refusal."""
    transcript = Transcript.from_answer(
        _answer(
            {"rows": [1], "type": "body", "transcript": "read this one"},
            {"rows": [2], "type": "body", "transcript": ""},
        ),
        rows=2,
    )
    assert transcript.text_of(1) == "read this one"
    assert transcript.text_of(2) == "", "an unread row carries no text"


def test_a_fenced_answer_is_read() -> None:
    """The model sometimes wraps its JSON in a markdown fence; that is
    tolerated, because the fence is formatting, not content."""
    fenced = "```json\n" + _answer({"rows": [1], "type": "body", "transcript": "one"}) + "\n```"
    assert Transcript.from_answer(fenced, rows=1).text_of(1) == "one"


def test_the_rows_are_numbered_where_the_number_cannot_be_mistaken() -> None:
    """The render the model reads: one chip per row, in the gutter left of the
    row, carrying the row's own number — and the map from ids to numbers, so an
    answer naming numbers 1..N needs no geometric reconciliation. A row whose
    chip has no free spot refuses the render rather than going unnumbered."""
    from PIL import Image

    from document.numbered_rows import NumberedRows
    from document.rectangle import Rectangle
    from document.row import Row

    page = Image.new("RGB", (400, 300), (250, 250, 245))
    rows = [
        Row(id="seg-1", kind="body", number=1, word_boxes=[], band=Rectangle(120, 40, 380, 70)),
        Row(id="seg-2", kind="body", number=2, word_boxes=[], band=Rectangle(120, 140, 380, 170)),
    ]
    numbered = NumberedRows.render(page, rows)
    assert numbered.rows_drawn() == 2
    assert numbered.numbers == {"seg-1": 1, "seg-2": 2}
    changed = sum(1 for x in range(400) for y in range(300) if numbered.image.getpixel((x, y)) != (250, 250, 245))
    assert changed > 50, "no chip was drawn"
    # nothing is painted over the rows' own writing
    assert all(numbered.image.getpixel((250, 55)) == (250, 250, 245) for _ in [0])


def test_a_line_read_twice_is_refused() -> None:
    """A tight stack's overlapping bands make a model return the same writing
    under two numbers (page-01: rows 13-16 came back again as 17-20). Two rows
    may share a short word; a whole line twice means one row was read twice."""
    with pytest.raises(TranscriptError, match="return the same line twice"):
        Transcript.from_answer(
            _answer(
                {"rows": [1], "type": "body", "transcript": "the same line of writing here"},
                {"rows": [2], "type": "body", "transcript": "The same line of writing here"},
            ),
            rows=2,
        )
    # short repeats are ordinary writing, not a double read
    ok = Transcript.from_answer(
        _answer(
            {"rows": [1], "type": "body", "transcript": "—"},
            {"rows": [2], "type": "body", "transcript": "—"},
        ),
        rows=2,
    )
    assert len(ok.row_transcripts) == 2
