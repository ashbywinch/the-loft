"""The row's tint: its geometry, its wire record, and that the pipeline's
raster renderer paints exactly those rectangles."""

from __future__ import annotations

from PIL import Image

from document.colour import Colour
from document.rectangle import Rectangle
from document.row import Row
from document.row_tint import RowTint
from document.word import Word
from pipeline.rows.render import RenderStyle, render_rows


def _row(words: list[Word]) -> Row:
    """One record row: its words' boxes and their exact union."""
    xs0 = min(w.rect.x0 for w in words)
    ys0 = min(w.rect.y0 for w in words)
    xs1 = max(w.rect.x1 for w in words)
    ys1 = max(w.rect.y1 for w in words)
    return Row(
        id="seg-1",
        kind="body",
        number=1,
        word_boxes=list(words),
        band=Rectangle(xs0, ys0, xs1, ys1),
    )


def test_tint_rects_are_the_words_and_their_joins() -> None:
    left = Word(x0=10, y0=10, x1=40, y1=40)
    right = Word(x0=60, y0=15, x1=100, y1=45)
    rects = _row([right, left]).tint_rects()  # given out of order on purpose
    assert rects == (left.rect, right.rect, left.rect.join_band(right.rect))


def test_a_single_word_is_its_own_tint() -> None:
    word = Word(x0=10, y0=10, x1=40, y1=40)
    assert _row([word]).tint_rects() == (word.rect,)


def test_tint_record_round_trips() -> None:
    tint = RowTint.of(
        _row([Word(x0=10, y0=10, x1=40, y1=40), Word(x0=60, y0=15, x1=100, y1=45)]),
        Colour(red=12, green=34, blue=56, alpha=55),
    )
    assert RowTint.from_dict(tint.to_dict()) == tint
    assert tint.to_dict()["colour"] == [12, 34, 56, 55]


def test_render_rows_paints_exactly_the_tint_rects() -> None:
    """The raster renderer and the record draw the same rectangles: every
    rect's centre carries the tint's composite, and the paper outside the
    union is untouched."""
    paper = (250, 250, 245)
    page = Image.new("RGB", (120, 60), paper)
    row = _row([Word(x0=10, y0=10, x1=40, y1=40), Word(x0=60, y0=15, x1=100, y1=45)])
    tint = RowTint.of(row, RenderStyle().colour(0))
    out = render_rows(page, [row])
    expected = (
        Image.alpha_composite(Image.new("RGBA", (1, 1), (*paper, 255)), Image.new("RGBA", (1, 1), tint.colour))
        .convert("RGB")
        .getpixel((0, 0))
    )
    for rect in tint.rects:
        assert out.getpixel((round(rect.cx), round(rect.cy))) == expected, f"rect {rect} not tinted"
    assert out.getpixel((5, 55)) == paper
