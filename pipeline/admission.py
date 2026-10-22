"""One orientation pass's admission: the lines read as real text, and the rest.

Admission is the recognition-driven gate (PRD VR15): the detector lines the
recognizer read REAL text at this orientation are kept — their boxes remapped
from the rotated frame back to the original image — and the others are
rejected, remapped too (a rejected line's box is still real geometry, which
is why the layout keeps it as an extra). Both lists are one outcome of one
pass, so they travel as one named record.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.detection import Detection


@dataclass(frozen=True)
class Admission:
    """One pass's outcome: the lines admitted and the lines rejected."""

    kept: list[Detection]
    rejected: list[Detection]
