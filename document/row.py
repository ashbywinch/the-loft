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
from typing import Any, ClassVar

from document.rectangle import Rectangle
from document.word import Word

# the fields a row record carries; its text and stage are the row's reading and
# its trust, and a record from before a reading ran carries neither
ROW_FIELDS = ("id", "kind", "number", "word_boxes", "band")


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

    # the per-row trust stages, in trust order (MULTI-DOC-IMPORT-PRD R7): the
    # machine's raw attempt, the system's corrected guess, the user's
    # confirmation — plus "" for a row no reading has filled yet
    STAGES: ClassVar[tuple[str, ...]] = ("", "raw", "guess", "confirmed")

    def __post_init__(self) -> None:
        if self.stage not in self.STAGES:
            raise ValueError(f"a row's stage {self.stage!r} is not one of {sorted(self.STAGES)}")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Row:
        """The row a rows.json record describes: its identity, kind and
        number, the words' boxes inline (a row never references another
        file's word ids), its band, and its own text and trust stage — a
        record from before a reading ran carries neither, which reads as
        unread ("")."""
        missing = [key for key in ROW_FIELDS if key not in raw]
        if missing:
            raise ValueError(f"a row record is missing {sorted(missing)}")
        text = raw.get("text", "")
        if not isinstance(text, str):
            raise ValueError("a row's text is a string")
        return cls(
            id=str(raw["id"]),
            kind=str(raw["kind"]),
            number=int(raw["number"]),
            word_boxes=[_word_box(record, index) for index, record in enumerate(raw["word_boxes"])],
            band=_box(raw["band"], "band"),
            text=text,
            stage=str(raw.get("stage", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """The row as its rows.json record — the words' boxes inline, its
        band, and its own text and trust stage."""
        return {
            "id": self.id,
            "kind": self.kind,
            "number": self.number,
            "word_boxes": [word.rect.to_dict() for word in self.word_boxes],
            "band": self.band.to_dict(),
            "text": self.text,
            "stage": self.stage,
        }


def _box(record: Any, what: str) -> Rectangle:
    """One wire box record as its rectangle, `what` naming where it sat."""
    try:
        return Rectangle.from_dict(record)
    except ValueError as exc:
        raise ValueError(f"{what}: {exc}") from exc


def _word_box(record: Any, index: int) -> Word:
    """One wire word box as a Word — the wire carries the box alone."""
    rect = _box(record, f"word_boxes[{index}]")
    return Word(rect.x0, rect.y0, rect.x1, rect.y1)
