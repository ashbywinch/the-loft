"""A chip's extent: the width and height its number needs.

`chip_extent` measures the number's text at a font and adds the ring's pad —
the pair `candidates` places from, capped at the renderer's MAX_CHIP.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChipExtent:
    """A chip's footprint for a number at a font size, in section px."""

    width: float
    height: float
