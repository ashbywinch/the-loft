"""One page's bands, numbered and written: the images the model is shown.

A page is read ONE BAND PER CALL — one image per band, each at the page's own
resolution — so the bands are cut, numbered and saved together: ``numbered`` is
each band's render with its row numbers drawn on it, and ``paths`` where each
was written beside the run. The paths are what a call sends, and the artifacts
an answer is diagnosed from.

A record with no wire: a band's render is a JPEG and its path a filename — the
pair is what the reading needs in hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from document.numbered_rows import NumberedRows


@dataclass(frozen=True)
class PageBands:
    """A page's bands: the numbered renders, and where each was written."""

    numbered: list[NumberedRows]
    paths: list[Path]
