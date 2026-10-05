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

CHIP_FONT = 34  # px: the number's own size on the page, readable at page scale
CHIP_LEFT = 96  # px: the gutter the disc occupies, immediately left of the row's words
CHIP_RADIUS = 26  # px: the disc's half-height, so the number never touches the ink
STRIPS = 3  # bands a tall page is cut into before the model reads it
OVERLAP = 60  # px: how much neighbouring bands share, so no row is lost at a cut
DISC_GAP = 4  # px: the least air between one row's number and the next


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
            crop = page.convert("RGB").crop((0, band_top, page.width, band_bottom))
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
        """One image with the numbers of `rows` drawn beside them, page
        coordinates shifted into this image's own space.

        A row's band can be a sliver inside its neighbours' (page-01's row 6 is
        sixteen pixels tall), so two numbers placed naively at their rows'
        centres cover each other and the model cannot read one of them at all.
        The discs are therefore pushed apart in reading order — each keeps its
        own row's height as its place, never another's."""
        numbers = {row.id: row.number for row in rows}
        draw = ImageDraw.Draw(canvas)
        font = _font()
        centres = _spread([(row.band.y0 + row.band.y1) / 2 for row in rows], canvas.height)
        for row, centre in zip(rows, centres, strict=False):
            left = min(word.x0 for word in row.word_boxes) if row.word_boxes else row.band.x0
            disc = (left - CHIP_LEFT, centre - CHIP_RADIUS, left - CHIP_LEFT + 2 * CHIP_RADIUS, centre + CHIP_RADIUS)
            draw.ellipse(disc, fill=(255, 255, 255), outline=(20, 20, 20), width=3)
            text = str(row.number)
            tb = draw.textbbox((0, 0), text, font=font)
            draw.text(
                (
                    (disc[0] + disc[2]) / 2 - (tb[0] + tb[2]) / 2,
                    (disc[1] + disc[3]) / 2 - (tb[1] + tb[3]) / 2,
                ),
                text,
                fill=(15, 15, 15),
                font=font,
            )
        return cls(canvas, numbers)

    def rows_drawn(self) -> int:
        """How many rows this image labels — the universe its reading must
        cover (one reading per number, none missing)."""
        return len(self.numbers)


def _spread(desired: list[float], height: int) -> list[float]:
    """Where the numbers actually sit: their rows' centres when those are far
    enough apart, and an even run across the image when they are not.

    Pushing each colliding number further down accumulates: on page-01 the last
    rows' numbers ended up below the band's own crop, so the model never saw
    39-41 at all. An even run keeps every number inside the image, in reading
    order, and each within reach of its own row — two numbers may sit closer to
    each other than the discs' width would prefer, but none is ever hidden."""
    if not desired:
        return []
    gap = 2 * CHIP_RADIUS + DISC_GAP
    pushed: list[float] = []
    for value in desired:
        if pushed:
            value = max(value, pushed[-1] + gap)
        pushed.append(value)
    top, bottom = CHIP_RADIUS + 2, height - CHIP_RADIUS - 2
    if pushed[-1] <= bottom and pushed[0] >= top:
        return pushed
    if len(desired) == 1:
        return [min(max(desired[0], top), bottom)]
    span = max(1.0, len(desired) - 1)
    return [top + (bottom - top) * index / span for index in range(len(desired))]


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
        return ImageDraw.ImageFont.load_default(size=CHIP_FONT)
    except TypeError:  # Pillow older than the size-capable default font
        return ImageDraw.ImageFont.load_default()
