"""The page's words: the detector's words.json artefact.

The detector measures the writing on a page and persists one record per word —
its box in page pixels plus the measures it made of it (the fitted text line,
baseline and waistline). That file is this class's wire: `from_dict` reads it,
refusing anything that is not a RAW word record (a box-only record is a row's
inline word, not this stage's), and `to_dict` writes it. The words are `Word`
records (`document/word.py`) — one type, whether they came from the file or from
the detector in memory.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from document.word import Word

# the fields a RAW word record carries: the detector's own stage. A record
# without them is a box (a row's inline word), never a words.json entry.
RAW_FIELDS = ("x0", "y0", "x1", "y1", "line", "baseline", "waistline")


class Words:
    """The words a page's detector measured — the words.json artefact."""

    def __init__(self, words: list[Word]) -> None:
        self.words = list(words)

    def __iter__(self) -> Iterator[Word]:
        return iter(self.words)

    def __len__(self) -> int:
        return len(self.words)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Words:
        """The words a words.json holds: the page's measured writing.

        Every record must be a raw word record — the box plus the detector's
        line, baseline and waistline. A record missing one is a box, not this
        stage's word, and the file is refused rather than half-read."""
        records = raw.get("words")
        if not isinstance(records, list):
            raise ValueError("not a Words (no top-level 'words' list)")
        words: list[Word] = []
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise ValueError(f"words[{index}] is not a record")
            missing = [key for key in RAW_FIELDS if key not in record]
            if missing:
                raise ValueError(f"words[{index}] missing {sorted(missing)} — not a raw word record")
            words.append(Word.from_dict(record))
        return cls(words)

    def to_dict(self) -> dict[str, Any]:
        """The words as the words.json artefact."""
        return {"words": [word.to_dict() for word in self.words]}
