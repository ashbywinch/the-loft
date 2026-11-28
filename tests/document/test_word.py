"""The word's words.json record — the box's four keys, then the measures.

`words.json` is a persisted archive format; the word delegates its box to
`Rectangle`'s own record, so this test pins the resulting key set and order —
a delegation that changed either would change the archive's bytes.
"""

from __future__ import annotations

from document.rectangle import Rectangle
from document.word import Word, WordMeasurements


def test_a_word_serialises_the_box_then_its_measures_in_order() -> None:
    word = Word(1.0, 2.0, 3.0, 4.0, WordMeasurements(baseline=9.0, waistline=4.0, line=7))
    assert isinstance(word.rect, Rectangle)
    assert list(word.to_dict()) == ["x0", "y0", "x1", "y1", "line", "baseline", "waistline"]
    assert word.to_dict() == {
        "x0": 1.0,
        "y0": 2.0,
        "x1": 3.0,
        "y1": 4.0,
        "line": 7,
        "baseline": 9.0,
        "waistline": 4.0,
    }


def test_an_unmeasured_word_serialises_only_the_box() -> None:
    word = Word(1.0, 2.0, 3.0, 4.0)
    assert list(word.to_dict()) == ["x0", "y0", "x1", "y1"]
    assert word.to_dict() == {"x0": 1.0, "y0": 2.0, "x1": 3.0, "y1": 4.0}
