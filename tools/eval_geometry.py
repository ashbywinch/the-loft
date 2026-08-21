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
from math import ceil
from typing import Any, cast

from tools.box import overlap
from tools.gates import validate_layout
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
    plus the known truth. The builder verbs run the layout from a given
    geometry source — each candidate is one way the pipeline could
    anchor the lines."""

    name: str
    width: int
    height: int
    detections: list[Detection]
    marker_boxes: dict[int, list[float]] | None
    truth: list[TruthLine]

    def _vlm_text(self) -> str:
        return "\n".join(t.text for t in self.truth)

    def baseline(self) -> dict[str, Any]:
        """The current pipeline: the transcription's own boxes (the marker
        geometry) anchor the single-orientation layout."""
        return Layout.single(
            "p1.jpg",
            self.width,
            self.height,
            self._vlm_text(),
            self.detections,
            vlm_boxes=self.marker_boxes,
        ).to_dict()

    def rec_only(self) -> dict[str, Any]:
        """Candidate: the rec association's ink-grounded boxes instead of
        the marker geometry (no vlm_boxes) — the misplaced-marker
        failing's proposed fix."""
        return Layout.single(
            "p1.jpg",
            self.width,
            self.height,
            self._vlm_text(),
            self.detections,
            vlm_boxes=None,
        ).to_dict()

    def multi(self) -> dict[str, Any]:
        """The multi-orientation layout: the report LOCATES the known text
        at its true boxes (the truth, normalized), the passes validate."""
        report_lines = [
            {
                "index": i,
                "box": [
                    t.box[0] / self.width * 1000,
                    t.box[1] / self.height * 1000,
                    t.box[2] / self.width * 1000,
                    t.box[3] / self.height * 1000,
                ],
                "degrees": t.orientation,
            }
            for i, t in enumerate(self.truth)
        ]
        passes: list[tuple[int, list[dict[str, Any]]]] = cast(
            "list[tuple[int, list[dict[str, Any]]]]", [(0, self.detections)]
        )
        return Layout.multi(
            "p1.jpg",
            self.width,
            self.height,
            passes,
            report_lines=report_lines,
            vlm_text=self._vlm_text(),
            trust_report_degrees=True,
        ).to_dict()


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


def synthetic_postcard() -> Fixture:
    """A postcard back — the genuinely-multi case: the printed top (0°),
    the handwritten message running vertically (90°), the address (0°).
    The report's located boxes carry the truth (the model LOCATED the
    known text); the pass detections are the rec's readings."""
    width, height = 1000, 1500
    printed = [
        ("POST CARD", [300, 30, 700, 80], 0),
        ("Printed in Great Britain", [300, 90, 700, 120], 0),
    ]
    message = [
        ("We are from", [150, 200, 220, 700], 90),
        ("beauford & Mrs", [240, 200, 310, 700], 90),
        ("Hampshire", [330, 200, 400, 700], 90),
    ]
    address = [
        ("Paul Wink", [500, 800, 900, 840], 0),
        ("47 Brighton Grove", [500, 850, 900, 890], 0),
    ]
    all_lines = printed + message + address
    truth = [
        TruthLine(text, list(box), orientation, position) for position, (text, box, orientation) in enumerate(all_lines)
    ]
    detections = cast(
        "list[Detection]",
        [{"box": list(box), "text": text, "score": 0.95, "words": []} for text, box, _ in all_lines],
    )
    marker_boxes = {
        i: [box[0] / width * 1000, box[1] / height * 1000, box[2] / width * 1000, box[3] / height * 1000]
        for i, (_, box, _) in enumerate(all_lines)
    }
    return Fixture("synthetic-postcard", width, height, detections, marker_boxes, truth)


def duplicate_region_fixture() -> Fixture:
    """The injected duplicate-region failing (the postcard's location
    report gave two message lines the SAME box): the truth has the lines
    at distinct positions; the report's boxes claim the same region. The
    RegionGate must fire — the experiment's detection axis."""
    width, height = 1000, 1500
    truth = [
        TruthLine("We are from", [150, 200, 220, 700], 90, 0),
        TruthLine("beauford & Mrs", [240, 200, 310, 700], 90, 1),
    ]
    detections = cast(
        "list[Detection]",
        [{"box": list(t.box), "text": t.text, "score": 0.95, "words": []} for t in truth],
    )
    marker_boxes: dict[int, list[float]] = {0: [150.0, 200.0, 220.0, 700.0], 1: [150.0, 200.0, 220.0, 700.0]}
    return Fixture("duplicate-region", width, height, detections, marker_boxes, truth)


