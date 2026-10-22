"""The box a line's anchor takes, and the source it came from.

The anchor resolution picks between three sources — the report's located
estimate ("report"), the rec's ink-grounded content match ("content") and
the order-based fallback ("positional"). The box and its provenance are one
decision, so they travel as one record rather than a bare pair.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BoxChoice:
    """The chosen box and which source it came from."""

    box: list[float]
    source: str
