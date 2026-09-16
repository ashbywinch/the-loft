"""How one yellow line agrees with the grouping."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Verdict:
    """How one yellow line agrees with the grouping."""

    verdict: str  # "right" | "split" | "unboxed"
    rows: tuple[int, ...]  # the row indices holding the line's own words
    words: int  # all words the trace passed over
    outside: tuple[int, ...]  # own words whose centre its row's box misses
