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
import math

from PIL import Image, ImageDraw

from document.colour import Colour
from document.rectangle import Rectangle, overlaps
from document.row import Row
from pipeline.rows.render import RenderStyle

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
PAPER: Colour = Colour(red=255, green=255, blue=255)
# the colour the bands are washed into when the page's own paper cannot be sampled
PILL_MIN_WIDTH = 30  # px: a one-digit pill is still a pill
PILL_STEP = 6  # px: the gap between two pills that had to be stepped apart
# Bands are cut SHORT on purpose, and by HEIGHT. The vision model resizes an
# image by its long edge, so a tall band comes back with the writing at less
# than half the page's resolution — page-01's numbers at the foot arrive
# unreadably small and the reading stops where it can still see them.
#
# Measured (tools/eval_band_size.py, 2026-10-07). Two separate effects:
#   * the whole writing on one image (2360px) lost the BOTTOM EIGHT row numbers
#     — 33 of 41 read — which is resolution, and is what bands are for;
#   * a band's call can come back EMPTY: the same 1286px bands that read 41/41
#     twice named nothing at all once, its neighbour band's 20 rows then missing
#     from the page. That is the model, not the size, and the masked alone path
#     is what repairs it.
# This height read 41/41 in four separate passes, so it sits at the measured-safe
# end of the range rather than at its boundary.
MAX_BAND_HEIGHT = 856  # px: the tallest band measured read in full
STRIPS_MAX = 8  # bands beyond this are cuts without rows to hold
# Neighbouring bands do NOT overlap. They did (60px), to be safe against a cut
# through a row — but the cuts are placed in the gaps BETWEEN rows, so there is
# nothing to be safe about, and the overlap made the model read the shared
# writing twice: page-01's rows 15, 16 and 27 appeared in two bands, and the
# model returned band 2's top lines as rows 17-20 — the same text as 13-16.
BAND_OVERLAP = 0  # px: bands are exclusive; a row is numbered in exactly one
INK_MARGIN = 40  # px: air either side of the writing — the numbers reach into it,
# and `numbers_extent` widens this left edge when a stepped pill needs more

# The chip is the colour its row's BAND is, drawn opaque instead of translucent:
# the same mix of the row's hue into the paper that the band shows, so a number
# and its row are visibly one colour. Two earlier attempts got this wrong in the
# same way — matching the hue and calling it a match. Measured on the rendered
# sheet, the band washes sit at saturation 0.06-0.19 / value 0.90-0.98, and a
# chip at 0.80 / 0.52 is 4-10x more saturated and half as bright: a dark blob
# that belongs to no row. The digit is that same hue taken dark, which reads on
# the wash and introduces no colour of its own.
DIGIT_SATURATION = 0.75
DIGIT_VALUE = 0.42
# A number that cannot sit beside its row steps OUT into the margin, lane by
# lane, and never up or down: a number level with the wrong row points at the
# wrong row (the user saw 38 beside 39). The lanes run out at the page's edge.
MARGIN_LANES = 16

# px the pointer and the leader stop SHORT of a row's writing. Zero was tried:
# a tip exactly on the word's edge paints its outer pixel inside the box — the
# drawing is a few px wide — which is the overlap the user saw.
PILL_TOUCH = 2


