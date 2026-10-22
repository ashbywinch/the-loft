"""One page's raw OCR text: the page's name and what the OCR read on it.

The guess stage works from each text page's raw OCR, and the page's name is what
the model's answer must name to be matched back. The pair travels together (a
page's text is meaningless without the page it came from), so it is one record —
never a bare tuple whose two strings can be read the wrong way round.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageText:
    """One page's raw OCR: the page's name and the text read on it."""

    page: str
    text: str
