"""A shape's ink in a line's own frame: along the line, and across it.

`Line.project` measures every piece in the fitted line's local frame — u along
the baseline, v across it — because a sloped line's box is a box in that frame,
not in the page's. The two coordinate arrays are meaningless apart, so they
travel as one record whose fields say which is which (an index cannot).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ProjectedInk:
    """A shape's ink in the line's own frame: `along` the line, `across` it."""

    along: np.ndarray
    across: np.ndarray
