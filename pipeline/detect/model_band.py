"""A band the model boxed on the page: its y-extent, and the line it read there.

The model's own boxes are schematic — they cannot be trusted as positions, so
they only refine the label matching where they agree with the measured rows.
The band is a record: the two y's it spans and the text the model claimed
between them, and the overlap it has with a measured row is its own to answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from document.rectangle import Rectangle


@dataclass(frozen=True)
class ModelBand:
    """A y-band the model boxed, and the line it read there."""

    y0: float
    y1: float
    text: str

    def overlap(self, box: Rectangle) -> float:
        """The y-overlap between this band and a measured box."""
        return max(0.0, min(box.y1, self.y1) - max(box.y0, self.y0))
