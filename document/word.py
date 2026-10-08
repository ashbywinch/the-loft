"""One word on the page: its rectangle and ITS font size.

The font size is the word's own: the number of pixels between its baseline and
its waistline - the x-height measured from the ink. Ascenders and descenders
cannot distort it (box height can and does: a word with no ascenders reads
'small' though it is not). A word is not a kind of rectangle - it HAS one -
so the geometry lives in `Rectangle` once, and Word delegates. Smallness is
not here either: a word is small only relative to the page, so `Page.is_small`
owns that judgement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from document.rectangle import Rectangle

RULE_ASPECT = 8.0  # x height: this wide for its height is a rule, not a word


@dataclass(frozen=True)
class WordMeasurements:
    """The measures the detector made of a word: the two fitted lines
    (baseline and waistline), the font-size estimate, and the reading's
    line index. All optional - an unmeasured word carries the defaults."""

    baseline: float | None = None
    waistline: float | None = None
    font_size: float = 0.0
    line: int | None = None


class Word:
    """One word on the page: its rectangle and ITS font size."""

    def __init__(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        measurements: WordMeasurements | None = None,
        **legacy: Any,
    ) -> None:
        """A word at (x0, y0)-(x1, y1) with the detector's measures.

        ``legacy`` carries the flat measurement keywords (``baseline``,
        ``waistline``, ``font_size``, ``line``) the pre-record callers in
        the pipeline still pass - folded into the record here so they keep
        working until they migrate to constructing the record themselves.
        """
        if measurements is None:
            measurements = WordMeasurements(
                baseline=legacy.get("baseline"),
                waistline=legacy.get("waistline"),
                font_size=legacy.get("font_size", 0.0),
                line=legacy.get("line"),
            )
        self.rect = Rectangle(x0, y0, x1, y1)
        self.baseline = measurements.baseline
        self.waistline = measurements.waistline
        self.line = measurements.line  # the reading's line index: the word's own line structure
        self._font_size = measurements.font_size  # unmeasured fallback; 0 means unmeasured

    @property
    def font_size(self) -> float:
        """The word's x-height: baseline to waistline, the pixels between the
        two measured lines. Unmeasured words carry the caller's estimate
        instead (0 means unmeasured entirely)."""
        if self.baseline is not None and self.waistline is not None:
            return self.baseline - self.waistline
        return self._font_size

    @property
    def x0(self) -> float:
        return self.rect.x0

    @property
    def y0(self) -> float:
        return self.rect.y0

    @property
    def x1(self) -> float:
        return self.rect.x1

    @property
    def y1(self) -> float:
        return self.rect.y1

    @property
    def width(self) -> float:
        return self.rect.width

    @property
    def height(self) -> float:
        return self.rect.height

    @property
    def cx(self) -> float:
        return self.rect.cx

    @property
    def cy(self) -> float:
        return self.rect.cy

    def is_rule(self) -> bool:
        """An underline or rule: far wider than it is tall, so not a word."""
        return self.width >= RULE_ASPECT * self.height

    def is_letter(self) -> bool:
        """A single glyph box (an 'I', a digit): narrower than it is tall.
        Its x-height measurement is a guess, not a word's - the page discards
        it when it averages its own size."""
        return self.width < 0.75 * self.height
