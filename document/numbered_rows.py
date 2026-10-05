"""The page with its rows numbered — what the model is shown.

One number per row, in reading order, drawn in the left gutter beside the row
it labels; the number IS the row's number, so the model's answer comes back in
the rows' own space and nothing has to be reconciled geometrically.

A tall page arrives at the model downsampled by its long edge, so the numbers
near the foot reach it unreadably small and the model stops where it can still
see them. `render_strips` cuts the page into big bands instead — each band
keeps its own aspect, so the same digits survive — and every band goes to the
model in ONE call, numbered with the same row numbers, so the answer is read
against one numbering however the page was cut.

The images are returned; this class never writes a file (the pipeline or the
app writes them where the front end needs them).
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from tools.row import Row

ROW_NUM_SIZE = 26  # px: the pill's number, the review surface's own type size
PILL_RADIUS = 12  # px: the pill's corner (`.rv-rownum`'s 10px at page scale)
PILL_PAD_X = 8  # px: air either side of the number
PILL_PAD_Y = 4  # px: air above and below it
PILL_INSET = 6  # px: how far the pill's right edge sits left of the band
PILL_LIFT = 10  # px: how far its top sits above the band's top edge
PILL_MIN_WIDTH = 30  # px: a one-digit pill is still a pill
STRIPS = 3  # bands a tall page is cut into before the model reads it
OVERLAP = 60  # px: how much neighbouring bands share, so no row is lost at a cut
INK_MARGIN = 140  # px: air either side of the writing — the numbers sit in it


class NumberedRows:
    """An image with one number per row drawn on it, and the numbers it drew.

    `numbers` maps each row's id to the number drawn for it; `image` is the
    rendered page (or one band of it). The pair is what an attempt needs: the
    image to show and the numbers to check the answer against.
    """

    def __init__(self, image: Image.Image, numbers: dict[str, int]) -> None:
        self.image = image
        self.numbers = numbers

    @classmethod
    def render(cls, page: Image.Image, rows: list[Row]) -> NumberedRows:
        """The whole page, its rows numbered 1..N in reading order.

        The numbers are the rows' own (`Row.number`), so an answer naming
        numbers 1..N is already in the rows' space. Each number sits in the
        gutter immediately left of its row's own first word, on the row's
        centre line — the convention the review surface numbers its lines by,
        so a reader of either sees the same thing."""
        return cls._draw(page.convert("RGB"), sorted(rows, key=lambda row: row.number), offset_y=0)

    @classmethod
    def render_strips(cls, page: Image.Image, rows: list[Row], *, strips: int = STRIPS) -> list[NumberedRows]:
        """The page in `strips` bands, top to bottom, numbered — one image per
        band, all of them going to the model in ONE call.

        The bands cover the WRITING (a blank margin is not worth an image) and
        the cuts fall in the gaps BETWEEN rows, never through one: a row cut in
        half is a row whose number and its writing part company, which is how a
        reading gets lost. Every row is numbered once, in the band holding it,
        with its own number — an answer is read against that numbering however
        the page was cut."""
        if strips < 1:
            raise ValueError(f"a page needs at least one strip, not {strips}")
        ordered = sorted(rows, key=lambda row: row.number)
        top = min(row.band.y0 for row in ordered)
        bottom = max(row.band.y1 for row in ordered)
        bounds = [top, *_cut_gaps(ordered, strips=strips, top=top, bottom=bottom), bottom]
        xs = [word.x0 for row in ordered for word in row.word_boxes] + [
            word.x1 for row in ordered for word in row.word_boxes
        ]
        ink_left = max(0, int(min(xs) if xs else 0) - INK_MARGIN)
        ink_right = min(page.width, int(max(xs) if xs else page.width) + INK_MARGIN)
        out: list[NumberedRows] = []
        for index in range(strips):
            band_top = int(bounds[index]) - (OVERLAP if index else 0)
            band_bottom = int(bounds[index + 1]) + (OVERLAP if index + 1 < strips else 0)
            band_top, band_bottom = max(0, band_top), min(page.height, band_bottom)
            inside = [
                row
                for row in ordered
                if band_top <= (row.band.y0 + row.band.y1) / 2 < band_bottom
                or (index == strips - 1 and (row.band.y0 + row.band.y1) / 2 >= band_bottom)
            ]
            # the page's own margins are not worth an image: the width sent is
            # the writing's, plus the gutter the numbers sit in. Page-01's
            # writing is 57% of the page's width — sending the paper too costs
            # the model ~40% of the detail it could have had.
            crop = page.convert("RGB").crop((ink_left, band_top, ink_right, band_bottom))
            out.append(cls._draw(crop, inside, offset_y=band_top))
        return out

    @classmethod
    def draw_numbers(cls, canvas: Image.Image, rows: list[Row], *, offset_y: float = 0) -> NumberedRows:
        """`canvas` with the rows' numbers drawn in the gutter, as `render`
        draws them — the one place row numbers are painted, so a caller that
        already has a rendered page (a tinted comparison sheet, say) uses the
        same convention rather than a second one."""
        return cls._draw(canvas, sorted(rows, key=lambda row: row.number), offset_y=offset_y)

    @classmethod
    def _draw(cls, canvas: Image.Image, rows: list[Row], *, offset_y: float) -> NumberedRows:
        """One image with the numbers of `rows` drawn on it, page coordinates
        shifted into this image's own space.

        The number is the review surface's own: a green pill with white type
        sitting on the row's top-left corner (`app/styles.css`, `.rv-rownum`).
        It touches the row it labels, so a number can never be mistaken for
        someone else's row — however close the rows sit, and even where a row's
        band is a sliver inside its neighbours'."""
        numbers = {row.id: row.number for row in rows}
        draw = ImageDraw.Draw(canvas)
        font = _font()
        for row in rows:
            pill_left = row.band.x0 - PILL_INSET
            pill_top = row.band.y0 - offset_y - PILL_LIFT
            text = str(row.number)
            width = draw.textbbox((0, 0), text, font=font)
            pill_w = max(PILL_MIN_WIDTH, (width[2] - width[0]) + 2 * PILL_PAD_X)
            pill_h = (width[3] - width[1]) + 2 * PILL_PAD_Y
            draw.rounded_rectangle(
                (pill_left - pill_w, pill_top, pill_left, pill_top + pill_h),
                radius=PILL_RADIUS,
                fill=(40, 110, 60),
            )
            draw.text(
                (
                    pill_left - pill_w + PILL_PAD_X - width[0],
                    pill_top + PILL_PAD_Y - width[1],
                ),
                text,
                fill=(255, 255, 255),
                font=font,
            )
        return cls(canvas, numbers)

    def rows_drawn(self) -> int:
        """How many rows this image labels — the universe its reading must
        cover (one reading per number, none missing)."""
        return len(self.numbers)


def _cut_gaps(rows: list[Row], *, strips: int, top: float, bottom: float) -> list[float]:
    """Where to cut `strips` bands of writing without cutting a row: the
    largest gaps between consecutive bands, at the boundaries a naive equal
    split would have chosen."""
    gaps = sorted(
        (
            (rows[i + 1].band.y0 - rows[i].band.y1, (rows[i + 1].band.y0 + rows[i].band.y1) / 2)
            for i in range(len(rows) - 1)
        ),
        reverse=True,
    )
    wanted = [top + (bottom - top) * index / strips for index in range(1, strips)]
    chosen: list[float] = []
    for target in wanted:
        nearest = min(gaps, key=lambda gap: abs(gap[1] - target) + (0 if gap[0] >= 0 else 10_000))
        chosen.append(nearest[1])
    return sorted(chosen)


def _font() -> ImageDraw.ImageFont.ImageFont | ImageDraw.ImageFont.FreeTypeFont:
    try:
        return ImageDraw.ImageFont.load_default(size=ROW_NUM_SIZE)
    except TypeError:  # Pillow older than the size-capable default font
        return ImageDraw.ImageFont.load_default()
