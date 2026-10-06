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

import colorsys

from PIL import Image, ImageDraw

from tools.rectangle import Rectangle, overlaps
from tools.render import RenderStyle
from tools.row import Row

ROW_NUM_SIZE = 26  # px: the pill's number, the review surface's own type size
PILL_POINTER = 14  # px: how far the pill's pointer reaches back toward its row
COLUMN_WIDTH = 120  # px: the numbered column added to the page's right side
COLUMN_GAP = 24  # px: air between the writing's widest line and the column
PILL_RADIUS = 12  # px: the pill's corner (`.rv-rownum`'s 10px at page scale)
PILL_PAD_X = 12  # px: air either side of the number
PILL_PAD_Y = 8  # px: air above and below it
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

# The pill is the row's OWN colour at full strength, not a darkened copy of it:
# clamping the channels (what this used to do) shrinks the dominant channel
# first, so a yellow pill came out brown and stopped matching its band. The hue
# is kept and only the value moves, which is what "the same colour, darker"
# means. White digits read at this value on every hue the palette holds.
PILL_SATURATION = 0.80
PILL_VALUE = 0.52
# A number that cannot sit beside its row steps OUT into the margin, lane by
# lane, and never up or down: a number level with the wrong row points at the
# wrong row (the user saw 38 beside 39). The lanes run out at the page's edge.
MARGIN_LANES = 16


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
        # the crop spans the numbers (now in the LEFT margin) and the writing
        number_left, _number_right = cls.numbers_extent(ordered)
        ink_left = max(0, int(min(float(min(xs) if xs else 0), float(number_left))) - INK_MARGIN)
        ink_right = min(page.width, int(max(xs) if xs else page.width) + INK_MARGIN)
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
        return min(b.x0 for b in boxes), max(b.x1 for b in boxes)

    @classmethod
    def _pill_boxes(cls, rows: list[Row]) -> list[Rectangle]:
        """Where every number's pill lands — the placement, without painting.

        The order is the review surface's own: 1. directly LEFT of the row it
        labels; 2. directly RIGHT of it when the left is taken (a line's ink
        reaches into the gap either side); 3. the page's LEFT margin, lane by
        lane outward. A number never moves up or down to find room: level with
        the wrong row, it points at the wrong row."""
        draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        font = _font()
        boxes: list[Rectangle] = []
        ink = [w.rect for r in rows for w in r.word_boxes]
        margin = _margin_column(rows, width=PILL_MIN_WIDTH + 2 * PILL_PAD_X + 12)
        for row in rows:
            measured = draw.textbbox((0, 0), str(row.number), font=font)
            width = max(PILL_MIN_WIDTH, (measured[2] - measured[0]) + 2 * PILL_PAD_X)
            height = (measured[3] - measured[1]) + 2 * PILL_PAD_Y
            centre = (row.band.y0 + row.band.y1) / 2
            top = centre - height / 2 - PILL_LIFT
            left_edge = min((w.rect.x0 for w in row.word_boxes), default=row.band.x0)
            right_edge = max((w.rect.x1 for w in row.word_boxes), default=row.band.x1)
            beside = next(
                (
                    Rectangle(candidate, top, candidate + width, top + height)
                    for candidate in (left_edge - PILL_INSET - width, right_edge + PILL_INSET)
                    if _fits(Rectangle(candidate, top, candidate + width, top + height), ink, boxes)
                ),
                None,
            )
            if beside is not None:
                boxes.append(beside)
                continue
            boxes.append(_in_lane(Rectangle(margin, top, margin + width, top + height), ink, boxes))
        return boxes

    @classmethod
    def hue_of(cls, index: int) -> float:
        """The hue of the row at this index — the palette band's own, so a
        number and its band are one colour."""
        red, green, blue, _alpha = RenderStyle().colour(index)
        return colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)[0]

    @classmethod
    def pill_colour(cls, index: int) -> tuple[int, int, int]:
        """The row's hue at full strength: white digits read on it and it is
        still the row's colour, which a channel-clamped darkening is not."""
        red, green, blue = colorsys.hsv_to_rgb(cls.hue_of(index), PILL_SATURATION, PILL_VALUE)
        return int(red * 255), int(green * 255), int(blue * 255)

    @classmethod
    def pointer_side(cls, box: Rectangle, row: Row) -> str:
        """Which edge of the number faces its row — the edge the pointer is
        drawn on and the leader leaves from. A number left of its row points
        right, one right of it points left; pointed the other way it aims at
        nothing, which is what the user saw on every number on the page."""
        return "right" if (box.x0 + box.x1) / 2 < (row.band.x0 + row.band.x1) / 2 else "left"

    @classmethod
    def _draw(cls, canvas: Image.Image, rows: list[Row], *, offset_y: float) -> NumberedRows:
        """One image with the numbers of `rows` drawn on it, page coordinates
        shifted into this image's own space."""
        numbers = {row.id: row.number for row in rows}
        draw = ImageDraw.Draw(canvas)
        font = _font()
        for index, (row, box) in enumerate(zip(rows, cls._pill_boxes(rows), strict=False)):
            left, top, right, bottom = box.x0, box.y0 - offset_y, box.x1, box.y1 - offset_y
            measured = draw.textbbox((0, 0), str(row.number), font=font)
            # the row's own hue at full strength: the pill and its band are one
            # colour, so a number can be matched to its line by colour alone
            fill = cls.pill_colour(index)
            edge_left = min((word.x0 for word in row.word_boxes), default=row.band.x0)
            edge_right = max((word.x1 for word in row.word_boxes), default=row.band.x1)
            centre_y = (top + bottom) / 2
            # the pointer and the leader both sit on the side the row lies
            # beyond, and the leader stops at the row's NEAREST edge — drawn to
            # the far one it crossed the writing it is meant to point at
            if cls.pointer_side(box, row) == "left":
                tip, root, row_edge = left - PILL_POINTER, left, edge_right
            else:
                tip, root, row_edge = right + PILL_POINTER, right, edge_left
            draw.line([(row_edge, centre_y), (root, centre_y)], fill=fill, width=3)
            draw.polygon(
                [
                    (tip, centre_y),
                    (root, top + (bottom - top) / 4),
                    (root, bottom - (bottom - top) / 4),
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
            )
        return cls(canvas, numbers)

    def rows_drawn(self) -> int:
        """How many rows this image labels — the universe its reading must
        cover (one reading per number, none missing)."""
        return len(self.numbers)


# a number's box, the ink on the page, and the numbers already placed are three
# things, not one clump: the box is a `Rectangle` (the geometry the model
# already has) and the other two are the lists it must stay clear of
def _fits(box: Rectangle, ink: list[Rectangle], placed: list[Rectangle]) -> bool:
    """Whether a number's box would cover ink or another number."""
    return not any(overlaps(box, other) for other in [*ink, *placed])


def _in_lane(box: Rectangle, ink: list[Rectangle], placed: list[Rectangle]) -> Rectangle:
    """The box in the first free lane of the margin, at its own height.

    Lanes run outward from the writing's widest line; the page's left margin is
    wide, and a number further out is still unmistakably its row's. Stepping up
    or down instead is what put 38's number beside 39.
    """
    for lane in range(MARGIN_LANES):
        left = box.x0 - lane * (box.width + COLUMN_GAP)
        if left < 0:
            break
        candidate = Rectangle(left, box.y0, left + box.width, box.y1)
        if _fits(candidate, ink, placed):
            return candidate
    return box


def _margin_column(rows: list[Row], *, width: float = 0.0) -> float:
    """The numbered column's left edge: in the page's LEFT margin, clear of
    every word, so no number can cover writing whatever its height.

    Each pill then sits at its own row's height with a leader line back to it.
    Placing pills beside their own rows failed twice over: the ragged writing
    pushed thirteen of page-01's numbers into the right margin where the model
    never found them, and where rows sit 20px apart the pills covered each
    other."""
    edges = [w.rect.x0 for row in rows for w in row.word_boxes] or [row.band.x0 for row in rows]
    return max(0.0, min(edges) - COLUMN_GAP - width)


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
