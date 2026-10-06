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


class ReadingError(ValueError):
    """The model's answer violates the contract — fail loudly, never merge."""


@dataclass(frozen=True)
class RowReading:
    """One row's reading: what it says, what it is, and where it injects.

    `rows` are the numbered rows this reading covers (a body row is one; a
    small aside may be several). `injection_after` is the row number an
    injection follows — the two are set together, always.
    """

    rows: tuple[int, ...]
    text: str
    kind: str
    injection_after: int | None


class Transcript:
    """The page's text, row by row, as the machine read it (the raw stage).

    `from_answer` is the whole contract: the model's answer and the number of
    rows that were numbered when it was asked. Every numbered row must appear
    in exactly one reading — none missing, none twice — because a page read in
    part is a page that will be confirmed in part.
    """

    def __init__(self, readings: tuple[RowReading, ...]) -> None:
        self.readings = readings

    @classmethod
    def from_answer(cls, answer: str, rows: int | Sequence[int]) -> Transcript:
        """The model's answer for the rows that were numbered.

        `rows` is how many were numbered (1..N, a whole page) or the numbers
        themselves — a band carries a run of a page's rows, and its answer must
        cover exactly those."""
        wanted = tuple(range(1, rows + 1)) if isinstance(rows, int) else tuple(sorted(rows))
        highest = max(wanted, default=0)
        segments = _parse(answer)
        readings: list[RowReading] = []
        claimed: dict[int, int] = {}  # row number -> the reading that claimed it
        for index, segment in enumerate(segments):
            reading = _reading(segment, index=index, rows=highest)
            readings.append(reading)
            for number in reading.rows:
                if number in claimed:
                    raise ReadingError(
                        f"row {number} is claimed twice: by reading {claimed[number]} and reading {index}"
                    )
                claimed[number] = index
        missing = sorted(set(wanted) - set(claimed))
        if missing:
            raise ReadingError(f"the answer leaves {len(missing)} row(s) unread: {missing[:20]}")
        cls._refuse_repeats(readings)
        return cls(tuple(readings))

    @staticmethod
    def _refuse_repeats(readings: list[RowReading]) -> None:
        """One line of writing read twice is a duplicated transcript.

        Rows in a tight stack have bands that overlap, and a model shown them
        can return the same writing under two numbers — page-01's rows 13-16
        came back again as 17-20, word for word (a band overlap did it), and
        its tail stack repeated one line across 37, 39 and 41. Two rows may
        share a short word; a whole line twice means one row was read twice,
        so the answer is refused rather than half-believed."""
        long_enough = [reading for reading in readings if len(reading.text.split()) >= 4]
        seen: dict[str, int] = {}
        for index, reading in enumerate(long_enough):
            key = " ".join(reading.text.lower().split())
            if key in seen:
                raise ReadingError(
                    f"readings {seen[key]} and {index} return the same line twice: {reading.text[:60]!r}"
                )
            seen[key] = index

    def text_of(self, row: int) -> str:
        """What row `row` says — the readings that cover it, in order."""
        return " ".join(reading.text for reading in self.readings if row in reading.rows)

    def kind_of(self, row: int) -> str:
        """What row `row` is: body writing, an injection, or marginalia."""
        for reading in self.readings:
            if row in reading.rows:
                return reading.kind
        raise ReadingError(f"row {row} was never read")


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
        raise ReadingError(f"the answer is not JSON: {answer[:200]!r}") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("segments"), list):
        raise ReadingError(f"the answer has no segments list: {answer[:200]!r}")
    return parsed["segments"]


def _rows_of(segment: dict[str, Any], *, index: int, rows: int) -> tuple[int, ...]:
    """The numbered rows a reading covers, or a refusal naming what is wrong
    with them: none named, one outside the page, one twice."""
    numbers = segment.get("rows")
    if not isinstance(numbers, list) or not numbers:
        raise ReadingError(f"reading {index} names no rows: {segment!r}")
    if any(not isinstance(number, int) or not 1 <= number <= rows for number in numbers):
        raise ReadingError(f"reading {index} names a row outside 1..{rows}: {numbers!r}")
    if len(set(numbers)) != len(numbers):
        raise ReadingError(f"reading {index} repeats a row: {numbers!r}")
    return tuple(numbers)


def _injection_after(segment: dict[str, Any], kind: str, *, index: int, rows: int) -> int | None:
    """The row an injection injects after: required for an injection, and
    forbidden on writing that injects nowhere."""
    after = segment.get("injection_after")
    if kind == "injection":
        if not isinstance(after, int) or not 1 <= after <= rows:
            raise ReadingError(f"reading {index} is an injection without a row to inject after: {after!r}")
        return after
    if after is not None:
        raise ReadingError(f"reading {index} is {kind!r} and must carry no injection point: {after!r}")
    return None


def _reading(segment: Any, *, index: int, rows: int) -> RowReading:
    """One segment as a reading, or a refusal naming what is wrong with it."""
    if not isinstance(segment, dict):
        raise ReadingError(f"reading {index} is not an object: {segment!r}")
    numbers = _rows_of(segment, index=index, rows=rows)
    kind = segment.get("type")
    if kind not in KINDS:
        raise ReadingError(f"reading {index}: unknown type {kind!r} (not {KINDS})")
    text = segment.get("transcript")
    if not isinstance(text, str) or not text.strip():
        raise ReadingError(f"reading {index} has no transcript: {segment!r}")
    return RowReading(
        rows=numbers,
        text=text.strip(),
        kind=kind,
        injection_after=_injection_after(segment, kind, index=index, rows=rows),
    )
