"""One row of writing: the words a drawn line (or a reading line) claimed, and
their union.

The id is `seg-<number>`: stable, and carrying no type — the row's kind is
decided at the transcription phase (the VLM rules what is a body row, an
interjection or marginalia, and where an injection points), never by the
geometry that found the rows. The number is the user-facing line number.

The words are their bounding boxes — never integer ids, which shift as the
word set changes. The band is the words' exact union. The text is the row's
own writing and the stage its trust (R7: the machine's raw attempt, the
system's corrected guess, the user's confirmation) — carried per row, never
as a page-level copy, so a row's confirmation survives beside its neighbours'
guesses.
"""

from __future__ import annotations

from dataclasses import dataclass

from document.rectangle import Rectangle
from document.word import Word


@dataclass(frozen=True)
class Row:
    """One row of writing: the words a drawn line (or a reading line) claimed,
    and their union."""

    id: str
    kind: str  # "body" from the builder; the transcription phase sets the rest
    number: int
    word_boxes: list[Word]
    band: Rectangle
    text: str = ""  # the row's own writing; empty until a reading fills it
    stage: str = ""  # R7 trust: "raw" | "guess" | "confirmed"; "" = unread
