"""The correction's inputs, whole: the page's measured words, the reviewer's
drawn lines, and the page's pixel size.

They travel together — `Rows.from_words(...).adjust(...)` consumes exactly
these three, and so does `Rows.validate(...)` — so they are one value rather
than three parallel parameters, and a caller cannot measure the lines against
one page's size while grouping another page's words.

The name is the pipeline's: the reviewer's *traces* are what they drew, and
the correction reads them against the page.
"""

from __future__ import annotations

from dataclasses import dataclass

from document.page_size import PageSize
from document.row_adjustments import RowAdjustments
from document.word import Word


@dataclass(frozen=True)
class Traces:
    """One page's correction inputs: its words, the drawn lines, its size."""

    words: tuple[Word, ...]
    adjustments: RowAdjustments
    page_size: PageSize
