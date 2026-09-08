"""Strip measurement (strip-grouping-plan slice 1): the page's writing
measured into numbered strips. Kraken+orli measures the line baselines
(tools.htr) — ~32 min/page on this laptop CPU, so the raw baselines
cache — and the baselines cluster into strips by the numbered-strips
spike's y/x-overlap merge (2026-09-07/08). Geometry is measurement;
the model never generates a coordinate (layout-requirements-draft
L3/L11)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from tools.atomic import atomic_write
from tools.htr import segment_page as kraken_segment_page
from tools.pipeline_store import file_sha256

# The merge rule (the spike's, verbatim): an entry joins a cluster when
# it overlaps the cluster's current extent by more than half the SMALLER
# side, in BOTH axes — the same writing shares ink band and x-range.
MERGE_OVERLAP_SHARE = 0.5
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
    of baselines. Measurement, never a generated coordinate."""

    x0: float
    y0: float
    x1: float
    y1: float

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

    def as_box(self) -> list[float]:
        return self.extent.as_box()


@dataclass(frozen=True)
class BaselineCache:
    """The baseline cache record: the page's measurement keyed by the
    image's content sha (the HTR stage's marker rule — a cache from
    other bytes never serves)."""

    input_sha: str
    lines: list[dict[str, Any]]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=1, ensure_ascii=False)

    @classmethod
    def read(cls, path: Path, sha: str) -> BaselineCache | None:
        """The cached measurement when the file matches this sha, else
        None (missing, stale, or foreign cache)."""
        if not path.exists():
            return None
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved.get("input_sha") != sha:
            return None
        return cls(input_sha=sha, lines=saved["lines"])


# lucidlint: ignore record-shape the kraken wire record is htr.segment_page's shape; unpacked to Extents once here
def baseline_entries(lines: list[dict[str, Any]]) -> list[Extent]:
    """Each kraken record's baseline extent; records without baseline
    points measure nothing and are skipped. The float conversion lives
    here — the seam where JSON numbers become measurements."""
    entries = []
    for ln in lines:
        pts = ln.get("baseline") or []
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        entries.append(Extent(x0=float(min(xs)), y0=float(min(ys)), x1=float(max(xs)), y1=float(max(ys))))
    return entries


def cluster_strips(entries: list[Extent]) -> list[Strip]:
    """The spike's transitive merge: each entry joins every cluster whose
    extent it overlaps strongly (both axes, half the smaller side); the
    joined clusters coalesce into the biggest and grow by the entry.
    Strips sort into reading order, degenerate points drop, numbers assign."""
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
        )
        if extent.width == 0 and extent.height == 0:
            continue  # a point: kraken noise, not writing
        extents.append(extent)
    extents.sort(key=lambda t: (t.y0, t.x0))
    return [Strip(i, t) for i, t in enumerate(extents)]


def measure_strips(
    image: Path,
    cache: Path | None = None,
    *,
    _segment: Callable[[Path], list[dict[str, Any]]] | None = None,
) -> list[Strip]:
    """The page's numbered strips. The kraken baseline run is the
    expensive step — cached by the image's content sha (the HTR stage's
    marker rule), so a re-run never re-measures the same page."""
    run = _segment or kraken_segment_page
    if cache is None:
        return cluster_strips(baseline_entries(run(image)))
    sha = file_sha256(image)
    cached = BaselineCache.read(cache, sha)
    if cached is not None:
        return cluster_strips(baseline_entries(cached.lines))
    lines = run(image)
    atomic_write(cache, BaselineCache(input_sha=sha, lines=lines).to_json())
    return cluster_strips(baseline_entries(lines))


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
