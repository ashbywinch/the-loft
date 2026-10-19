"""One text line's pieces: the rec's boxes that share a y-band.

The rec's detection pieces are REAL ink, so a row is a measured thing, not a
guess: the pieces whose y-centres chain within a fraction of their own height.
The row is a record — the pieces it holds, in order — and its measured extent
is its own business: the bounding box of those pieces, which is what the
label matching and the extent gates read.

It is NOT `document.row.Row`: that row is the transcribed one, with an id, a
kind and its reading, all decided after this geometry (the geometry never
decides a row's kind).
"""

from __future__ import annotations

from dataclasses import dataclass

from document.rectangle import Rectangle


@dataclass(frozen=True)
class PieceRow:
    """One text line's pieces: the rec's boxes that share a y-band."""

    pieces: list[Rectangle]

    def __post_init__(self) -> None:
        if not self.pieces:
            raise ValueError("a row holds at least one piece")

    def union(self) -> Rectangle:
        """The row's measured extent — the bounding box of its pieces."""
        return Rectangle(
            min(piece.x0 for piece in self.pieces),
            min(piece.y0 for piece in self.pieces),
            max(piece.x1 for piece in self.pieces),
            max(piece.y1 for piece in self.pieces),
        )
