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
