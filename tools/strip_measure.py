"""Strip measurement (strip-grouping-plan slices 1/2b): the page's
writing measured into numbered strips. Kraken+orli measures the line
baselines at BOTH orientations — the page as-is and a quarter-turn
CCW (the Godolphin resolution, 2026-09-08: vertical writing reads
horizontally in the rotated frame, its baselines inverse-map home) —
and the baselines cluster into strips by the numbered-strips spike's
y/x-overlap merge (2026-09-07/08). The kraken runs cache by content
sha (~32 min/page on this laptop CPU). Geometry is measurement; the
model never generates a coordinate (layout-requirements-draft L3/L11)."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from tools.atomic import atomic_write
from tools.htr import segment_page as kraken_segment_page
from tools.layout import remap_box
from tools.pipeline_store import file_sha256

# The merge rule (the spike's, verbatim): an entry joins a cluster when
# it overlaps the cluster's current extent by more than half the SMALLER
# side, in BOTH axes — the same writing shares ink band and x-range.
MERGE_OVERLAP_SHARE = 0.5
# The rotated pass reads the page a quarter-turn CCW — the pipeline's
# degrees-270 pass (Image.rotate(-270) == the ROTATE_90 transpose).
ROTATED_PASS_DEGREES = 270
# A sliver here is a DEGENERATE measurement — a zero-extent point. The
# band floors of the first spike do NOT apply: baseline extents are
# naturally flat (typed lines measure ~2px tall) and a width floor
# would drop vertical writing (the rotated-message pages).
# The drawn annotation: thin green outlines + margin numbers, the
# writing untouched (the grouping read reads THIS image).
STRIP_OUTLINE_COLOR = (0, 150, 0)
STRIP_OUTLINE_WIDTH = 2
MARGIN_NUMBER_SIZE = 30
MARGIN_NUMBER_OFFSET = (-40, -8)  # the number sits in the left margin, above the strip's top


@dataclass(frozen=True)
class Extent:
    """A measured rectangle of the page — the merged extent of a band
    of baselines, in ORIGINAL-image pixels, carrying the reading
    rotation the measurement came from (0 native, or the rotated pass
    when only that frame could see the writing)."""

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
        """The layout's box shape ([x0, y0, x1, y1], original-image px)."""
        return [self.x0, self.y0, self.x1, self.y1]


