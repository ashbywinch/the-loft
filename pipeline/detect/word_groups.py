"""The row groups one mark's cut leaves, and the continuations they absorb.

`Writing._word_groups` walks a mark's candidate segments, merging the ones no
boundary separates, and collects the continuations — the marks beneath a cut
whose ink is the same word's rest. Both are returned together, because the
pieces are built from both: the groups say which rows become pieces, the
continuations which ink those pieces also carry.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.detect.mark import Mark
from pipeline.detect.segment import Segment


@dataclass(frozen=True)
class WordGroups:
    """A mark's row groups, and the continuation each group index absorbs."""

    segments: list[Segment]
    continuations: dict[int, Mark]
