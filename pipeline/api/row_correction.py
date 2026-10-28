"""The page's corrected rows and what the traces broke, together.

The correction builds the rows the reviewer's drawn lines make and validates
the same traces they were built from (`Rows.validate`) in one pass over one
page's inputs; the two travel together because they describe the same write —
the surface shows the rows and the first violation of the drawing that made
them.
"""

from __future__ import annotations

from dataclasses import dataclass

from document.row import Row


@dataclass(frozen=True)
class RowCorrection:
    """One page's correction: the rows, and the violations the traces hold."""

    rows: list[Row]
    violations: tuple[str, ...] = ()
