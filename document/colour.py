"""Colour: the RGBA record every renderer and reader draws with.

One type, not two: the pipeline's tints and chips, the detector's overlays
and the review sheets all paint the same (red, green, blue, alpha) — a
swapped channel is a silent bug, so every construction names its fields.
A `NamedTuple` because PIL's draw calls accept it as a tuple at the seam."""

from __future__ import annotations

from typing import NamedTuple


class Colour(NamedTuple):
    # an 8-bit channel's ceiling — full-intensity red, and an opaque alpha;
    # the unit a 0-1 hue or saturation converts back to and divides by
    MAX_CHANNEL = 255

    red: int
    green: int
    blue: int
    alpha: int = MAX_CHANNEL
