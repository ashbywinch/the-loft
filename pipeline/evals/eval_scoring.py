"""The eval scoring contract: a served page's transcription is scored
against a reference by ORDER-PRESERVING normalized-text matching —
each truth line must appear in the layout's lines at the right place
in the reading order. Position-based PIXEL truth is out of reach for
the real archive (we have reference texts, not reference boxes); the
reading-order dimension is the position that matters for transcription
fidelity, and write-skip is captured: a REFUSED page is counted as
refused, never as wrong text. This is the calibration instrument the
research synthesis demanded — incident-tuned gates become measured
coverage numbers."""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.layout import Layout
from tools.text import words


def _lcs_matches(a: list[str], b: list[str]) -> int:
    """The longest common subsequence of normalized lines — content
    coverage in reading order, tolerating insertions and omissions
    (a duplicated line shifts nothing; a wrong line in the middle
    costs exactly the content it displaced)."""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp[n][m]


@dataclass(frozen=True)
class PageScore:
    """One page's transcription score against its reference: the matched
    and total normalized word tokens, and whether the page was refused.
    The coverage is the pair's own ratio — a refused page has no coverage
    at all, and an empty reference is trivially covered."""

    matched: int
    total: int
    refused: int  # 1 when the page was refused — captured, never wrong text

    def __post_init__(self) -> None:
        if self.refused and self.matched:
            raise ValueError(f"a refused page is never scored for text, got {self.matched} matches")

    @property
    def coverage(self) -> float:
        """The matched share of the reference's tokens."""
        if self.refused:
            return 0.0
        return (self.matched / self.total) if self.total else 1.0

    @classmethod
    def refused_page(cls, total: int) -> PageScore:
        """The score a refused page carries — captured, never failed."""
        return cls(matched=0, total=total, refused=1)

    @classmethod
    def served(cls, matched: int, total: int) -> PageScore:
        """The score a served page carries."""
        return cls(matched=matched, total=total, refused=0)


def score_page(truth_text: str, layout: Layout | None) -> PageScore:
    """A page's transcription score: the LONGEST COMMON SUBSEQUENCE of
    the reference's and the served layout's NORMALIZED WORD TOKENS,
    over the whole page — granularity-invariant (handwriting wraps at
    arbitrary points, so line-level matching is meaningless), still
    penalizing reordering, tolerant of insertions/omissions. Refused
    pages count as refused, never as wrong text."""
    truth_tokens = words(truth_text)
    if layout is None:
        return PageScore.refused_page(len(truth_tokens))
    served = " ".join(line.text for line in layout.lines if line.text)
    return PageScore.served(_lcs_matches(truth_tokens, words(served)), len(truth_tokens))
