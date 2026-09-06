"""The eval scoring contract (2026-08-26, settled after three sessions
blocked on it): a served page's transcription is scored against a
reference by ORDER-PRESERVING normalized-text matching — each truth
line must appear in the layout's lines at the right place in the
reading order. Position-based PIXEL truth is out of reach for the real
archive (we have reference texts, not reference boxes); the reading-
order dimension is the position that matters for transcription
fidelity, and write-skip is captured: a REFUSED page is counted as
refused, never as wrong text. This is the calibration instrument the
research synthesis demanded — incident-tuned gates become measured
coverage numbers."""

from __future__ import annotations

from typing import Any

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


def score_page(truth_text: str, layout: dict[str, Any] | None) -> dict[str, float | int]:
    """A page's transcription score: the LONGEST COMMON SUBSEQUENCE of
    the reference's and the served layout's NORMALIZED WORD TOKENS,
    over the whole page — granularity-invariant (handwriting wraps at
    arbitrary points, so line-level matching is meaningless), still
    penalizing reordering, tolerant of insertions/omissions. Refused
    pages count as refused, never as wrong text."""
    if layout is None:
        return {"matched": 0, "total": len(words(truth_text)), "refused": 1, "coverage": 0.0}
    served = " ".join(ln.get("text", "") for ln in layout.get("lines", []) if ln.get("text"))
    truth_tokens = words(truth_text)
    served_tokens = words(served)
    matched = _lcs_matches(truth_tokens, served_tokens)
    total = len(truth_tokens)
    return {
        "matched": matched,
        "total": total,
        "refused": 0,
        "coverage": (matched / total) if total else 1.0,
    }