@dataclass(frozen=True)
class Strip:
    """One measured band of writing: its extent plus the reading-order
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


CACHE_VERSION = 2  # bumped when the measurement logic changes — a cache from an older logic never serves


@dataclass(frozen=True)
class BaselineCache:
    """The baseline cache record: the page's dual-orientation
    measurements keyed by the image's content sha (the HTR stage's
    marker rule — a cache from other bytes never serves) and by the
    measurement logic's version (a cache from older logic never
    serves either)."""

    version: int
    input_sha: str
    entries: list[Extent]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=1, ensure_ascii=False)

    @classmethod
    def read(cls, path: Path, sha: str) -> BaselineCache | None:
        """The cached measurement when the file matches this sha AND the
        current measurement version, else None (missing, stale, foreign,
        or written by older logic)."""
        if not path.exists():
            return None
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved.get("version") != CACHE_VERSION or saved.get("input_sha") != sha:
            return None
        return cls(version=CACHE_VERSION, input_sha=sha, entries=[Extent(**entry) for entry in saved["entries"]])


# lucidlint: ignore record-shape the kraken wire record is htr.segment_page's shape; unpacked to Extents once here
def baseline_entries(lines: list[dict[str, Any]], orientation: int = 0) -> list[Extent]:
    """Each kraken record's baseline extent in ITS OWN frame; records
    without baseline points measure nothing and are skipped. The float
    conversion lives here — the seam where JSON numbers become
    measurements."""
    entries = []
    for ln in lines:
        pts = ln.get("baseline") or []
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        entries.append(
            Extent(x0=float(min(xs)), y0=float(min(ys)), x1=float(max(xs)), y1=float(max(ys)), orientation=orientation)
        )
    return entries


def dual_orientation_entries(image: Path, run: Callable[[Path], list[dict[str, Any]]]) -> list[Extent]:
    """The page's baselines measured at BOTH orientations: the page
    as-is (reading rotation 0) plus the page a quarter-turn CCW —
    vertical writing reads horizontally there and its baselines
    inverse-map home (the Godolphin resolution, 2026-09-08). A rotated
    entry that holds no ink drops BEFORE clustering: orli hallucinates
    baselines over blank card on out-of-distribution rotations
    (page-01, 2026-09-08: 768 phantoms on pure white), and a phantom
    that survives to the merge bridges real clusters into noise."""
    with Image.open(image) as im:
        width, height = im.size
        rotated = im.convert("RGB").transpose(Image.Transpose.ROTATE_90)
    entries = baseline_entries(run(image), orientation=0)
    with tempfile.TemporaryDirectory() as tmp:
        rotated_path = Path(tmp) / "rotated-quarter.jpg"
        rotated.save(rotated_path, quality=95)
        for extent in baseline_entries(run(rotated_path), orientation=ROTATED_PASS_DEGREES):
            box = remap_box(extent.as_box(), ROTATED_PASS_DEGREES, (width, height), (height, width))
            mapped = Extent(x0=box[0], y0=box[1], x1=box[2], y1=box[3], orientation=ROTATED_PASS_DEGREES)
            if extent_has_ink(image, mapped):
                entries.append(mapped)
    return entries


def cluster_strips(entries: list[Extent]) -> list[Strip]:
    """The spike's transitive merge: each entry joins every cluster whose
    extent it overlaps strongly (both axes, half the smaller side); the
    joined clusters coalesce into the biggest and grow by the entry.
    Strips sort into reading order, degenerate points drop, numbers
    assign."""
    clusters: list[list[Extent]] = []
    for e in entries:
        merged = []
        for cluster in clusters:
            cx0, cx1 = min(m.x0 for m in cluster), max(m.x1 for m in cluster)
            cy0, cy1 = min(m.y0 for m in cluster), max(m.y1 for m in cluster)
            y_ov = min(e.y1, cy1) - max(e.y0, cy0)
            x_ov = min(e.x1, cx1) - max(e.x0, cx0)
            if y_ov > MERGE_OVERLAP_SHARE * min(e.height, cy1 - cy0) and x_ov > (
                MERGE_OVERLAP_SHARE * min(e.width, cx1 - cx0)
            ):
                merged.append(cluster)
        if merged:
            biggest = max(merged, key=len)
            for m in merged:
                if m is not biggest:
                    biggest.extend(m)
                    clusters.remove(m)
            biggest.append(e)
        else:
            clusters.append([e])
    extents = []
    for cluster in clusters:
        extent = Extent(
            x0=min(m.x0 for m in cluster),
            y0=min(m.y0 for m in cluster),
            x1=max(m.x1 for m in cluster),
            y1=max(m.y1 for m in cluster),
            # The native pass wins a mixed cluster: the rotated pass
            # exists for writing the native pass cannot see. The GROUP's
            # model-reported reading rotation stays the authority.
            orientation=0 if any(m.orientation == 0 for m in cluster) else ROTATED_PASS_DEGREES,
        )
        if extent.width == 0 and extent.height == 0:
            continue  # a point: kraken noise, not writing
        extents.append(extent)
    extents.sort(key=lambda t: (t.y0, t.x0))
    return [Strip(i, t) for i, t in enumerate(extents)]


def extent_has_ink(image: Path, extent: Extent, pad: int = 6) -> bool:
    """Gate D's principle at the strip seam (2026-08-20): a measured
    extent must contain the ink it claims. The probe pads ±6px (the
    group box's own pad): a baseline estimate can sit a pixel or two
    off the ink it measured."""
    with Image.open(image) as im:
        gray = im.convert("L")
        x0, y0, x1, y1 = (int(v) for v in extent.as_box())
        x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
        x1, y1 = min(gray.width, x1 + pad), min(gray.height, y1 + pad)
    if x1 <= x0 or y1 <= y0:
        return False
    crop = gray.crop((x0, y0, x1, y1))
    table = [255 if v < 128 else 0 for v in range(256)]
    return crop.point(table).getbbox() is not None


def measure_strips(
    image: Path,
    cache: Path | None = None,
    *,
    _segment: Callable[[Path], list[dict[str, Any]]] | None = None,
) -> list[Strip]:
    """The page's numbered strips: kraken measures the baselines at
    both orientations, the baselines cluster into strips. The kraken
    runs are the expensive step — cached by the image's content sha
    (the HTR stage's marker rule), so a re-run never re-measures."""
    run = _segment or kraken_segment_page

    def clustered(entries: list[Extent]) -> list[Strip]:
        # a final degenerate-point sweep; the ink probe ran at the entry
        # level, before the merge
        strips = cluster_strips(entries)
        return [Strip(number=index, extent=strip.extent) for index, strip in enumerate(strips)]

    if cache is None:
        return clustered(dual_orientation_entries(image, run))
    sha = file_sha256(image)
    cached = BaselineCache.read(cache, sha)
    if cached is not None:
        return clustered(cached.entries)
    entries = dual_orientation_entries(image, run)
    atomic_write(cache, BaselineCache(version=CACHE_VERSION, input_sha=sha, entries=entries).to_json())
    return clustered(entries)


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
