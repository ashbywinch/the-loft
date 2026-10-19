"""One captioned set of rows: the title a panel is labelled with, and the rows
that panel draws.

The row engines are compared side by side, one captioned panel each (the user's
own adjudication, the reader's proposal, the grouping), so a panel is a title and
the rows under it — one record, whether the panel is the whole page or a zoomed
band of it.
"""

from __future__ import annotations

from dataclasses import dataclass

from document.row import Row


@dataclass(frozen=True)
class RowSet:
    """One captioned set of rows: its title, and the rows it draws."""

    title: str
    rows: list[Row]
