"""The eval-side reading machinery: the alone path must show one row and
nothing else — a mask erases whatever is not the row's own words."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from tools.eval_rows_transcript import masked_row, row_crop
from tools.rectangle import Rectangle
from tools.row import Row
from tools.word import Word

PAGE = (2544, 4642)
PAPER = (247, 243, 232)
INK = (60, 60, 60)
FOREIGN = (200, 80, 80)  # a neighbour's ink, painted so it cannot be mistaken


def _row(number: int, words: list[tuple[float, float, float, float]]) -> Row:
    boxes = [Word(x0, y0, x1, y1) for x0, y0, x1, y1 in words]
    band = Rectangle(
        min(w.x0 for w in boxes),
        min(w.y0 for w in boxes),
        max(w.x1 for w in boxes),
        max(w.y1 for w in boxes),
    )
    return Row(id=f"seg-{number}", kind="body", number=number, word_boxes=boxes, band=band)


def test_the_mask_erases_a_neighbour_that_interleaves_vertically() -> None:
    """Rows 36 and 37 interleave in Y — 76px of band overlap — so NO crop
    rectangle holds one without the other, which is why both "alone" crops kept
    showing the same writing. A mask does not need the rectangle: it paints
    every pixel outside the row's own word boxes over in the paper's colour.
    The fixture is the real shape: the neighbour's word sits at the row's
    height, in the gap between the row's own words — inside the crop, in no
    word box (measured: the duplicate pairs' boxes never overlap)."""
    page = Image.new("RGB", (700, 300), PAPER)
    page_draw = ImageDraw.Draw(page)
    page_draw.rectangle((100, 100, 200, 140), fill=INK)
    page_draw.rectangle((400, 100, 500, 140), fill=INK)
    page_draw.rectangle((250, 110, 350, 150), fill=FOREIGN)  # the interleaved neighbour
    row = _row(36, [(100, 100, 200, 140), (400, 100, 500, 140)])
    neighbour = _row(37, [(250, 110, 350, 150)])
    masked = np.asarray(masked_row(row, page, [row, neighbour])).astype(int)
    assert not (np.abs(masked - FOREIGN).max(axis=2) <= 20).any(), "the neighbour's ink survived the mask"
    assert (np.abs(masked - INK).max(axis=2) <= 20).any(), "the row's own ink was erased by the mask"


def test_the_mask_keeps_the_rows_own_ink_untouched() -> None:
    """The erase must not shave the row's own strokes: inside the word boxes
    the pixels are the page's own, outside them everything is paper."""
    page = Image.new("RGB", (700, 300), PAPER)
    ImageDraw.Draw(page).rectangle((100, 100, 300, 140), fill=INK)
    row = _row(1, [(100, 100, 300, 140)])
    masked = np.asarray(masked_row(row, page, [row])).astype(int)
    origin = np.asarray(page.crop((76, 76, 324, 164))).astype(int)
    box = (slice(24, 64), slice(24, 224))  # word (100,100)-(300,140) in crop coords
    assert (np.abs(masked[box] - origin[box]).max()) <= 20, "the row's words were altered by the mask"


def test_the_rect_holds_only_the_rows_words_plus_air() -> None:
    row = _row(2, [(100, 400, 200, 440)])
    rect = row_crop(row, PAGE)
    assert (rect.x0, rect.y0, rect.x1, rect.y1) == (76, 376, 224, 464)
