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

from tools.rectangle import Rectangle

RULE_ASPECT = 8.0  # x height: this wide for its height is a rule, not a word


class Word:
    """One word on the page: its rectangle and ITS font size."""

    def __init__(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        baseline: float | None = None,
        waistline: float | None = None,
        font_size: float = 0.0,
    ) -> None:
        self.rect = Rectangle(x0, y0, x1, y1)
        self.baseline = baseline
        self.waistline = waistline
        self._font_size = font_size  # unmeasured fallback; 0 means unmeasured

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
