"""One detection pass: the orientation it ran at and the lines it admitted.

The multi-orientation layout runs the detector once per reported direction
(PRD VR15); each run's admitted lines are the pass. The degrees and the
lines travel together — a bare pair read by position is a record with no
name, and the assembly sorts the passes by their degrees.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.detection import Detection


@dataclass(frozen=True)
class DetectionPass:
    """One orientation pass of the detector."""

    degrees: int
    lines: list[Detection]
