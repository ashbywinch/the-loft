"""The fail-fast validation layer — the gates a layout must pass before it
is written or served. Each gate is one check with a plain-language
violation; ``validate_layout`` runs the collection in order. The gates
exist because the review surface must never show a wrong box (2026-08-17:
page-02's approximate boxes reached the review silently) — and they now
detect the geometry failings the pure checks could not see (the inkless
estimates, the duplicated regions).
"""

from __future__ import annotations

from typing import Any

from tools.box import aspect_consistent, overlap, reading_axis
from tools.text import normalize


class Gate:
    """One fail-fast check over a layout; ``violations`` returns the
    plain-language findings ([] = the gate passes)."""

    def violations(self, layout: dict[str, Any], tolerance: float = 4.0) -> list[str]:
        raise NotImplementedError


def _boxed(line: dict[str, Any]) -> list[float] | None:
    """The line's box when it is a well-formed 4-float list, else None —
    a malformed box cannot be checked by the geometry gates."""
    box = line.get("box")
    if isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
        return box
    return None


class IntegrityGate(Gate):
    """A malformed, degenerate or out-of-image box is never an anchor.
    A ``None`` box passes — the line is flagged, the review shows it
    without a box; the tolerance covers the model's estimate slop."""

    def violations(self, layout: dict[str, Any], tolerance: float = 4.0) -> list[str]:
        width = int(layout.get("width", 0))
        height = int(layout.get("height", 0))
        findings: list[str] = []
        for line in layout.get("lines", []):
            box = _boxed(line)
            if box is None:
                if isinstance(line.get("box"), list):
                    findings.append(f"{line.get('text', '')[:20]!r}: malformed box {line['box']}")
                continue
            x0, y0, x1, y1 = box
            if x1 <= x0 or y1 <= y0:
                findings.append(f"{line.get('text', '')[:20]!r}: degenerate box {box}")
            elif x0 < -tolerance or y0 < -tolerance or x1 > width + tolerance or y1 > height + tolerance:
                findings.append(f"{line.get('text', '')[:20]!r}: box outside the image {box}")
        return findings


class AspectGate(Gate):
    """Gate A (2026-08-20): the line's orientation must be consistent with
    its box's aspect. The AXIS (mod 180) handles EXACT angles — an 88.4°
    line is vertical-axis and must have a tall box. Lenient: a 45°
    diagonal and a near-square box never flag."""

    def violations(self, layout: dict[str, Any], tolerance: float = 4.0) -> list[str]:
        findings: list[str] = []
        for line in layout.get("lines", []):
            box = _boxed(line)
            orientation = line.get("orientation")
            if not box or not isinstance(orientation, (int, float)):
                continue
            if not aspect_consistent(orientation, box):
                findings.append(
                    f"{line.get('text', '')[:20]!r}: orientation {orientation:.1f}° inconsistent "
                    f"with a {int(box[2] - box[0])}x{int(box[3] - box[1])} box"
                )
        return findings


def text_extent_violation(text: str, box: list[float], orientation: float | None) -> str | None:
    """Gate B's rule, shared with the anchor arbitration (a candidate box
    must plausibly hold the line's text). Returns the violation or None."""
    axis = reading_axis(box, orientation)
    if not text.strip() and axis > 0:
        return f"{text[:20]!r}: empty text in a {int(box[2] - box[0])}x{int(box[3] - box[1])} box"
    if text.strip():
        # spaces carry no ink — density is judged on real glyphs only
        glyphs = len(text.strip().replace(" ", ""))
        px_per_char = axis / max(1, glyphs)
        # perpendicular extent (2026-08-26): a letter's advance is
        # proportional to its own height, so big print (the Heinz
        # crest's '57 Varieties' at 90 px/char, 'REMINDER', 'POST
        # CARD') is legitimate where the old absolute 80 refused it.
        # The DENSITY floor stays absolute here (2 px/char):
        # association candidates include roomy boxes where a sparse
        # advance is fine — the strict glyph-relative pair lives in
        # glyph_extent_violation for measured ink unions only.
        vertical = orientation is not None and orientation % 180 != 0
        perpendicular = (box[2] - box[0]) if vertical else (box[3] - box[1])
        ceiling = max(30.0, perpendicular * 1.7)
        if px_per_char < 2 or px_per_char > ceiling:
            return (
                f"{text[:20]!r}: text length {len(text.strip())} wildly out of "
                f"sync with a {int(axis)}px reading axis ({px_per_char:.0f} px/char)"
            )
    return None


