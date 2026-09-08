"""The strip measurement stage's contract (tools/strip_measure.py):
kraken's fragmented baselines cluster into numbered strips by y/x
overlap — the numbered-strips spike's rules pinned on synthetic
fixtures (the merge rule, the sliver filter, reading order, and the
baseline cache that saves the ~32-min/page kraken run)."""

# lucidlint: ignore-file fakefs atomic_write's os.replace + PIL's C encoder need real FS; pyfakefs isn't a dependency

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image

from tools.strip_measure import (
    Extent,
    Strip,
    baseline_entries,
    cluster_strips,
    draw_numbered_strips,
    measure_strips,
)


def test_baseline_entries_take_the_points_extent() -> None:
    lines: list[dict[str, Any]] = [
        {"baseline": [[10, 100], [200, 95], [200, 105]]},
        {"baseline": []},
        {"other": 1},
    ]
    assert baseline_entries(lines) == [Extent(x0=10.0, y0=95.0, x1=200.0, y1=105.0)]


def test_fragments_of_one_line_merge() -> None:
    """Two fragments overlapping strongly in BOTH axes are one band of
    writing: the strip spans the union of their ink."""
    strips = cluster_strips([Extent(x0=100, y0=100, x1=400, y1=130), Extent(x0=150, y0=102, x1=700, y1=128)])
    assert len(strips) == 1
    assert strips[0].extent.as_box() == [100.0, 100.0, 700.0, 130.0]


def test_separate_lines_stay_separate() -> None:
    strips = cluster_strips([Extent(x0=100, y0=100, x1=700, y1=130), Extent(x0=100, y0=200, x1=700, y1=230)])
    assert len(strips) == 2


def test_chains_merge_transitively() -> None:
    """a touches b, b touches c, a and c never touch — the chain is one
    strip (the spike's 'chains merge transitively')."""
    strips = cluster_strips(
        [
            Extent(x0=100, y0=100, x1=280, y1=130),
            Extent(x0=180, y0=100, x1=360, y1=130),
            Extent(x0=260, y0=100, x1=440, y1=130),
        ]
    )
    assert len(strips) == 1
    assert strips[0].extent.as_box() == [100.0, 100.0, 440.0, 130.0]


def test_side_by_side_columns_do_not_merge() -> None:
    """The merge needs overlap in BOTH axes: two columns of one y-band
    stay separate until a fragment bridges them."""
    strips = cluster_strips([Extent(x0=100, y0=100, x1=400, y1=130), Extent(x0=500, y0=100, x1=800, y1=130)])
    assert len(strips) == 2


def test_flat_and_vertical_baselines_survive() -> None:
    """A flat typed baseline (zero height) and a vertical baseline
    (2px wide — the rotated-message case) are writing, not slivers:
    only a DEGENERATE point drops."""
    strips = cluster_strips(
        [
            Extent(x0=100, y0=100, x1=700, y1=100),
            Extent(x0=300, y0=400, x1=302, y1=900),
        ]
    )
    assert [(s.number, s.extent.as_box()) for s in strips] == [
        (0, [100.0, 100.0, 700.0, 100.0]),
        (1, [300.0, 400.0, 302.0, 900.0]),
    ]


def test_degenerate_point_baselines_drop() -> None:
    """A single-point baseline measures nothing — it can neither merge
    (zero overlap over zero extent) nor survive the sliver filter."""
    strips = cluster_strips([Extent(x0=50, y0=50, x1=50, y1=50), Extent(x0=100, y0=100, x1=700, y1=130)])
    assert len(strips) == 1


def test_reading_order_and_numbers() -> None:
    """Strips number 0..n-1 top-to-bottom, left-to-right — whatever
    order kraken emitted the baselines in."""
    strips = cluster_strips(
        [
            Extent(x0=400, y0=200, x1=800, y1=230),
            Extent(x0=100, y0=100, x1=300, y1=130),
            Extent(x0=100, y0=200, x1=300, y1=230),
        ]
    )
    assert [(s.number, s.extent.x0, s.extent.y0) for s in strips] == [
        (0, 100.0, 100.0),
        (1, 100.0, 200.0),
        (2, 400.0, 200.0),
    ]


def _fake_segment(runs: list[str]) -> Callable[[Path], list[dict[str, Any]]]:
    # lucidlint: ignore record-shape mirrors the production seam's wire type — a fake must match the real contract
    def fake_segment(img: Path) -> list[dict[str, Any]]:
        runs.append(img.name)
        return [{"baseline": [[10, 100], [200, 100]]}]

    return fake_segment


def test_measure_strips_caches_the_expensive_run(tmp_path: Path) -> None:
    """The kraken run happens ONCE per image content: the cache is keyed
    by the image's sha, a re-run reads it, and no-cache callers just run."""
    image = tmp_path / "page.png"
    image.write_bytes(b"pretend-image-bytes")
    cache = tmp_path / "baselines.json"
    runs: list[str] = []
    segment = _fake_segment(runs)

    first = measure_strips(image, cache, _segment=segment)
    second = measure_strips(image, cache, _segment=segment)
    no_cache = measure_strips(image, None, _segment=segment)

    assert runs == ["page.png", "page.png"]  # miss runs, hit doesn't, no-cache runs
    assert first == second == no_cache
    saved = json.loads(cache.read_text())
    assert saved["input_sha"]  # the cache is keyed by content


def test_measure_strips_remeasures_when_the_image_changes(tmp_path: Path) -> None:
    """A cache from different image bytes never serves — the sha is the
    validity check (the HTR stage's marker rule)."""
    image = tmp_path / "page.png"
    image.write_bytes(b"v1")
    cache = tmp_path / "baselines.json"
    runs: list[str] = []
    segment = _fake_segment(runs)

    measure_strips(image, cache, _segment=segment)
    image.write_bytes(b"v2")
    measure_strips(image, cache, _segment=segment)

    assert runs == ["page.png", "page.png"]
    assert json.loads(cache.read_text())["lines"]  # the cache now serves v2


def test_draw_numbered_strips_annotates_onto_a_new_image(tmp_path: Path) -> None:
    """The grouping read's input: the strips drawn on a COPY — thin
    outlines + margin numbers on a new file, the page image untouched."""
    page = tmp_path / "page.png"
    Image.new("L", (1000, 800), 255).save(page)
    before = page.read_bytes()
    out = tmp_path / "strips.png"

    draw_numbered_strips(page, [Strip(number=0, extent=Extent(x0=100.0, y0=100.0, x1=700.0, y1=130.0))], out)

    assert Image.open(out).size == (1000, 800)
    assert page.read_bytes() == before
