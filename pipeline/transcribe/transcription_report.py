"""One page transcribed: what was read, what it cost, and the verdict.

The report is the run's record: the page, the endpoint and model that read it
and how long it took, the rows and words read, the bands sent, the usage, the
renders written and the per-row text — plus, where they happened, the refusal
that stopped the page and the bands' working notes, and the page's measures
(``PageMeasures``; they sit flat here, see that module).

Its wire is the report JSON: ``to_dict`` writes it — the keys a read did not
produce are left out, so a page with no rows carries no endpoint and a refused
page carries no measures — and ``from_dict`` reads it back. A reader of a
report therefore takes this record rather than guessing at dict keys.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, replace
from typing import Any

from document.transcript import Transcript
from pipeline.model.token_usage import TokenUsage
from pipeline.transcribe.page_measures import PageMeasures


@dataclass(frozen=True)
class TranscriptionReport:
    """One page transcribed: its rows, its transcript, its verdict, its cost.

    ``page``, ``rows`` and ``transcripts`` are what every read produces (a page
    with no writing produces none of the rest); the other fields are absent
    until the read produced them, and ``to_dict`` leaves an absent field out.
    """

    page: str
    rows: int
    transcripts: dict[str, str]
    endpoint: str | None = None
    model: str | None = None
    seconds: float | None = None
    words: int | None = None
    strips: int | None = None
    usage: TokenUsage | None = None
    renders: list[str] | None = None
    refused: str | None = None
    band_notes: list[str] | None = None
    measures: PageMeasures | None = None

    def measured(self, transcript: Transcript) -> TranscriptionReport:
        """This report with the page's measures added: the kinds and where they
        point, no row without words, a plausible words-per-row band, and
        transcripts that differ from one another."""
        kinds: dict[str, int] = {}
        words_per_row: list[int] = []
        for one in transcript.row_transcripts:
            kinds[one.kind] = kinds.get(one.kind, 0) + 1
            words_per_row.append(len(re.findall(r"[\w'’~-]+", one.text)))
        return replace(
            self,
            measures=PageMeasures(
                row_transcripts=len(transcript.row_transcripts),
                kinds=kinds,
                injections_point_at_a_row=all(
                    one.kind != "injection" or one.injection_after is not None for one in transcript.row_transcripts
                ),
                words_per_row_median=statistics.median(words_per_row),
                words_per_row_min=min(words_per_row),
                distinct_transcripts=len({one.text.strip().lower() for one in transcript.row_transcripts}),
                longest_transcript=max(len(one.text) for one in transcript.row_transcripts),
            ),
        )

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TranscriptionReport:
        """The report a report JSON holds: the page's read, with the fields the
        read did not produce absent (and the measures, when they were
        measured, flat beside the rest)."""
        return cls(
            page=str(raw["page"]),
            rows=int(raw.get("rows", 0)),
            transcripts={str(number): str(text) for number, text in (raw.get("transcripts") or {}).items()},
            endpoint=raw.get("endpoint"),
            model=raw.get("model"),
            seconds=raw.get("seconds"),
            words=raw.get("words"),
            strips=raw.get("strips"),
            usage=None if raw.get("usage") is None else TokenUsage.from_dict(raw["usage"]),
            renders=raw.get("renders"),
            refused=raw.get("refused"),
            band_notes=raw.get("band_notes"),
            measures=PageMeasures.from_dict(raw) if "row_transcripts" in raw else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """The report as its JSON: the keys a read did not produce are left
        out, and the page's measures ride flat at the end."""
        out: dict[str, Any] = {"page": self.page}
        for key, value in (
            ("endpoint", self.endpoint),
            ("model", self.model),
            ("seconds", self.seconds),
            ("rows", self.rows),
            ("words", self.words),
            ("strips", self.strips),
            ("usage", None if self.usage is None else self.usage.to_dict()),
            ("renders", self.renders),
            ("transcripts", self.transcripts),
            ("refused", self.refused),
            ("band_notes", self.band_notes),
        ):
            if value is not None:
                out[key] = value
        if self.measures is not None:
            out.update(self.measures.to_dict())
        return out
