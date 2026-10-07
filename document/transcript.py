"""The page's transcript: what each of its rows says.

A page is read by showing the model the page with its rows numbered — one
number per row — and asking for the writing of each numbered row. The answer
is a list of segments; each names the rows it covers, says what it is (body
writing, an injection, or marginalia), gives its transcript, and — for an
injection — the row it injects after.

Nothing is guessed at: a missing row, a row claimed twice, a kind outside the
vocabulary, or an injection point that names no row refuses the whole answer.
A refusal is loud and visible; a half-read page is never presented as read
(MULTI-DOC-IMPORT-PRD R7: nothing unconfirmed is treated as the document's
words, and the machine's own answer is the raw stage, not the truth).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

KINDS = ("body", "injection", "marginalia")
"""What a segment of writing can be. `rule` is absent on purpose: a rule is a
detector artefact, not writing, and it carries no transcript."""

_FENCE = "```"  # the markdown fence the model sometimes wraps its JSON in


class TranscriptError(ValueError):
    """The model's answer violates the contract — fail loudly, never merge."""


@dataclass(frozen=True)
class RowTranscript:
    """One row's transcript: what it says, what it is, and where it injects.

    `rows` are the numbered rows this transcript covers (a body row is one; a
    small aside may be several). `injection_after` is the row number an
    injection follows — the two are set together, always.
    """

    rows: tuple[int, ...]
    text: str  # "" when the model could not read the row: unread, never text
    kind: str
    injection_after: int | None


class Transcript:
    """The page's text, row by row, as the machine read it (the raw stage).

    `from_answer` is the whole contract: the model's answer and the number of
    rows that were numbered when it was asked. Every numbered row must appear
    in exactly one transcript — none missing, none twice — because a page read in
    part is a page that will be confirmed in part.
    """

    def __init__(self, row_transcripts: tuple[RowTranscript, ...]) -> None:
        self.row_transcripts = row_transcripts

    @classmethod
    def from_answer(cls, answer: str, rows: int | Sequence[int]) -> Transcript:
        """The model's answer for the rows that were numbered.

        `rows` is how many were numbered (1..N, a whole page) or the numbers
        themselves — a band carries a run of a page's rows, and its answer must
        cover exactly those."""
        wanted = tuple(range(1, rows + 1)) if isinstance(rows, int) else tuple(sorted(rows))
        highest = max(wanted, default=0)
        segments = _parse(answer)
        row_transcripts: list[RowTranscript] = []
        claimed: dict[int, int] = {}  # row number -> the transcript that claimed it
        for index, segment in enumerate(segments):
            row_transcript = _row_transcript(segment, index=index, rows=highest)
            row_transcripts.append(row_transcript)
            for number in row_transcript.rows:
                if number in claimed:
                    raise TranscriptError(
                        f"row {number} is claimed twice: by transcript {claimed[number]} and transcript {index}"
                    )
                claimed[number] = index
        missing = sorted(set(wanted) - set(claimed))
        if missing:
            raise TranscriptError(f"the answer leaves {len(missing)} row(s) unread: {missing[:20]}")
        cls._refuse_repeats(row_transcripts)
        return cls(tuple(row_transcripts))

    @staticmethod
    def _refuse_repeats(row_transcripts: list[RowTranscript]) -> None:
        """One line of writing read twice is a duplicated transcript.

        Rows in a tight stack have bands that overlap, and a model shown them
        can return the same writing under two numbers — page-01's rows 13-16
        came back again as 17-20, word for word (a band overlap did it), and
        its tail stack repeated one line across 37, 39 and 41. Two rows may
        share a short word; a whole line twice means one row was read twice,
        so the answer is refused rather than half-believed."""
        long_enough = [one for one in row_transcripts if len(one.text.split()) >= 4]  # unread rows excluded
        seen: dict[str, int] = {}
        for index, one in enumerate(long_enough):
            key = " ".join(one.text.lower().split())
            if key in seen:
                raise TranscriptError(
                    f"transcripts {seen[key]} and {index} return the same line twice: {one.text[:60]!r}"
                )
            seen[key] = index

    def text_of(self, row: int) -> str:
        """What row `row` says — the transcripts that cover it, in order."""
        return " ".join(one.text for one in self.row_transcripts if row in one.rows)

    def kind_of(self, row: int) -> str:
        """What row `row` is: body writing, an injection, or marginalia."""
        for one in self.row_transcripts:
            if row in one.rows:
                return one.kind
        raise TranscriptError(f"row {row} was never read")


def _parse(answer: str) -> list[dict[str, Any]]:
    """The model's JSON answer (fence-tolerant) as the segments list."""
    stripped = answer.strip()
    if stripped.startswith(_FENCE):
        lines = stripped.splitlines()
        lines = lines[1:] if lines[0].strip().startswith(_FENCE) else lines
        stripped = "\n".join(line for line in lines if not line.strip().startswith(_FENCE)).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise TranscriptError(f"the answer is not JSON: {answer[:200]!r}") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("segments"), list):
        raise TranscriptError(f"the answer has no segments list: {answer[:200]!r}")
    return parsed["segments"]


def _rows_of(segment: dict[str, Any], *, index: int, rows: int) -> tuple[int, ...]:
    """The numbered rows a transcript covers, or a refusal naming what is wrong
    with them: none named, one outside the page, one twice."""
    numbers = segment.get("rows")
    if not isinstance(numbers, list) or not numbers:
        raise TranscriptError(f"transcript {index} names no rows: {segment!r}")
    if any(not isinstance(number, int) or not 1 <= number <= rows for number in numbers):
        raise TranscriptError(f"transcript {index} names a row outside 1..{rows}: {numbers!r}")
    if len(set(numbers)) != len(numbers):
        raise TranscriptError(f"transcript {index} repeats a row: {numbers!r}")
    return tuple(numbers)


def _injection_after(segment: dict[str, Any], kind: str, *, index: int, rows: int) -> int | None:
    """The row an injection injects after: required for an injection, and
    forbidden on writing that injects nowhere."""
    after = segment.get("injection_after")
    if kind == "injection":
        if not isinstance(after, int) or not 1 <= after <= rows:
            raise TranscriptError(f"transcript {index} is an injection without a row to inject after: {after!r}")
        return after
    if after is not None:
        raise TranscriptError(f"transcript {index} is {kind!r} and must carry no injection point: {after!r}")
    return None


def _row_transcript(segment: Any, *, index: int, rows: int) -> RowTranscript:
    """One segment as a row transcript, or a refusal naming what is wrong with it."""
    if not isinstance(segment, dict):
        raise TranscriptError(f"transcript {index} is not an object: {segment!r}")
    numbers = _rows_of(segment, index=index, rows=rows)
    kind = segment.get("type")
    if kind not in KINDS:
        raise TranscriptError(f"reading {index}: unknown type {kind!r} (not {KINDS})")
    text = segment.get("transcript")
    if not isinstance(text, str):
        raise TranscriptError(f"transcript {index} has no transcript: {segment!r}")
    # an EMPTY transcript is the model saying it cannot read that row. That is
    # a fact about the page, not a malformed answer: it is recorded as unread
    # (no text, and nothing unconfirmed is treated as the document's words) and
    # the reviewer is shown the row. A row ABSENT from the answer is still a
    # refusal — that is a partial read pretending to be a whole one.
    return RowTranscript(
        rows=numbers,
        text=text.strip(),
        kind=kind,
        injection_after=_injection_after(segment, kind, index=index, rows=rows),
    )