def loose_box_fixture() -> Fixture:
    """The injected loose-box failing (the postcard's stamp lines): the
    location report's box is ~8x the text's true extent (well-placed but
    wildly loose), so Gate B fires and the anchor arbitration must drop
    the box — the line stays flagged, never anchoring a box that refuses
    the page."""
    width, height = 1000, 1500
    truth = [TruthLine("POSTAGE", [820, 300, 880, 320], 0, 0)]
    detections = cast(
        "list[Detection]",
        [{"box": [820, 300, 880, 320], "text": "POSTAGE", "score": 0.95, "words": []}],
    )
    # the report's box: the same region but ~11x the width (the loose
    # estimate — 'POSTAGE' in a 680px box is 97 px/char, over Gate B's 80)
    marker_boxes = {0: [820 / width * 1000, 300 / height * 1000, 1500 / width * 1000, 320 / height * 1000]}
    return Fixture("loose-box", width, height, detections, marker_boxes, truth)


def detection_report(fixtures: list[Fixture], label: str) -> str:
    """The detection axis: for the injected-failing fixtures, how many
    gates fire (the failing is seen) and whether the layout refuses."""
    rows = []
    for fixture in fixtures:
        layout = fixture.baseline()
        findings = validate_layout(layout)
        rows.append(f"  {fixture.name:<20} gate findings {len(findings):>2}  refuses: {bool(findings)}")
    return f"{label}:\n" + "\n".join(rows)


@dataclass
class LocationCost:
    """The clip-location candidate's cost for one fixture: the number of
    model calls and the estimated tokens. The model's per-call overhead
    (the system prompt + the image tokens) dominates small batches — the
    cost-effectiveness question the batch-size sweep answers."""

    calls: int
    tokens: int

    def tokens_per_line(self, n_lines: int) -> float:
        return self.tokens / n_lines if n_lines else 0.0


# The model call's fixed overhead: the system prompt + one image's tokens.
# A line clip at the marker-box resolution is ~a few hundred tokens; the
# overhead is the dominant term at batch size 1.
_OVERHEAD_TOKENS = 800
_CLIP_TOKENS = 300


def clip_location_cost(n_lines: int, batch_size: int) -> LocationCost:
    """The cost of locating ``n_lines`` in batches of ``batch_size``:
    each call carries the overhead + the batch's clips. The larger
    batches amortize the overhead — the sweep's point."""
    calls = ceil(n_lines / batch_size) if n_lines else 0
    tokens = calls * _OVERHEAD_TOKENS + n_lines * _CLIP_TOKENS
    return LocationCost(calls, tokens)


class ClipLocation:
    """The clip-location candidate (2026-08-20): clip each line's marker
    box, ask the model to LOCATE the batch's lines (the exact box within
    the clip + the angle), map the crop boxes back to the page. The
    batch size is the experimental variable — one call per batch, not
    one per line. The SIMULATED locator is perfect WITHIN the clip but
    inherits the crop quality: a marker box that misses the line's ink
    (page-03's misplaced boxes) yields a blank clip no model can locate —
    the line falls back to the rec's match. The real model calls are the
    eval's."""

    def __init__(self, batch_size: int) -> None:
        self.batch_size = batch_size

    def __call__(self, fixture: Fixture) -> dict[str, Any]:
        report_lines = []
        for i, t in enumerate(fixture.truth):
            marker = fixture.marker_boxes.get(i) if fixture.marker_boxes else None
            if marker:
                scaled = [
                    marker[0] / 1000 * fixture.width,
                    marker[1] / 1000 * fixture.height,
                    marker[2] / 1000 * fixture.width,
                    marker[3] / 1000 * fixture.height,
                ]
                locatable = overlap(scaled, t.box) > 0
            else:
                locatable = False
            if locatable:
                report_lines.append(
                    {
                        "index": i,
                        "box": [
                            t.box[0] / fixture.width * 1000,
                            t.box[1] / fixture.height * 1000,
                            t.box[2] / fixture.width * 1000,
                            t.box[3] / fixture.height * 1000,
                        ],
                        "degrees": t.orientation,
                    }
                )
        vlm_text = "\n".join(t.text for t in fixture.truth)
        passes: list[tuple[int, list[dict[str, Any]]]] = cast(
            "list[tuple[int, list[dict[str, Any]]]]", [(0, fixture.detections)]
        )
        return Layout.multi(
            "p1.jpg",
            fixture.width,
            fixture.height,
            passes,
            report_lines=report_lines or None,
            vlm_text=vlm_text,
            trust_report_degrees=True,
        ).to_dict()


def batch_sweep(fixtures: list[Fixture], batch_sizes: list[int]) -> str:
    """The clip-location sweep: the accuracy at each batch size (the
    simulated perfect model — the ceiling) + the cost model's tokens per
    line. The question: does the accuracy hold as the batches grow, and
    how much does the per-line cost drop?"""
    rows = ["  batch  calls  tokens/line  accuracy"]
    for fixture in fixtures:
        n = len(fixture.truth)
        for size in batch_sizes:
            metrics = measure(ClipLocation(size)(fixture), fixture)
            cost = clip_location_cost(n, size)
            rows.append(
                f"  {size:>5}  {cost.calls:>5}  {cost.tokens_per_line(n):>10.0f}  "
                f"IoU {metrics.anchor_iou:.2f} ori {metrics.orientation_accuracy:.2f}"
            )
    return "\n".join(rows)
