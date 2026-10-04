"""One row of writing: the words a drawn line (or a reading line) claimed, and
their union.

The id carries its kind, so the file format never loses the type: `seg-6` is a
body row, `int-41` an interjection row. The number is the user-facing line
number. The words are their bounding boxes — never integer ids, which shift as
the word set changes. The band is the words' exact union. The text is the
row's own writing and the stage its trust (R7: the machine's raw attempt, the
system's corrected guess, the user's confirmation) — carried per row, never as
a page-level copy, so a row's confirmation survives beside its neighbours'
guesses.
"""

from __future__ import annotations

from dataclasses import dataclass

from tools.rectangle import Rectangle
from tools.word import Word


@dataclass(frozen=True)
class Row:
    """One row of writing: the words a drawn line (or a reading line) claimed,
    and their union."""

    id: str
    kind: str  # "body" | "interjection"
    number: int
    word_boxes: list[Word]
    band: Rectangle
    text: str = ""  # the row's own writing; empty until a reading fills it
    stage: str = ""  # R7 trust: "raw" | "guess" | "confirmed"; "" = unread
