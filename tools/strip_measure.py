"""Strip measurement (strip-grouping-plan slice 1, reworked 2026-09-09):
the page's writing measured into numbered line strips by INK PROJECTION —
the row ink profile's line cores (the house's 0.1% ink floor), one strip
per line of writing. The kraken/orli baseline detector was replaced: it
fragmented ~25 handwritten lines into 768 baselines (and hallucinated
768 more on blank paper in the rotated frame) — measurements that never
corresponded to the page's real lines. Geometry is measurement; the
model never generates a coordinate (layout-requirements-draft L3/L11)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# The row ink floor: a row carries a line core when more than this
# fraction of its pixels are dark (<128) — the house's Gate D clip
# minimum (tools/layout.py _CLIP_INK_MIN).
PROFILE_INK_FLOOR = 0.001
# Contiguous core rows within this distance are one line core.
CORE_MERGE_PX = 6
# The drawn annotation: thin green outlines + margin numbers, the
# writing untouched (the grouping read reads THIS image).
STRIP_OUTLINE_COLOR = (0, 150, 0)
STRIP_OUTLINE_WIDTH = 2
MARGIN_NUMBER_SIZE = 30
MARGIN_NUMBER_OFFSET = (-40, -8)  # the number sits in the left margin, above the strip's top


@dataclass(frozen=True)
class Extent:
    """A measured rectangle of the page — a line band's ink extent, in
    page pixels. Measurement, never a generated coordinate."""

    x0: float
    y0: float
    x1: float
    y1: float
    orientation: int = 0

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    def as_box(self) -> list[float]:
        """The layout's box shape ([x0, y0, x1, y1], page px)."""
        return [self.x0, self.y0, self.x1, self.y1]


@dataclass(frozen=True)
class Strip:
    """One measured line of writing: its extent plus the reading-order
    number the drawn annotation and the grouping read address it by."""

    number: int
    extent: Extent

    @property
    def width(self) -> float:
        return self.extent.width

    @property
    def height(self) -> float:
        return self.extent.height

    @property
    def orientation(self) -> int:
        return self.extent.orientation

    def as_box(self) -> list[float]:
        return self.extent.as_box()


def line_bands(image: Path) -> list[Extent]:
    """The page's line bands from the row ink profile: a row is a line
    core when more than PROFILE_INK_FLOOR of its pixels are dark; core
    rows within CORE_MERGE_PX merge into one band; each band's x-extent
    is the ink it contains. Band order is reading order (top to
    bottom) — the projection cannot see columns, so a two-column page
    measures each band across both columns and the grouping read splits
    them (it owns segment definition, L3). A band touching the page's
    top or bottom edge drops: scan and binding edges shade the outermost
    rows dark, and the shading measures as a full-width "line" (page-02,
    2026-09-09: a 7px band on the page's last rows refused the page)."""
    with Image.open(image) as im:
        gray = im.convert("L")
        width, height = gray.size
        binary = gray.point(lambda v: 255 if v < 128 else 0)
    # the 1px-wide resize averages each binary row: the pixel value IS
    # the row's ink fraction (0..255)
    profile = binary.resize((1, height), Image.Resampling.BOX)
    floor = PROFILE_INK_FLOOR * width
    cores: list[list[int]] = []
    for y in range(height):
        value = profile.getpixel((0, y))
        if isinstance(value, (int, float)) and value > floor:
            if cores and y - cores[-1][1] <= CORE_MERGE_PX:
                cores[-1][1] = y
            else:
                cores.append([y, y])
    bands = []
    for top, bottom in cores:
        if top <= 1 or bottom >= height - 2:
            continue  # the page's own edge shading, not writing
        bbox = binary.crop((0, top, width, bottom + 1)).getbbox()
        if bbox is None:  # pragma: no cover — a band above the floor carries ink by construction
            continue
        bands.append(Extent(x0=float(bbox[0]), y0=float(top), x1=float(bbox[2]), y1=float(bottom + 1)))
    return bands


def measure_strips(image: Path) -> list[Strip]:
    """The page's numbered line strips: one strip per measured line
    band, numbered in reading order."""
    return [Strip(i, extent) for i, extent in enumerate(line_bands(image))]


def draw_numbered_strips(image: Path, strips: list[Strip], out: Path) -> None:
    """The strips drawn on a COPY of the page — the grouping read's
    input image; the original page file is never edited."""
    annotated = Image.open(image).convert("RGB").copy()
    draw = ImageDraw.Draw(annotated)
    font = ImageFont.load_default(size=MARGIN_NUMBER_SIZE)
    for strip in strips:
        draw.rectangle(
            (strip.extent.x0, strip.extent.y0, strip.extent.x1, strip.extent.y1),
            outline=STRIP_OUTLINE_COLOR,
            width=STRIP_OUTLINE_WIDTH,
        )
        draw.text(
            (
                max(4, strip.extent.x0 + MARGIN_NUMBER_OFFSET[0]),
                max(2, strip.extent.y0 + MARGIN_NUMBER_OFFSET[1]),
            ),
            str(strip.number),
            fill=STRIP_OUTLINE_COLOR,
            font=font,
        )
    annotated.save(out, quality=92)
