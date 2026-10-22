"""One traced line's box: the line it names, and the box its strokes define.

A trace replaces the boxes of the line it names: `compose_boxes` cuts the traced
span out of that line's own boxes and adds the traced box itself. The pair
travels as one record — the box alone cannot say which line it claims, and the
index alone cannot say where the reviewer drew it.
"""

from __future__ import annotations

from dataclasses import dataclass

from document.trace import Box


@dataclass(frozen=True)
class TracedBox:
    """A traced line's box, and the index of the line it names."""

    line: int
    box: Box
