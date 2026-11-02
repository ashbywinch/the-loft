"""One row's tint as data: the colour it is drawn in and the rectangles it
covers.

The pipeline paints these rectangles into its overlays (`pipeline.rows.render`)
and the review screen draws the same rectangles as SVG paths — one geometry,
one colour rule, two surfaces. This is why the screen needs neither a second
implementation of the colour formula nor a raster copy of the pipeline's
render: it is handed the rectangles the pipeline itself would draw.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from document.colour import Colour
from document.rectangle import Rectangle
from document.row import Row


@dataclass(frozen=True)
class RowTint:
    """A row's tint: its colour and the rectangles that colour fills."""

    # the fields a tint record carries; a record with any other field is not a tint
    FIELDS: ClassVar[tuple[str, ...]] = ("colour", "rects")

    colour: Colour
    rects: tuple[Rectangle, ...]

    @classmethod
    def of(cls, row: Row, colour: Colour) -> RowTint:
        """The row's tint under a colour — the words' boxes and their joins."""
        return cls(colour=colour, rects=row.tint_rects())

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RowTint:
        """The record `to_dict` writes: `{"colour": [r, g, b, a], "rects":
        [{"x0": …}, …]}`."""
        record = _stated_fields(raw, "a tint record")
        colour = record["colour"]
        if not isinstance(colour, list) or len(colour) != 4:
            raise ValueError("a tint's colour is four channels")
        rects = record["rects"]
        if not isinstance(rects, list):
            raise ValueError("a tint's rects are a list")
        return cls(
            colour=Colour(*(int(channel) for channel in colour)),
            rects=tuple(Rectangle.from_dict(rect) for rect in rects),
        )

    def to_dict(self) -> dict[str, Any]:
        """The tint as its wire record — the colour as four channels, the
        rectangles as box records."""
        return {
            "colour": [self.colour.red, self.colour.green, self.colour.blue, self.colour.alpha],
            "rects": [rect.to_dict() for rect in self.rects],
        }


def _stated_fields(raw: Any, what: str) -> dict[str, Any]:
    """The record's fields, checked against the tint's shape: a missing or an
    extra field both fail loudly, naming which."""
    if not isinstance(raw, dict):
        raise ValueError(f"{what} is not an object")
    missing = [key for key in RowTint.FIELDS if key not in raw]
    extra = [key for key in raw if key not in RowTint.FIELDS]
    if missing or extra:
        raise ValueError(f"{what} has the wrong fields: missing {sorted(missing)}, extra {sorted(extra)}")
    return raw
