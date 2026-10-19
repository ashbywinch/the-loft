"""One page of a transcription run: its name and the image to read.

The run is given the pages by NAME — the .txt, the sidecars and the layout
are keyed by it — and by file: the oriented image the model actually reads.
The two travel together, and a bare pair read by position is a record with
no name.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PageImage:
    """One page of a run: its name and the image to read."""

    name: str
    image: Path
