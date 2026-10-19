"""The verdict on one proposed cut: does it separate two things, and what does it absorb?

`Writing._is_a_cut` judges a boundary between two segments of a mark: both sides
word-shaped (or one side a line that cedes) means the cut stands. A cut at the
mark's bottom edge may instead be a word split across two components by a
crossing line — then the verdict carries the mark beneath, whose ink is the same
word's rest and is absorbed into the piece.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.detect.mark import Mark


@dataclass(frozen=True)
class CutVerdict:
    """Whether a boundary is a real cut, and the continuation it absorbs."""

    cut: bool
    continuation: Mark | None
