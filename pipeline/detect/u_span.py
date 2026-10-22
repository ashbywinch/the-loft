"""An extent along a line of writing, in the line's own u units.

`Line.u_span` answers where a box lies along the fitted line; a trace's spans
are the same measure — the pair of u coordinates the thing's ends sit at. Named,
because a bare (min, max) pair cannot say which end is which, and a NamedTuple,
so a span still sorts and unpacks as the pair of numbers it is.
"""

from __future__ import annotations

from typing import NamedTuple


class USpan(NamedTuple):
    """An extent along a line, `start` and `end` in the line's own u units."""

    start: float
    end: float
