"""The words one drawn stroke passes over — how a stroke names its line.

A stroke IS a line (the reviewer drew it along one), and the line it names is the
one holding most of the words it covers. The covered words are one stroke's own
measurement of the page, held per stroke because that is the index the naming is
read by.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.detect.mark import Mark


@dataclass(frozen=True)
class CoveredWords:
    """The words one stroke passes over, in the page's own order."""

    words: list[Mark]
