"""The page with its rows numbered — what the model is shown.

One number per row, in reading order, drawn where the row's own writing
begins; the number IS the row's number, so the model's answer comes back in
the rows' own space and nothing has to be reconciled geometrically. The chips
are placed collision-free by the numbering machinery the word numbering
already uses (`tools/word_numbering.py`): the render is drawn, but nothing in
it is inferred — every chip's rectangle is a placed value.

The image is returned; this class never writes a file (the pipeline or the
app writes it where the front end needs it).
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from tools.row import Row

CHIP_FONT = 34  # px: the number's own size on the page, readable at page scale
CHIP_LEFT = 96  # px: the gutter the disc occupies, immediately left of the row's words
CHIP_RADIUS = 26  # px: the disc's half-height, so the number never touches the ink


class NumberedRows:
    """A page rendered with one number per row, and the numbers it drew.

    `numbers` maps each row's id to the number drawn for it; `image` is the
    rendered page. The pair is what an attempt needs: the image to show and
    the numbers to check the answer against.
    """

    def __init__(self, image: Image.Image, numbers: dict[str, int]) -> None:
        self.image = image
        self.numbers = numbers

    @classmethod
    def render(cls, page: Image.Image, rows: list[Row]) -> NumberedRows:
        """The page with its rows numbered 1..N in reading order.

        The numbers are the rows' own (`Row.number`), so an answer naming
        numbers 1..N is already in the rows' space. Each number sits in the
        gutter immediately left of its row's own first word, on the row's
        centre line — the same convention the review surface numbers its
        lines by, so a reader of either sees the same thing. The gutter is
        outside every row's band, so no chip can cover the writing it
        labels."""
        ordered = sorted(rows, key=lambda row: row.number)
        numbers = {row.id: row.number for row in ordered}
        canvas = page.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        font = _font()
        for row in ordered:
            left = min(word.x0 for word in row.word_boxes) if row.word_boxes else row.band.x0
            centre = (row.band.y0 + row.band.y1) / 2
            disc = (left - CHIP_LEFT, centre - CHIP_RADIUS, left - CHIP_LEFT + 2 * CHIP_RADIUS, centre + CHIP_RADIUS)
            draw.ellipse(disc, fill=(255, 255, 255), outline=(20, 20, 20), width=3)
            text = str(row.number)
            tb = draw.textbbox((0, 0), text, font=font)
            draw.text(
                ((disc[0] + disc[2]) / 2 - (tb[2] - tb[0]) / 2, (disc[1] + disc[3]) / 2 - (tb[3] - tb[1]) / 2),
                text,
                fill=(15, 15, 15),
                font=font,
            )
        return cls(canvas, numbers)

    def rows_drawn(self) -> int:
        """How many rows the render labels — the universe an answer must
        cover (one reading per number, none missing)."""
        return len(self.numbers)


def _font() -> ImageDraw.ImageFont.ImageFont | ImageDraw.ImageFont.FreeTypeFont:
    try:
        return ImageDraw.ImageFont.load_default(size=CHIP_FONT)
    except TypeError:  # Pillow older than the size-capable default font
        return ImageDraw.ImageFont.load_default()
