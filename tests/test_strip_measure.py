"""The strip measurement stage's contract (tools/strip_measure.py): the
row ink profile's line cores — one strip per line of writing, extents
from each band's own ink, reading order, deterministically. Synthetic
pages with drawn ink are the fixtures (the measurement is pure image
processing — no model, no network)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from tools.strip_measure import (
    Extent,
    Strip,
    draw_numbered_strips,
    measure_strips,
)


def _page(tmp_path: Path, lines: list[tuple[int, int, int, int]]) -> Path:
    """A white 1000x800 page with the given ink rectangles drawn on it."""
    page = tmp_path / "page.png"
    img = Image.new("L", (1000, 800), 255)
    draw = ImageDraw.Draw(img)
    for box in lines:
        draw.rectangle(box, fill=0)
    img.save(page)
    return page


def test_one_strip_per_drawn_line(tmp_path: Path) -> None:
    """Three separated lines of ink measure to three strips: each strip's
    extent is its line's own ink, numbered in reading order."""
    page = _page(tmp_path, [(100, 100, 700, 140), (100, 200, 650, 240), (150, 300, 700, 340)])

    strips = measure_strips(page)

    assert len(strips) == 3
    assert [s.number for s in strips] == [0, 1, 2]
    # PIL rectangles are endpoint-inclusive; the band's y is the ink's rows
    assert strips[0].as_box() == [100.0, 100.0, 701.0, 141.0]
    assert strips[1].as_box() == [100.0, 200.0, 651.0, 241.0]
    assert strips[2].as_box() == [150.0, 300.0, 701.0, 341.0]


def test_descender_bridge_merges_two_lines(tmp_path: Path) -> None:
    """Two lines whose ink rows touch through a bridging column measure
    as ONE band — the projection cannot separate them, and inventing a
    split would be a guess, not a measurement."""
    page = tmp_path / "page.png"
    img = Image.new("L", (1000, 800), 255)
    draw = ImageDraw.Draw(img)
    draw.rectangle((100, 100, 400, 140), fill=0)
    draw.rectangle((100, 143, 400, 180), fill=0)  # 2px white gap — under CORE_MERGE_PX
    draw.rectangle((420, 120, 424, 160), fill=0)  # the descender bridging both
    img.save(page)

    strips = measure_strips(page)

    assert len(strips) == 1
    assert strips[0].extent.as_box() == [100.0, 100.0, 425.0, 181.0]


def test_separated_lines_never_merge(tmp_path: Path) -> None:
    """A real inter-line gap (more than CORE_MERGE_PX of white) keeps
    two lines as two strips, even when their x-ranges overlap."""
    page = _page(tmp_path, [(100, 100, 700, 140), (100, 160, 700, 200)])

    strips = measure_strips(page)

    assert len(strips) == 2
    assert strips[0].extent.y1 < strips[1].extent.y0


def test_page_edge_shading_does_not_measure_as_a_line(tmp_path: Path) -> None:
    """A dark band on the page's last rows is scan/binding edge shading,
    not writing — it drops instead of measuring as a full-width line
    (page-02, 2026-09-09: the edge band refused the page)."""
    page = tmp_path / "page.png"
    img = Image.new("L", (1000, 800), 255)
    draw = ImageDraw.Draw(img)
    draw.rectangle((100, 100, 700, 140), fill=0)  # the one real line
    draw.rectangle((100, 798, 900, 799), fill=0)  # the bottom edge shading
    img.save(page)

    strips = measure_strips(page)

    assert len(strips) == 1
    assert strips[0].extent.y1 < 300


def test_blank_page_measures_nothing(tmp_path: Path) -> None:
    page = tmp_path / "page.png"
    Image.new("L", (1000, 800), 255).save(page)

    assert measure_strips(page) == []


def test_faint_rows_are_not_line_cores(tmp_path: Path) -> None:
    """A row of light-gray (above the ink threshold) is not writing —
    the floor keeps the paper's own texture from becoming strips."""
    page = tmp_path / "page.png"
    img = Image.new("L", (1000, 800), 255)
    draw = ImageDraw.Draw(img)
    draw.rectangle((100, 100, 700, 140), fill=0)  # the one real line
    draw.rectangle((100, 300, 700, 340), fill=200)  # light gray, not ink
    img.save(page)

    strips = measure_strips(page)

    assert len(strips) == 1
    assert strips[0].extent.y1 < 300


def test_strip_properties_delegate_to_the_extent() -> None:
    strip = Strip(number=3, extent=Extent(x0=10.0, y0=20.0, x1=110.0, y1=40.0))

    assert strip.width == 100.0
    assert strip.height == 20.0
    assert strip.orientation == 0
    assert strip.as_box() == [10.0, 20.0, 110.0, 40.0]


def test_draw_numbered_strips_annotates_onto_a_new_image(tmp_path: Path) -> None:
    """The grouping read's input: the strips drawn on a COPY — thin
    outlines + margin numbers on a new file, the page image untouched."""
    page = tmp_path / "page.png"
    Image.new("L", (1000, 800), 255).save(page)
    before = page.read_bytes()
    out = tmp_path / "strips.png"

    draw_numbered_strips(page, [Strip(number=0, extent=Extent(x0=100.0, y0=100.0, x1=700.0, y1=140.0))], out)

    assert Image.open(out).size == (1000, 800)
    assert page.read_bytes() == before
