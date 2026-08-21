"""The geometry experiment — measure how accurately the pipeline anchors
the tricky pages' lines, and A/B the enhancement candidates against a
KNOWN ground truth (2026-08-20).

The fixtures are SYNTHETIC: a generated letter with margin blocks and
injected failings (misplaced transcription boxes, loose boxes) whose
true geometry is known BY CONSTRUCTION. The metrics: the per-line anchor
IoU, the orientation accuracy, and the reading-order accuracy. Each
candidate is a layout-source configuration; the harness builds the
Layout per candidate and reports the table — the evidence for the
pipeline's enhancement decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from tools.box import overlap
from tools.layout import Detection, Layout
from tools.text import normalize


@dataclass
class TruthLine:
    """A fixture line's known geometry: the text, the box, the
    orientation and the reading position — the ground truth by
    construction."""

    text: str
    box: list[float]
    orientation: int = 0
    position: int = 0


@dataclass
class Fixture:
    """A tricky page: the geometry inputs (what the pipeline consumes)
    plus the known truth."""

    name: str
    width: int
    height: int
    detections: list[Detection]
    marker_boxes: dict[int, list[float]] | None
    truth: list[TruthLine]


@dataclass
class Metrics:
    """The accuracy numbers for one candidate on one fixture."""

    anchor_iou: float
    orientation_accuracy: float
    order_accuracy: float
    coverage: float  # the fraction of truth lines present in the layout


def synthetic_letter() -> Fixture:
    """A letter page with the failing classes the real pages exhibited:
    margin blocks at the top (the P.S. left, the address right), a
    full-width body below, and the transcription boxes MISPLACED for the
    margin lines (the page-03 failing — well-proportioned boxes ~200px
    above the real text). The detections carry the true boxes."""
    width, height = 1000, 2000
    body = [
        ("Chere Maman.", [60, 400, 940, 440]),
        ("I've come to the conclusion", [60, 450, 940, 490]),
        ("that it'll be best if I write", [60, 500, 940, 540]),
        ("some each day, so it won't", [60, 550, 940, 590]),
    ]
    margin = [
        ("P.S. I had a whole Grade 3A", [60, 100, 460, 140]),
        ("theory paper to work before", [60, 150, 460, 190]),
        ("my first Theory lesson today.", [60, 200, 460, 240]),
    ]
    address = [
        ("Postmark 27.9.63", [540, 100, 940, 140]),
        ("Queen Alexandra's House,", [540, 150, 940, 190]),
    ]
    truth_lines = [
        TruthLine(text, list(box), 0, position) for position, (text, box) in enumerate(body + margin + address)
    ]
    detections = cast(
        "list[Detection]",
        [{"box": list(box), "text": text, "score": 0.95, "words": []} for text, box in (body + margin + address)],
    )
    # the injected failing: the transcription boxes for the margin lines
    # sit ~200px above the real text (well-proportioned, in the blank).
    # The marker boxes are the NORMALIZED 0-1000 frame (the layout's
    # vlm_boxes contract).
    misplaced = {}
    for i, (text, box) in enumerate(body + margin + address):
        if text.startswith(("P.S.", "theory", "my first", "Postmark", "Queen")):
            box = [box[0], box[1] - 200, box[2], box[3] - 200]
        misplaced[i] = [box[0] / width * 1000, box[1] / height * 1000, box[2] / width * 1000, box[3] / height * 1000]
    return Fixture("synthetic-letter", width, height, detections, misplaced, truth_lines)


def _matching_line(layout: dict[str, Any], truth: TruthLine) -> dict[str, Any] | None:
    """The layout line whose normalized text matches the truth line's."""
    wanted = normalize(truth.text)
    for line in layout["lines"]:
        if normalize(line.get("text", "")) == wanted:
            return line
    return None


def measure(layout: dict[str, Any], fixture: Fixture) -> Metrics:
    """The candidate's accuracy on the fixture: the mean anchor IoU over
    the matched lines, the orientation agreement, the reading-order
    agreement (the relative positions of the matched pairs), and the
    coverage."""
    ious: list[float] = []
    orientations_ok = 0
    matched: list[tuple[TruthLine, dict[str, Any]]] = []
    for truth in fixture.truth:
        line = _matching_line(layout, truth)
        if line is None:
            continue
        matched.append((truth, line))
        if line.get("box") and truth.box:
            ious.append(overlap(line["box"], truth.box))
        if int(line.get("orientation", 0)) == truth.orientation:
            orientations_ok += 1
    order_ok = 0
    total_pairs = 0
    for i, (ta, la) in enumerate(matched):
        for tb, lb in matched[i + 1 :]:
            total_pairs += 1
            truth_ordered = ta.position < tb.position
            layout_ordered = layout["lines"].index(la) < layout["lines"].index(lb)
            order_ok += truth_ordered == layout_ordered
    return Metrics(
        anchor_iou=sum(ious) / len(ious) if ious else 0.0,
        orientation_accuracy=orientations_ok / len(fixture.truth),
        order_accuracy=order_ok / total_pairs if total_pairs else 1.0,
        coverage=len(matched) / len(fixture.truth),
    )


def report(fixtures: list[Fixture], builder: Any, label: str) -> str:
    """Run one candidate (a Layout builder) over the fixtures and format
    the metric table."""
    rows = []
    for fixture in fixtures:
        layout = builder(fixture)
        m = measure(layout, fixture)
        rows.append(
            f"  {fixture.name:<20} IoU {m.anchor_iou:.2f}  orientation {m.orientation_accuracy:.2f}  "
            f"order {m.order_accuracy:.2f}  coverage {m.coverage:.2f}"
        )
    return f"{label}:\n" + "\n".join(rows)


def baseline_builder(fixture: Fixture) -> dict[str, Any]:
    """The current pipeline: the single-orientation layout with the
    transcription's own boxes (the marker geometry)."""
    vlm_text = "\n".join(t.text for t in fixture.truth)
    return Layout.single(
        "p1.jpg",
        fixture.width,
        fixture.height,
        vlm_text,
        fixture.detections,
        vlm_boxes=fixture.marker_boxes,
    ).to_dict()


def rec_only_builder(fixture: Fixture) -> dict[str, Any]:
    """Candidate: the rec association's ink-grounded boxes instead of the
    marker geometry (no vlm_boxes) — the misplaced-marker failing's
    proposed fix."""
    vlm_text = "\n".join(t.text for t in fixture.truth)
    return Layout.single(
        "p1.jpg",
        fixture.width,
        fixture.height,
        vlm_text,
        fixture.detections,
        vlm_boxes=None,
    ).to_dict()
