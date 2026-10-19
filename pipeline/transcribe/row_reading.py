"""One row read on its own: the row's number, and the writing read for it.

A row the bands left blank or doubled is shown ALONE — a masked crop of its own
words, so no neighbour's ink can be read as this row's — and what comes back is
this pair: which row it was, and the text read for it. The running read threads
each new row with the rows above it, so the list of these is also the
transcript so far.

A record with no wire of its own: the rows read alone are persisted as a
mapping of number to text (``<stem>.alone.json``) — a mapping, which is the
file's shape, not this record's.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RowReading:
    """One row read alone: its number, and the writing read for it."""

    number: int
    text: str
