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
from tools.word_numbering import UNPLACED, place_chips

CHIP_FONT = 28  # px: the smallest a chip's number is drawn at, readable when scaled


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
        numbers 1..N is already in the rows' space. Each chip is a placed
        value (from `place_chips`): it sits where it collides with nothing,
        and a row whose chip cannot be placed refuses the whole render —
        every row is numbered or none is."""
        ordered = sorted(rows, key=lambda row: row.number)
        numbers = {row.id: row.number for row in ordered}
        boxes = [(row.band.x0, row.band.y0, row.band.x1, row.band.y1) for row in ordered]
        chips = place_chips(boxes, list(range(len(boxes))))
        unplaced = [ordered[i].number for i, chip in enumerate(chips) if chip.verdict == UNPLACED]
        if unplaced:
            # every row must be numbered: a row whose chip cannot be placed
            # would be a row the model cannot name, so the render refuses
            raise ValueError(f"no free spot for the number of row(s) {unplaced}")
        canvas = page.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        for chip in chips:
            draw.rounded_rectangle(chip.rect, radius=3, outline=chip.colour, width=2)
            text = str(chip.render_id)
            font = _font(round(chip.font_size))
            tb = draw.textbbox((0, 0), text, font=font)
            draw.text(
                (
                    (chip.rect[0] + chip.rect[2]) / 2 - (tb[2] - tb[0]) / 2,
                    (chip.rect[1] + chip.rect[3]) / 2 - (tb[3] - tb[1]) / 2,
                ),
                text,
                fill=(15, 15, 15),
                font=font,
            )
        return cls(canvas, numbers)

    def rows_drawn(self) -> int:
        """How many rows the render labels — the universe an answer must
        cover (one reading per number, none missing)."""
        return len(self.numbers)


def _font(size: int) -> ImageDraw.ImageFont.ImageFont | ImageDraw.ImageFont.FreeTypeFont:
    try:
        return ImageDraw.ImageFont.load_default(size=max(size, CHIP_FONT))
    except TypeError:  # Pillow older than the size-capable default font
        return ImageDraw.ImageFont.load_default()
