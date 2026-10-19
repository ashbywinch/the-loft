"""One row algorithm's score against the adjudication: the words it put in the
right row, of those judged.

Two row engines are compared on the same page (the reader's fitted lines against
the word grouping), and both are reported by the same two counts. The pair is a
record, not a bare tuple: `correct` is the words the adjudication agrees with,
`judged` the words the algorithm placed in some row at all, and reading them the
wrong way round would misreport both engines.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RowScore:
    """One algorithm's score: the words in the row the adjudication gives them,
    and the words it judged (every word it placed in a row)."""

    correct: int
    judged: int
