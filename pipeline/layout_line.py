"""One line of a page's review layout: its text, its box and its words.

A line is the unit the review surface shows and the reader edits: the
transcription's text, the box it sits in (None when no source could locate
it), the confidence the review colours, the per-word flags, and the
detection the line came from. The class OWNS its layout-JSON entry — the
builders emit different subsets of the fields, so a field that is None is
NOT on the wire and ``to_dict`` re-emits exactly what the line carries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pipeline.detection_word import DetectionWord
from pipeline.layout_word import LayoutWord
from pipeline.richness import Richness

# the box_source values the builders use — the review colours a line by them
BOX_SOURCE_REPORT = "report"
BOX_SOURCE_REPORT_UNCONFIRMED = "report-unconfirmed"
BOX_SOURCE_CONTENT = "content"
BOX_SOURCE_POSITIONAL = "positional"
BOX_SOURCE_MULTI = "multi"


@dataclass
class LayoutLine:
    """One line of a page's review layout."""

    index: int
    text: str
    box: list[float] | None = None
    conf: float | None = None
    words: list[LayoutWord] | None = None
    box_source: str | None = None
    orientation: float | None = None
    rec_text: str | None = None
    rec_score: float | None = None
    det_words: list[DetectionWord] | None = None

    def is_boxed(self) -> bool:
        """A line whose box holds ink — the gates' own test."""
        return bool(self.box)

    def is_anchored(self) -> bool:
        """A line the model's report located (confirmed or not): the
        authoritative transcription, never dropped by the dedupe."""
        return self.box_source in (BOX_SOURCE_REPORT, BOX_SOURCE_REPORT_UNCONFIRMED)

    def is_confirmed(self) -> bool:
        """A line a rec detection content-matched — the rec read its text."""
        return self.box_source == BOX_SOURCE_CONTENT

    def richness(self) -> Richness:
        """The reading's strength — more letters beat fewer; ties by score."""
        return Richness(letters=sum(1 for ch in self.text if ch.isalpha()), conf=self.conf or 0.0)

    @classmethod
    def from_dict(cls, raw: dict[str, Any], position: int = 0) -> LayoutLine:
        """The line a layout-JSON entry (or a reading line) describes.

        ``position`` is the index for a line whose entry carries none — the
        readers assign the position the review surface keys its edit state
        on, so a layout already on disk loads correctly without a rewrite."""
        index = raw.get("index")
        conf = raw.get("conf")
        orientation = raw.get("orientation")
        words = raw.get("words")
        det_words = raw.get("det_words")
        return cls(
            index=int(index) if isinstance(index, (int, float)) else position,
            text=str(raw.get("text", "")),
            box=raw.get("box"),
            conf=float(conf) if isinstance(conf, (int, float)) else None,
            words=[LayoutWord.from_dict(w) for w in words if isinstance(w, dict)] if isinstance(words, list) else None,
            box_source=raw.get("box_source"),
            orientation=orientation if isinstance(orientation, (int, float)) else None,
            rec_text=raw.get("rec_text"),
            rec_score=raw.get("rec_score"),
            det_words=(
                [DetectionWord.from_dict(w) for w in det_words if isinstance(w, dict)]
                if isinstance(det_words, list)
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """The line as its layout-JSON entry — only the fields it carries."""
        out: dict[str, Any] = {"index": self.index, "text": self.text, "box": self.box}
        if self.conf is not None:
            out["conf"] = self.conf
        if self.words is not None:
            out["words"] = [word.to_dict() for word in self.words]
        if self.box_source is not None:
            out["box_source"] = self.box_source
        if self.orientation is not None:
            out["orientation"] = self.orientation
        if self.rec_text is not None:
            out["rec_text"] = self.rec_text
        if self.rec_score is not None:
            out["rec_score"] = self.rec_score
        if self.det_words is not None:
            out["det_words"] = [word.to_dict() for word in self.det_words]
        return out