# lucidlint: ignore latent-class one rendered document: placement, drawing,
# measures share one state; no field-disjoint partition to split along
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
    def render_strips(
        cls, page: Image.Image, rows: list[Row], *, max_band_height: float = MAX_BAND_HEIGHT
    ) -> list[NumberedRows]:
        """The page in bands, top to bottom, numbered — one image per band, one
        call per band.

        The bands cover the WRITING (a blank margin is not worth an image) and
        the cuts fall in the gaps BETWEEN rows, never through one: a row cut in
        half is a row whose number and its writing part company, which is how a
        reading gets lost. Every row is numbered once, in the band holding it,
        with its own number — an answer is read against that numbering however
        the page was cut.

        The COUNT is the fewest bands that keep every band under the height the
        model reads at full resolution (`MAX_BAND_HEIGHT`, measured) — a short
        page gets one band, a fragment or a postcard is never cut up to fit a
        fixed three, and a tall page gets as many as its writing needs. A cut may
        only fall in a gap between rows, so where rows sit far apart the count
        climbs until each band fits, and a page of very few rows simply cannot be
        cut at all."""
        if max_band_height < 1:
            raise ValueError(f"a band needs a height, not {max_band_height}")
        ordered = sorted(rows, key=lambda row: row.number)
        if not ordered:
            return []
        top = min(row.band.y0 for row in ordered)
        bottom = max(row.band.y1 for row in ordered)
        # the fewest bands that hold every band under the readable height: a cut
        # can only fall in a gap between rows, so the first count the height asks
        # for may leave a band too tall (rows far apart make wide gaps), and the
        # count then climbs until each band fits — a fragment or a postcard
        # never gets cut at all
        most_bands = max(1, min(len(ordered), STRIPS_MAX))
        bands = max(1, min(math.ceil((bottom - top) / max_band_height), most_bands))
        while True:
            bounds = [top, *_cut_gaps(ordered, strips=bands, top=top, bottom=bottom), bottom]
            tallest = max(high - low for low, high in zip(bounds[:-1], bounds[1:], strict=True))
            if bands >= most_bands or tallest <= max_band_height:
                break
            bands += 1
        xs = [word.x0 for row in ordered for word in row.word_boxes] + [
            word.x1 for row in ordered for word in row.word_boxes
        ]
        # the crop spans the numbers (now in the LEFT margin) and the writing
        number_left, _number_right = cls.numbers_extent(ordered)
        ink_left = max(0, int(min(float(min(xs) if xs else 0), float(number_left))) - INK_MARGIN)
        ink_right = min(page.width, int(max(xs) if xs else page.width) + INK_MARGIN)
        out: list[NumberedRows] = []
        for index in range(bands):
            band_top = int(bounds[index]) - (BAND_OVERLAP if index else 0)
            band_bottom = int(bounds[index + 1]) + (BAND_OVERLAP if index + 1 < bands else 0)
            band_top, band_bottom = max(0, band_top), min(page.height, band_bottom)
            inside = [
                row
                for row in ordered
                if band_top <= (row.band.y0 + row.band.y1) / 2 < band_bottom
                or (index == bands - 1 and (row.band.y0 + row.band.y1) / 2 >= band_bottom)
            ]
            # the page's own margins are not worth an image: the width sent is
            # the writing's, plus the gutter the numbers sit in. Page-01's
            # writing is 57% of the page's width — sending the paper too costs
            # the model ~40% of the detail it could have had.
            if not inside:
                continue  # a band with no rows is an image of a margin
            crop = page.convert("RGB").crop((ink_left, band_top, ink_right, band_bottom))
            # BOTH origins are taken off the numbers. With only the y taken off,
            # every number was painted `ink_left` px right of its row — on the
            # middle of the writing, in the middle of a neighbouring row — which
            # is what made the bands unreadable and sent every row to the
            # read-alone path.
            out.append(cls._draw(crop, inside, offset_x=ink_left, offset_y=band_top))
        return out

    @classmethod
    def draw_numbers(
        cls, canvas: Image.Image, rows: list[Row], *, offset_x: float = 0, offset_y: float = 0
    ) -> NumberedRows:
        """`canvas` with the rows' numbers drawn in the gutter, as `render`
        draws them — the one place row numbers are painted, so a caller that
        already has a rendered page (a tinted comparison sheet, say) uses the
        same convention rather than a second one."""
        return cls._draw(canvas, sorted(rows, key=lambda row: row.number), offset_x=offset_x, offset_y=offset_y)

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
    def end_centre(cls, row: Row, *, left_end: bool) -> float:
        """The vertical centre of the end of the row's line the number stands
        beside: the leftmost word's centre for a number to the left, the
        rightmost word's for one to the right.

        Not the whole line's centre: a line of handwriting rises and falls, and
        the band's middle can be a full word's height away from the end the
        pointer actually touches — the number then reads as belonging to the
        line above or below it at exactly the point where that matters."""
        if not row.word_boxes:
            return (row.band.y0 + row.band.y1) / 2
        end = min(row.word_boxes, key=lambda w: w.rect.x0) if left_end else max(row.word_boxes, key=lambda w: w.rect.x1)
        return (end.rect.y0 + end.rect.y1) / 2

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
            left_edge = min((w.rect.x0 for w in row.word_boxes), default=row.band.x0)
            right_edge = max((w.rect.x1 for w in row.word_boxes), default=row.band.x1)
            # each candidate sits level with the END of the line it stands
            # beside, not with the line's middle
            beside = (
                (left_edge - PILL_INSET - width, cls.end_centre(row, left_end=True)),
                (right_edge + PILL_INSET, cls.end_centre(row, left_end=False)),
            )
            for candidate, centre in beside:
                top = centre - height / 2 - PILL_LIFT
                box = Rectangle(candidate, top, candidate + width, top + height)
                if _fits(box, ink, boxes):
                    boxes.append(box)
                    break
            else:
                # the margin is the fallback that always takes the number: the
                # page's left margin is wide, and a number further out is still
                # unmistakably its row's
                centre = cls.end_centre(row, left_end=True)
                top = centre - height / 2 - PILL_LIFT
                boxes.append(_in_lane(Rectangle(margin, top, margin + width, top + height), ink, boxes))
        return boxes

    @classmethod
    def hue_of(cls, index: int) -> float:
        """The hue of the row at this index — the palette band's own, so a
        number and its band are one colour."""
        red, green, blue, _alpha = RenderStyle().colour(index)
        return colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)[0]

    @classmethod
    def pill_colour(cls, index: int, background: Colour | None = None) -> Colour:
        """The colour the row's band shows: the row's hue laid over the
        background at the palette's tint — the same translucent wash
        `render_rows` composites, which is what makes the chip and its band one
        colour instead of two nearly-matching ones."""
        red, green, blue, alpha = RenderStyle().colour(index)
        share = alpha / 255
        layers = zip((red, green, blue), (background or PAPER)[:3], strict=True)
        mixed = [int(channel * share + paper * (1 - share)) for channel, paper in layers]
        first, second, third = mixed
        return Colour(first, second, third)

    @classmethod
    def background_of(cls, canvas: Image.Image, rows: list[Row], *, offset_x: float = 0, offset_y: float = 0) -> Colour:
        """The colour the bands are washed into: ONE sample, taken where no
        writing is — in the writing's own left margin, level with the gap
        BETWEEN two rows, where the tint of neither reaches.

        Sampling a row's own box for its tint was the wrong aim twice over: 31
        of page-01's 41 rows have ink under some point inside the box, and row
        11 has a single word box whose centre is a stroke, so its chip came out
        ink-coloured. The background has no ink in it by construction."""
        ordered = sorted(rows, key=lambda row: row.band.y0)
        if not ordered:
            return Colour(red=255, green=255, blue=255)
        gap_y = (ordered[0].band.y1 + ordered[1].band.y0) / 2 if len(ordered) > 1 else ordered[0].band.y0 - COLUMN_GAP
        ink_left = min(
            (word.x0 - offset_x for row in ordered for word in row.word_boxes),
            default=ordered[0].band.x0 - offset_x,
        )
        x = min(max(int(ink_left) - COLUMN_GAP, 0), canvas.width - 1)
        y = min(max(int(gap_y - offset_y), 0), canvas.height - 1)
        sample = _rgb(canvas.convert("RGB").getpixel((x, y)))
        # a cropped canvas can carry the page's dark edge where the margin
        # should be, which is no background to wash a hue into
        return sample if sum(sample) > 450 else Colour(red=255, green=255, blue=255)

    @classmethod
    def digit_colour(cls, index: int) -> Colour:
        """The same hue taken dark: it reads on the row's own wash and adds no
        colour that is not the row's."""
        red, green, blue = colorsys.hsv_to_rgb(cls.hue_of(index), DIGIT_SATURATION, DIGIT_VALUE)
        return Colour(int(red * 255), int(green * 255), int(blue * 255))

    @classmethod
    def pointer_side(cls, box: Rectangle, row: Row) -> str:
        """Which edge of the number faces its row — the edge the pointer is
        drawn on and the leader leaves from. A number left of its row points
        right, one right of it points left; pointed the other way it aims at
        nothing, which is what the user saw on every number on the page."""
        return "right" if (box.x0 + box.x1) / 2 < (row.band.x0 + row.band.x1) / 2 else "left"

    @classmethod
    def _draw(cls, canvas: Image.Image, rows: list[Row], *, offset_x: float = 0, offset_y: float = 0) -> NumberedRows:
        """One image with the numbers of `rows` drawn on it, page coordinates
        shifted into this image's own space — BOTH axes: a cut-out band has an
        x origin as much as a y one."""
        numbers = {row.id: row.number for row in rows}
        background = cls.background_of(canvas, rows, offset_x=offset_x, offset_y=offset_y)
        draw = ImageDraw.Draw(canvas)
        font = _font()
        for row, box in zip(rows, cls._pill_boxes(rows), strict=False):
            left, top = box.x0 - offset_x, box.y0 - offset_y
            right, bottom = box.x1 - offset_x, box.y1 - offset_y
            measured = draw.textbbox((0, 0), str(row.number), font=font)
            # The chip is its row's hue washed onto the background the bands are
            # washed onto — that background sampled once, where no writing is —
            # so the number and its row are one colour rather than two that
            # nearly match. The digit is the same hue taken dark. The palette
            # index is the row's NUMBER, not its place in this image: in a band
            # the two differ, and the colour stopped matching the band it came
            # from.
            fill = cls.pill_colour(row.number - 1, background)
            ink = cls.digit_colour(row.number - 1)
            edge_left = min((word.x0 for word in row.word_boxes), default=row.band.x0) - offset_x
            edge_right = max((word.x1 for word in row.word_boxes), default=row.band.x1) - offset_x
            centre_y = (top + bottom) / 2
            # the pointer and the leader both sit on the side the row lies
            # beyond, and BOTH stop SHORT of the row's nearest edge — short even
            # of touching it, because the line is drawn 3px wide and a tip on
            # the edge paints its outer pixel onto the first letter. The pointer
            # used to reach a fixed 14px whatever the drawing was doing: beside
            # the end of its line that overshot the 6px inset by 8px and landed
            # on the writing.
            if cls.pointer_side(box, row) == "left":
                touch = edge_right + PILL_TOUCH
                tip, root, row_edge = max(left - PILL_POINTER, touch), left, touch
            else:
                touch = edge_left - PILL_TOUCH
                tip, root, row_edge = min(right + PILL_POINTER, touch), right, touch
            draw.line([(row_edge, centre_y), (root, centre_y)], fill=ink, width=3)
            draw.polygon(
                [
                    (tip, centre_y),
                    (root, top + (bottom - top) / 4),
                    (root, bottom - (bottom - top) / 4),
                ],
                fill=fill,
                outline=ink,
            )
            draw.rounded_rectangle((left, top, right, bottom), radius=PILL_RADIUS, fill=fill, outline=ink)
            draw.text(
                (left + PILL_PAD_X - measured[0], top + PILL_PAD_Y - measured[1]),
                str(row.number),
                fill=ink,
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


def _rgb(pixel: object) -> Colour:
    """A pixel as three channels — PIL hands back a tuple on an RGB image, and
    on an RGB image only, which is what every canvas here is."""
    # every canvas here is RGB, so getpixel returns channels, never a float
    channels: tuple[int, ...] = tuple(pixel)  # type: ignore[arg-type]  # RGB canvas, so channels not a float
    first, second, third = channels[:3]
    return Colour(first, second, third)


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
