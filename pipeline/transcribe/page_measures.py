"""What a read page can be measured on without a gold transcript.

There is no confirmed transcript for these pages yet, so the run checks what
needs none: the kinds and where they point, no row without words, a plausible
words-per-row band, and transcripts that differ from one another — a model
repeating one line down the page is a failure with no gold needed.

The measures sit FLAT in the run's report, beside the read's own keys rather
than nested under one, so ``to_dict``/``from_dict`` are keys of that report
record: ``TranscriptionReport`` writes and reads them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PageMeasures:
    """The measures of one read page: its segments counted and weighed."""

    row_transcripts: int
    kinds: dict[str, int]
    injections_point_at_a_row: bool
    words_per_row_median: float
    words_per_row_min: int
    distinct_transcripts: int
    longest_transcript: int

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PageMeasures:
        """The measures a report record carries — flat, beside the read's own
        keys."""
        return cls(
            row_transcripts=int(raw["row_transcripts"]),
            kinds={str(kind): int(count) for kind, count in (raw.get("kinds") or {}).items()},
            injections_point_at_a_row=bool(raw["injections_point_at_a_row"]),
            words_per_row_median=float(raw["words_per_row_median"]),
            words_per_row_min=int(raw["words_per_row_min"]),
            distinct_transcripts=int(raw["distinct_transcripts"]),
            longest_transcript=int(raw["longest_transcript"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """The measures as the report's own keys, in the order it writes them."""
        return {
            "row_transcripts": self.row_transcripts,
            "kinds": self.kinds,
            "injections_point_at_a_row": self.injections_point_at_a_row,
            "words_per_row_median": self.words_per_row_median,
            "words_per_row_min": self.words_per_row_min,
            "distinct_transcripts": self.distinct_transcripts,
            "longest_transcript": self.longest_transcript,
        }
