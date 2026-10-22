"""The strokes that are one traced line: the indices of its members.

Strokes naming the same line and overlapping along it are one group, and a group
becomes one traced box. The group holds indices into the page's stroke list, not
the strokes themselves, because the line each stroke names is looked up by index
— and the group is a record, so a bare list of lists cannot be read in the wrong
order.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrokeGroup:
    """One traced line's strokes: their indices in the page's stroke list."""

    members: list[int]