def glyph_extent_violation(text: str, box: list[float], orientation: float | None) -> str | None:
    """The STRICT pair for MEASURED ink unions (2026-08-26): the batch's
    boxes come from the rec's detection pieces, so their perpendicular
    extent IS the glyph size — both bounds go glyph-relative (advance
    within [0.12, 1.7] × perpendicular; ground truth: audited-correct
    letter rows sit >= 0.17, the birth certificate's crushed 67-char
    column at 0.10). Association candidates must not use this — their
    boxes are roomier than their ink."""
    axis = reading_axis(box, orientation)
    vertical = orientation is not None and orientation % 180 != 0
    perpendicular = (box[2] - box[0]) if vertical else (box[3] - box[1])
    if not text.strip():
        return None  # emptiness is text_extent_violation's business
    glyphs = len(text.strip().replace(" ", ""))
    px_per_char = axis / max(1, glyphs)
    floor = max(2.0, perpendicular * 0.12)
    ceiling = max(30.0, perpendicular * 1.7)
    if px_per_char < floor or px_per_char > ceiling:
        return (
            f"{text[:20]!r}: text length {len(text.strip())} wildly out of "
            f"sync with a {int(axis)}px reading axis ({px_per_char:.0f} px/char)"
        )
    return None


class TextExtentGate(Gate):
    """Gate B (2026-08-20): the recognized text length must not be WILDLY
    out of sync with the box's reading-axis extent — a 500px-wide box
    holding 3 characters is empty or truncated; a 50px box holding 40
    characters is impossible. Loose (only ~2-80 px/char fails — the
    far-too-short nonsense is the >80 side) so handwriting variance
    never false-positives; an empty text with a box fails ("nothing
    there")."""

    def violations(self, layout: dict[str, Any], tolerance: float = 4.0) -> list[str]:
        findings: list[str] = []
        for line in layout.get("lines", []):
            # the ink-layout's labels are the VLM's reads of its
            # ink-truth boxes (2026-08-28): a short read is a TEXT
            # error the reviewer fixes in the UI — the box-level gates
            # already vetted the geometry. The pieces-based lines
            # keep the check (a mismatch there means a wrong box).
            if line.get("box_source") == "ink-layout":
                continue
            box = _boxed(line)
            if not box:
                continue
            violation = text_extent_violation(line.get("text", ""), box, line.get("orientation"))
            if violation:
                findings.append(violation)
        return findings


class RegionGate(Gate):
    """Gate E (2026-08-20): the same region claimed by DIFFERENT text is a
    geometry failing — the postcard's location report gave two message
    lines the same box. The same text in one region is the dedupe's job
    (a fragment); different texts in one region is ambiguity the review
    must see. The anchored lines' loose boxes may legitimately overlap
    slightly, so the bar is half the smaller box."""

    def violations(self, layout: dict[str, Any], tolerance: float = 4.0) -> list[str]:
        boxed = [(ln, ln["box"]) for ln in layout.get("lines", []) if _boxed(ln)]
        findings: list[str] = []
        for i, (a, ab) in enumerate(boxed):
            for b, bb in boxed[i + 1 :]:
                if overlap(ab, bb) >= 0.5 and normalize(a.get("text", "")) != normalize(b.get("text", "")):
                    findings.append(
                        f"{a.get('text', '')[:20]!r} and {b.get('text', '')[:20]!r}: "
                        "same region claimed by different text"
                    )
        return findings


class BoxlessGate(Gate):
    """Gate F (2026-08-22, user: "I want boxless lines to fail during the
    pipeline run so we can figure out how to fix our pipeline!"): a line
    without a box is an unfinished pipeline result — the anchor
    arbitration found no candidate that holds the text, which means the
    geometry pass needs fixing, not a flag in the review. The page fails
    loudly at the write; the reviewer never sees a half-anchored layout.
    (The older ``None``-box-passes rule belongs to the flag era; the
    user's explicit choice supersedes it.)"""

    def violations(self, layout: dict[str, Any], tolerance: float = 4.0) -> list[str]:
        return [
            f"line {line.get('index', i)} is boxless — the pipeline must fix its geometry"
            for i, line in enumerate(layout.get("lines", []))
            if _boxed(line) is None
        ]


# The gates in their run order — the integrity first (a malformed box
# cannot be checked for aspect or extent), then the line-level geometry,
# then the region-level ambiguity. A tuple: the collection is fixed.
GATES: tuple[Gate, ...] = (IntegrityGate(), AspectGate(), TextExtentGate(), RegionGate(), BoxlessGate())


def validate_layout(layout: dict[str, Any], tolerance: float = 4.0) -> list[str]:
    """The fail-fast guard (2026-08-17): a layout whose lines fail any
    gate must NEVER reach the front end — the reviewer must never see
    wrong boxes. Returns the violations; [] = clean."""
    findings: list[str] = []
    for gate in GATES:
        findings.extend(gate.violations(layout, tolerance))
    return findings
