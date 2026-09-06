"""The text comparison primitives — how the cross-reader engines' words are
tokenized for comparison, and how the VLM's display words are kept verbatim.

The rec model's letter confusions are the SIGNAL ("Aloxandra" vs
"Alexandra" must flag), while its systematic losses are not (diacritics,
apostrophes, punctuation): ``normalize`` strips what the engines lose and
keeps what they confuse.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")
# Apostrophes are REMOVED, not spaced — the rec model drops them
# ("t'écrivons" reads as "tecrivons") so they must not split the token.
# Periods stay spaced so the P.S.I / P.S. I split artifact normalizes equal.
_APOS = re.compile(r"['’]")


def normalize(text: str) -> str:
    """The comparison form: case-folded, diacritics stripped, punctuation
    dropped. Diacritics are stripped because the rec model loses them
    ("Chère" reads as "Chere"); punctuation is dropped so "P.S.]" and
    "P.S.I" normalize to the same token."""
    folded = unicodedata.normalize("NFD", text).casefold()
    folded = "".join(c for c in folded if unicodedata.category(c) != "Mn")
    folded = unicodedata.normalize("NFC", folded)
    folded = _APOS.sub("", folded)
    return _WS.sub(" ", _PUNCT.sub(" ", folded)).strip()


def words(text: str) -> list[str]:
    """The comparison tokens of a text (normalized, non-empty)."""
    return [w for w in normalize(text).split(" ") if w]


def vlm_line_words(line: str) -> list[str]:
    """The VLM line's display words — whitespace tokens, unnormalized (the
    verbatim discipline: the review shows exactly what the model wrote)."""
    return [w for w in line.split(" ") if w]


def flag_line_words(line: str, flagged: set[str]) -> list[dict[str, Any]]:
    """The line's word dicts for the layout, with the self-report's
    flagged words at conf 0.0 (2026-08-26: the wiring seam the batch
    was missing — the UI colours conf-0 words red). Matching uses
    normalize() on BOTH sides — the report cites display words,
    case-insensitively."""
    normalized = {normalize(f) for f in flagged}
    out: list[dict[str, Any]] = []
    for w in vlm_line_words(line):
        out.append({"word": w, "conf": 0.0 if normalize(w) in normalized else 1.0})
    return out


def selfreport_words_by_line(lines: list[str], report: list[dict[str, Any]] | None) -> dict[int, set[str]]:
    """The self-report's flagged words matched by WORD CONTENT, not line
    number (2026-08-26: the report cites the RAW VLM text's numbering,
    but the layout's line indices come from proportional matching — the
    numbers drift when the raw text has empty lines; the word is the
    reliable key). Every line containing the word is flagged."""
    flagged: dict[int, set[str]] = {}
    for entry in report or []:
        word = normalize(str(entry.get("word", "")))
        if not word:
            continue
        for i, line in enumerate(lines):
            if word in {normalize(w) for w in vlm_line_words(line)}:
                flagged.setdefault(i, set()).add(word)
    return flagged


def selfreport_by_line(report: list[dict[str, Any]] | None, n_lines: int) -> dict[int, set[str]]:
    """The self-report's flagged words keyed by 0-based line index —
    lines the model cited beyond the transcript are dropped."""
    by_line: dict[int, set[str]] = {}
    for entry in report or []:
        line = int(entry.get("line", -1)) - 1  # the report is 1-based
        word = str(entry.get("word", ""))
        if 0 <= line < n_lines and word:
            by_line.setdefault(line, set()).add(normalize(word))
    return by_line


def is_struck(word: str) -> bool:
    """The VLM marks crossed-out words with ~~ — they always flag: struck
    text is content the reviewer must handle, whatever the confidence
    signal (walk finding 5, 2026-08-15)."""
    return "~~" in word


def jaccard(a: set[str], b: set[str]) -> float:
    """The word-set similarity — 0 when disjoint, 1 when identical. The
    association's match bar: one word in common is not a match."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
