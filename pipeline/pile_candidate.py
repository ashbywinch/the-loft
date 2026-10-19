"""A registry record the adopted folder might be the same pile as: how much
content the two share, and the record itself.

The overlap is the evidence the match rests on — a path match is the pile
outright, and a path mismatch is only the same pile when the overlap is large
(a small overlap is a duplicate-scan case, never hijacked).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pipeline.batch_record import BatchRecord


@dataclass(frozen=True)
class PileCandidate:
    """A registry record the folder's content might be the same pile as."""

    overlap: int
    path: Path
    record: BatchRecord
