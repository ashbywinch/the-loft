"""A span: one axis' extent, from its lower end to its upper.

A run of columns, a line's x-extent, the y-window a zoom shows — each is one
axis' start and end, and naming them keeps the two ends from being read the
wrong way round (the class of bug a bare pair hides). It is a `NamedTuple`, so a
span still unpacks as `start, end`.
"""

from __future__ import annotations

from typing import NamedTuple


class Span(NamedTuple):
    """One axis' extent: its lower end and its upper end, in the caller's unit."""

    start: float
    end: float
