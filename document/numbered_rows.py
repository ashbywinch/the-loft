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

from tools.render import RenderStyle
from tools.row import Row

ROW_NUM_SIZE = 26  # px: the pill's number, the review surface's own type size
PILL_POINTER = 14  # px: how far the pill's pointer reaches back toward its row
COLUMN_WIDTH = 120  # px: the numbered column added to the page's right side
COLUMN_GAP = 24  # px: air between the writing's widest line and the column
PILL_RADIUS = 12  # px: the pill's corner (`.rv-rownum`'s 10px at page scale)
PILL_PAD_X = 8  # px: air either side of the number
PILL_PAD_Y = 4  # px: air above and below it
PILL_INSET = 6  # px: how far the pill's right edge sits left of the band
PILL_LIFT = 0  # px: the pill is centred on its row's own line, not lifted above
# it. Lifted, every number reads as belonging to the line above — "all the
# numbers seem to be a bit high" (user, on the sheet) — and a row whose band
# starts high is lifted furthest, which is how row 7's number came adrift.
PILL_MIN_WIDTH = 30  # px: a one-digit pill is still a pill
PILL_STEP = 6  # px: the gap between two pills that had to be stepped apart
# Bands are cut SHORT on purpose. The vision API downsamples an image by its
# long edge, so a tall band returns the writing at less than half the page's
# resolution — and rows whose bands overlap (page-01's tail stack, 38/39/40/41
# within 20px) become one blur the model reads twice. A short band stays under
# the API's pixel budget and arrives at the page's own resolution.
STRIPS = 3
# Neighbouring bands do NOT overlap. They did (60px), to be safe against a cut
# through a row — but the cuts are placed in the gaps BETWEEN rows, so there is
# nothing to be safe about, and the overlap made the model read the shared
# writing twice: page-01's rows 15, 16 and 27 appeared in two bands, and the
# model returned band 2's top lines as rows 17-20 — the same text as 13-16.
BAND_OVERLAP = 0  # px: bands are exclusive; a row is numbered in exactly one
INK_MARGIN = 40  # px: air either side of the writing — the numbers reach into it,
# and `numbers_extent` widens this left edge when a stepped pill needs more


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
        _number_left, number_right = cls.numbers_extent(ordered)
        ink_right = int(number_right) + INK_MARGIN
        out: list[NumberedRows] = []
        for index in range(strips):
            band_top = int(bounds[index]) - (BAND_OVERLAP if index else 0)
            band_bottom = int(bounds[index + 1]) + (BAND_OVERLAP if index + 1 < strips else 0)
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
            if not inside:
                continue  # a band with no rows is an image of a margin
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
    def numbers_extent(cls, rows: list[Row], *, offset_y: float = 0) -> tuple[float, float]:
        """The left and right edges the numbers reach, page px (right margin).

        A number that shares its corner with another's steps outward, so the
        numbers can reach further left than the writing does. A caller that
        crops an image around the writing must crop around THIS too, or the
        stepped numbers are cut away and the model reports the page as having
        no such row (page-01's rows 6 and 7, twice)."""
        boxes = cls._pill_boxes(rows)
        if not boxes:
            return 0.0, 0.0
        return min(b[0] for b in boxes), max(b[2] for b in boxes)

    @classmethod
    def _pill_boxes(cls, rows: list[Row]) -> list[tuple[float, float, float, float]]:
        """Where every number's pill lands — the placement, without painting.

        Each pill sits on its own row's top-left corner (the review surface's
        `.rv-rownum`); one that would land on another steps OUTWARD into the
        margin, keeping its own row's height, so the pairing stays exact and no
        number is ever hidden or cut."""
        draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        font = _font()
        boxes: list[tuple[float, float, float, float]] = []
        for row in rows:
            text = str(row.number)
            measured = draw.textbbox((0, 0), text, font=font)
            width = max(PILL_MIN_WIDTH, (measured[2] - measured[0]) + 2 * PILL_PAD_X)
            height = (measured[3] - measured[1]) + 2 * PILL_PAD_Y
            # centred on the row's own line and in the RIGHT margin, which is
            # empty (the writing runs to x2006 of a 2544px page) — the left
            # margin is where the crowded rows pushed each other's numbers
            # around. The pill is the row's own hue and points back at it, so
            # the pairing never depends on the number's exact position.
            centre = (row.band.y0 + row.band.y1) / 2
            top = centre - height / 2 - PILL_LIFT
            bottom = top + height
            # clear of EVERY line the pill's own height spans, not just its own:
            # rows sit ~20px apart and a pill is ~34px tall, so ten of page-01's
            # pills lay over a neighbour's writing (row 6's covered row 7, and
            # the tail stack's covered each other) — ink under a label is ink
            # the reader cannot see, and the repeats followed exactly that.
            boxes.append((_column_left(rows), top, _column_left(rows) + width, bottom))
        return boxes

    @classmethod
    def _draw(cls, canvas: Image.Image, rows: list[Row], *, offset_y: float) -> NumberedRows:
        """One image with the numbers of `rows` drawn on it, page coordinates
        shifted into this image's own space."""
        numbers = {row.id: row.number for row in rows}
        draw = ImageDraw.Draw(canvas)
        font = _font()
        style = RenderStyle()
        for index, (row, (left, top, right, bottom)) in enumerate(zip(rows, cls._pill_boxes(rows), strict=False)):
            top -= offset_y
            bottom -= offset_y
            measured = draw.textbbox((0, 0), str(row.number), font=font)
            # the row's OWN hue at full strength (the band is the same colour
            # washed out): the pill and its band are one colour, so a number
            # can be matched to its line by colour alone
            red, green, blue, _alpha = style.colour(index)
            fill = (red, green, blue)
            row_edge = max((word.x1 for word in row.word_boxes), default=row.band.x1)
            centre_y = (top + bottom) / 2
            draw.line([(row_edge, centre_y), (left, centre_y)], fill=fill, width=3)
            draw.polygon(
                [
                    (left - PILL_POINTER, centre_y),
                    (left, top + (bottom - top) / 4),
                    (left, bottom - (bottom - top) / 4),
                ],
                fill=fill,
                outline=(30, 30, 30),
            )
            draw.rounded_rectangle((left, top, right, bottom), radius=PILL_RADIUS, fill=fill, outline=(30, 30, 30))
            draw.text(
                (left + PILL_PAD_X - measured[0], top + PILL_PAD_Y - measured[1]),
                str(row.number),
                fill=(255, 255, 255),
                font=font,
                stroke_width=2,
                stroke_fill=(30, 30, 30),
            )
        return cls(canvas, numbers)

    def rows_drawn(self) -> int:
        """How many rows this image labels — the universe its reading must
        cover (one reading per number, none missing)."""
        return len(self.numbers)


def _column_left(rows: list[Row]) -> float:
    """The numbered column's left edge: clear of the writing's widest line, so
    every number sits in one reserved strip with its own pointer back to its
    row. Placing each pill just right of its own line put thirteen of page-01's
    numbers out in the ragged margin, where the model could not find them: told
    "exactly rows 16..27", it found five of them and reported the rest empty."""
    widest = max((word.x1 for row in rows for word in row.word_boxes), default=0.0)
    return widest + COLUMN_GAP


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
        # one gap per cut: two cuts in the same gap make a band with no rows,
        # which is an image of a margin and a wasted look (a 6-band page has
        # fewer distinct gaps than that on its thin stretches)
        free = [gap for gap in gaps if gap[1] not in chosen]
        if not free:
            break
        chosen.append(min(free, key=lambda gap: abs(gap[1] - target) + (0 if gap[0] >= 0 else 10_000))[1])
    return sorted(chosen)


def _font() -> ImageDraw.ImageFont.ImageFont | ImageDraw.ImageFont.FreeTypeFont:
    try:
        return ImageDraw.ImageFont.load_default(size=ROW_NUM_SIZE)
    except TypeError:  # Pillow older than the size-capable default font
        return ImageDraw.ImageFont.load_default()
