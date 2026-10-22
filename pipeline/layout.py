"""The layout model — how a page's review layout is built (TECHSPEC
§16.16).

The VLM transcribes the words AND supplies the line geometry; this
module is the deterministic half: the content-based line association,
the anchor resolution (which box and orientation a line takes when the
sources disagree — ``Anchor``), the per-word flags, the reading order
(``tools.reading``), and the fail-fast gates (``tools.gates`` — a
layout that fails them is never written or served). No detector engine
(paddle, kraken) serves the layout path — the geometry comes from the
same VLM that read the page.

The layout JSON per page (written beside ocr-guess, atomic):
    {"page", "width", "height",
     "lines": [{index, text, box, conf, box_source, words: [{word, box, conf}]}],
     "unmatched": [{box, text, conf: 0.0}]}

The records are classes: ``LayoutLine`` (one line — its text, box,
confidence, per-word flags and the detection it came from),
``LayoutWord`` (the per-word entry), ``UnmatchedLine`` (the artefact's
unclaimed line) and ``Layout`` itself — the page's artefact, which owns
the layout JSON. ``LineMatch`` is the association's working record.

    ``box_source`` says how the anchor was found: "report" (the read's
    own per-line box — it read the page, so its box is text-anchored and
    reading-consistent), "content" (the line matched to a segment's
    recognized text, taking its box) or "positional" (the fallback filled
    the line with the next unmatched segment's box in reading order — the
    geometry is real, the text anchor is not; the surface renders these
    dashed). ``unmatched`` carries the segments that matched no
    transcription line and were not positionally assigned (their geometry
    is real; a confident text anchor is not — conf 0).
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from PIL import Image

from document.page_size import PageSize
from pipeline.admission import Admission
from pipeline.association import Association
from pipeline.box_choice import BoxChoice
from pipeline.detection import Detection
from pipeline.detection_pass import DetectionPass
from pipeline.detection_word import DetectionWord
from pipeline.layout_line import (
    BOX_SOURCE_CONTENT,
    BOX_SOURCE_MULTI,
    BOX_SOURCE_POSITIONAL,
    BOX_SOURCE_REPORT,
    BOX_SOURCE_REPORT_UNCONFIRMED,
    LayoutLine,
)
from pipeline.layout_word import LayoutWord
from pipeline.line_match import LineMatch
from pipeline.model.orientation_line import READING_DEGREES, OrientationLine
from pipeline.model.orientation_report import OrientationReport
from pipeline.model.unsure_word import UnsureWord
from pipeline.transcription_line import TranscriptionLine
from pipeline.unmatched_line import UnmatchedLine
from tools.atomic import atomic_write
from tools.box import aspect_consistent, overlap
from tools.gates import text_extent_violation, validate_layout
from tools.reading import order_lines
from tools.store import DiskStore  # noqa: F401 — the architecture test's store-layer marker
from tools.text import is_struck, jaccard, normalize, vlm_line_words, words

# The minimum word-set overlap (Jaccard) for a detector line to claim a VLM
# line. The rec text is noisy on cursive — that noise IS the confidence
# signal — so the matcher tolerates it: one word in common is not a match.
MATCH_THRESHOLD = 0.34

# The VLM's box coordinate system: normalized 0-1000 (fractions of the
# image's width/height, times 1000), rescaled to pixels when anchored.
NORMALIZED_BOX_SCALE = 1000

# Float tolerance for division-underflow protection.
_MIN_AREA_EPSILON = 1e-9
QUARTERS_PER_FULL_TURN = 4  # a full rotation is four quarter-turns (90° each)

# The multi-orientation admission (PRD VR15): a detected line is
# admitted only when the recognizer read REAL text at that orientation
# — confidence + plausibility — never on box shape alone, so an
# accidental upside-down pass's boxes are rejected.
REC_SCORE_GATE = 0.85  # recognition confidence: real words read at the right orientation
MIN_LETTERS = 2  # plausibility: a "real word" has letters, not just shapes
_DEDUPE_OVERLAP = 0.3  # two passes' lines sharing this much of the smaller box are the same physical region
_LOCATED_OVERLAP = 0.5  # the report box must claim at least half of the matched detection's ink to anchor it
_CLIP_INK_MIN = 0.001  # a line clip must carry >= 0.1% dark pixels — a blank clip has nothing to recognize
# A multi line the rec read below this is doubtful — its words flag (conf
# 0.0), the review's red doubt + the mark-fine button (VR4: the rec score
# is the doubt signal — the multi path has no self-report).
WORD_FLAG_THRESHOLD = 0.95


@dataclass(frozen=True)
class PageGeometry:
    """A page's identity and pixel dimensions - the geometry the layout
    passes share (the width/height pair the build functions threaded)."""

    page: str
    width: int
    height: int


@dataclass(frozen=True)
class ClipSeam:
    """The clip->rotate->recognize seam for the rec-only extras: the
    original image and the recognizer callable. Absent = no re-reading
    (the rec fragment rides along)."""

    image: Path
    recognize: Callable[[Path], str | None]


def _det_y(det: Detection) -> float:
    """The detection's top — the sort key for reading order (module-level:
    captures nothing, so it is not a closure)."""
    return det["box"][1]


def _by_top(d: Detection) -> float:
    """Sort key: the box's top — module-level (captures nothing)."""
    return d["box"][1]


def _by_vlm_index(m: LineMatch) -> int:
    """Sort key: the VLM line index — module-level (captures nothing)."""
    return m.vlm_index


def _positional_box_plausible(text: str, box: list[float]) -> bool:
    """The positional fallback's guard: an unmatched detection's box is
    only a plausible anchor for a boxless line when the line's text length
    roughly matches the box's extent — the gate's own rule (Gate B)
    applied at assignment."""
    if not text.strip():
        return False
    box_w = box[2] - box[0]
    box_h = box[3] - box[1]
    if box_w <= 0 or box_h <= 0:
        return False
    return text_extent_violation(text, box, 0.0) is None


def associate_lines(vlm_lines: list[str], detections: list[Detection]) -> Association:
    """Match detector lines to VLM transcription lines by content.

    Reading orders differ (the engines disagree on where a marginal note
    sits), so the match is best normalized word-set overlap above
    MATCH_THRESHOLD, ties broken by reading order (y-first). Each VLM line
    claims at most one detector line and vice versa. Returns (matches,
    unmatched_detections), where matches are in VLM line order.
    """
    vlm_sets = [set(words(line)) for line in vlm_lines]
    used_vlm: set[int] = set()
    used_det: set[int] = set()
    matches: list[LineMatch] = []

    # Greedy in detector reading order: each detector line claims its best
    # still-free VLM line. The pair is dropped when no candidate clears the
    # threshold (the rec text is too noisy to anchor).
    for di in sorted(range(len(detections)), key=lambda i: _det_y(detections[i])):
        det_set = set(words(detections[di]["text"]))
        best: tuple[float, int] = (0.0, -1)
        for vi in range(len(vlm_lines)):
            if vi in used_vlm:
                continue
            score = jaccard(det_set, vlm_sets[vi])
            if score > best[0]:
                best = (score, vi)
        if best[0] >= MATCH_THRESHOLD and best[1] >= 0:
            vi = best[1]
            used_vlm.add(vi)
            used_det.add(di)
            det = detections[di]
            matches.append(
                LineMatch(
                    vlm=vlm_lines[vi],
                    vlm_index=vi,
                    box=det["box"],
                    rec_text=det["text"],
                    rec_score=det["score"],
                    rec_words=words(det["text"]),
                    det_words=list(det.get("words", [])),
                    box_source=BOX_SOURCE_CONTENT,
                    orientation=det.get("orientation", 0),
                )
            )
    matches.sort(key=_by_vlm_index)
    unmatched = [d for i, d in enumerate(detections) if i not in used_det]
    # Positional fallback: the rec model cannot read cursive, so whole
    # pages never content-match and the boxless VLM lines take the
    # unmatched detections in reading order: both lists run
    # top-to-bottom, so the k-th boxless line takes the k-th unmatched
    # detection's geometry. The anchor is positional, not textual (the
    # rec text never matched) — the caller marks it, and the surface
    # renders positional boxes dashed.
    boxless = [vi for vi in range(len(vlm_lines)) if vi not in used_vlm]
    unmatched.sort(key=_by_top)
    matches.extend(
        LineMatch(
            vlm=vlm_lines[vi],
            vlm_index=vi,
            # The positional guard: the detection's box anchors the
            # boxless line ONLY when it plausibly holds the line's text.
            # An absurd box is dropped (the line stays boxless, flagged),
            # never assigned.
            box=det["box"] if _positional_box_plausible(vlm_lines[vi], det["box"]) else None,
            rec_text=det["text"],
            rec_score=det["score"],
            rec_words=words(det["text"]),
            det_words=list(det.get("words", [])),
            box_source=BOX_SOURCE_POSITIONAL,
            orientation=det.get("orientation", 0),
        )
        for vi, det in zip(boxless, unmatched, strict=False)
    )
    matches.sort(key=_by_vlm_index)
    return Association(matches=matches, unmatched=unmatched[len(boxless) :])


def word_conf(vlm_words: list[str], rec_words: list[str]) -> list[float]:
    """Per-VLM-word cross-reader agreement.

    A VLM word agrees with the detector's line when its normalized form
    appears among the detector line's normalized words — otherwise it is
    flagged (the reader must check it). Both sides are normalized here
    (robust to either raw or pre-normalized input): the rec model's noise
    is the signal, so near-misses ("fiist" vs "first") flag while accent
    and apostrophe loss agrees.
    """
    rec_set = {normalize(w) for w in rec_words}
    return [1.0 if normalize(w) in rec_set else 0.0 for w in vlm_words]


def _word_flag(
    word: str,
    *,
    selfreport_line: set[str] | None,
    rec_words: list[str],
    use_selfreport: bool,
) -> float:
    """The per-word flag source (user). With a self-report the
    transcription model's own doubt drives the flags (it is the good
    reader — the cross-reader's agreement over-flagged 75-90% of lines
    because the detector's rec model garbles every cursive line); without
    one, the cross-reader agreement is the fallback. Struck words always
    flag."""
    if is_struck(word):
        return 0.0
    if use_selfreport:
        return 0.0 if normalize(word) in (selfreport_line or set()) else 1.0
    return 0.0 if normalize(word) not in {normalize(w) for w in rec_words} else 1.0


def _words_out(
    vw: list[str],
    *,
    selfreport_line: set[str] | None,
    rec_words: list[str],
    use_selfreport: bool,
) -> list[LayoutWord]:
    """The per-word layout entries for one line — the flag source applies
    per word (self-report / cross-reader fallback / struck)."""
    out: list[LayoutWord] = []
    for w in vw:
        conf = _word_flag(
            w,
            selfreport_line=selfreport_line,
            rec_words=rec_words,
            use_selfreport=use_selfreport,
        )
        out.append(LayoutWord(word=w, box=None, conf=conf))
    return out


def drop_conflicting_boxes(lines: list[LayoutLine]) -> int:
    """Gate E as a correction (2026-08-22): when two lines claim the same
    region with DIFFERENT text, the lower-confidence line's box is an
    estimate that shadows the confirmed anchor — page-03's boxless
    "critic's view. To quote:" box sat on the P.S. margin, refusing the
    whole page at the serve gate. The lower-conf box drops (the line
    stays flagged); the confirmed anchor keeps its region. The same text
    in one region is the dedupe's job, never dropped here. Returns the
    count dropped."""
    boxed = [ln for ln in lines if ln.is_boxed()]
    dropped = 0
    for i, a in enumerate(boxed):
        for b in boxed[i + 1 :]:
            if a.box is None or b.box is None:
                continue
            if overlap(a.box, b.box) >= 0.5 and normalize(a.text) != normalize(b.text):
                if (a.conf or 0.0) < (b.conf or 0.0):
                    a.box = None
                else:
                    b.box = None
                dropped += 1
    return dropped


@dataclass
class Layout:
    """A page's review layout — the lines with their boxes, orientations
    and confidence. Built from the transcription and the geometry sources
    (``Layout.single`` for one-orientation pages, ``Layout.multi`` for the
    combined passes), validated by the gates, ordered for the review pane,
    and written through the store. The dict form (``to_dict``) is the
    JSON the review surface reads."""

    page: str
    width: int
    height: int
    lines: list[LayoutLine]
    unmatched: list[UnmatchedLine]
    # The coordinate frame the boxes live in — declared by the stage's entry
    # points (single/multi) so a reader can check, never assume: the
    # ORIGINAL image's pixels, the same space as width/height. The pure
    # builders declare nothing: their dict never carried the key.
    box_space: str | None = None
    # The wire keys this record does not model — the reviewer's ``rotation``,
    # the store's ``revision`` — carried through so a rewrite loses nothing.
    extra: dict[str, Any] = field(default_factory=dict)

    # the single-path build's inputs mirror build_layout's — a parameter object would obscure the pure pass
    @classmethod
    def single(
        cls,
        page: str,
        width: int,
        height: int,
        vlm_text: str,
        detections: list[Detection],
        selfreport: list[UnsureWord] | None = None,
        vlm_boxes: dict[int, list[float]] | None = None,
    ) -> Layout:
        """The single-orientation layout: the guess text anchored at the
        transcription's own boxes, the rec association filling the rest."""
        layout = build_layout(page, width, height, vlm_text, detections, selfreport=selfreport, vlm_boxes=vlm_boxes)
        layout.box_space = BOX_SPACE_ORIGINAL
        return layout

    # the multi-path build's inputs mirror multi_layout's — a parameter object would obscure the combined pass
    @classmethod
    def multi(
        cls,
        page: str,
        width: int,
        height: int,
        passes: list[DetectionPass],
        report_lines: list[OrientationLine] | None = None,
        vlm_text: str | None = None,
        image: Path | None = None,
        recognize: Callable[[Path], str | None] | None = None,
        trust_report_degrees: bool = False,
    ) -> Layout:
        """The multi-orientation layout: a detection pass at each reported
        orientation, the guess text anchored at the report's per-line
        boxes, the extras re-read from their own upright clips."""
        layout = multi_layout(
            page,
            width,
            height,
            passes,
            report_lines=report_lines,
            vlm_text=vlm_text,
            image=image,
            recognize=recognize,
            trust_report_degrees=trust_report_degrees,
        )
        layout.box_space = BOX_SPACE_ORIGINAL
        return layout

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Layout:
        """The layout a layout JSON (or a rows reading) describes.

        Every line carries its position: the review surface keys the
        edit/verify state, the box clicks and the dual-pane links on
        ``line.index``. The pipeline's writers did not all emit it — a line
        without an index made ``lines.find(l => l.index === undefined)``
        match the FIRST line, so one "Verified" tap saved line 0's text as
        the edit for every row and the whole page rendered as the first
        line, over and over (user: "the transcript on screen is just 'A
        picture of life in music college' repeated over and over again").
        Readers assign the position when the entry lacks it — the layouts
        already on disk load correctly without a rewrite."""
        lines = [
            LayoutLine.from_dict(entry, position)
            for position, entry in enumerate(raw.get("lines") or [])
            if isinstance(entry, dict)
        ]
        unmatched = [UnmatchedLine.from_dict(entry) for entry in raw.get("unmatched") or [] if isinstance(entry, dict)]
        return cls(
            page=str(raw.get("page", "")),
            width=int(raw.get("width") or 0),
            height=int(raw.get("height") or 0),
            lines=lines,
            unmatched=unmatched,
            box_space=raw.get("box_space"),
            extra={key: value for key, value in raw.items() if key not in _LAYOUT_KEYS},
        )

    def validate(self, tolerance: float = 4.0) -> list[str]:
        """The gates' findings — [] = the layout is fit to write and
        serve."""
        return validate_layout(self, tolerance)

    def in_reading_order(self) -> Layout:
        """The block-aware reading order for the review pane — each
        physical block reads whole, the blocks top-to-bottom. The order
        itself is the standalone reading tool's."""
        self.lines = order_lines(self.lines)
        return self

    def drop_inkless(self, image: Path) -> int:
        """Gate D: the boxes whose region holds no ink are estimates, not
        anchors — dropped (the lines stay flagged). Returns the count."""
        return drop_inkless_boxes(self.lines, image)

    def to_dict(self) -> dict[str, Any]:
        """The layout as its JSON — the lines, the unclaimed ink, and the
        wire keys the record carries through, in the order they were read."""
        out: dict[str, Any] = {
            "page": self.page,
            "width": self.width,
            "height": self.height,
        }
        if self.box_space is not None:
            out["box_space"] = self.box_space
        out["lines"] = [line.to_dict() for line in self.lines]
        out["unmatched"] = [line.to_dict() for line in self.unmatched]
        out.update(self.extra)
        return out

    def detections(self) -> list[Detection]:
        """Reconstruct the detection pass from a page's stored layout — the
        reviewer's rotate fix re-anchors these: the matched lines carry their
        detection (box + rec text + score + per-word data), the unmatched ride
        along with their geometry. The texts are rotation-invariant, so the
        reconstruction is exact for a rigid rotation."""
        detections: list[Detection] = []
        for line in self.lines:
            if line.box is None:
                continue
            detections.append(
                Detection(
                    box=line.box,
                    # the VLM-anchored lines carry no rec text — their OWN
                    # text is the content anchor, so the rotation's rebuild
                    # re-associates them exactly
                    text=line.rec_text or line.text,
                    score=line.rec_score or 0.0,
                    words=list(line.det_words or []),
                    orientation=int(line.orientation or 0),
                )
            )
        detections.extend(Detection(box=line.box, text=line.text, score=0.0, words=[]) for line in self.unmatched)
        return detections

    def write(self, path: Path) -> None:
        """Publish a page's layout atomically — a reader must never meet a
        half-written layout (house rule: files other code reads are
        write-then-rename). Fail-fast: a layout with a degenerate or
        out-of-image box is REFUSED — a bad layout must never be persisted,
        let alone served."""
        wire = self.to_dict()
        violations = validate_layout(self)
        if violations:
            raise ValueError(f"refusing to write an invalid layout: {violations}")
        atomic_write(path, json.dumps(wire, indent=1, ensure_ascii=False) + "\n")

    def write_store(self, store: Any, store_path: str) -> None:
        """Versioned layout write via the ``PipelineStore`` — a re-run creates
        a new version instead of overwriting a fixed path. Every write stamps
        the layout's ``revision`` — the store's version AFTER this write —
        so a reader can tell the newest layout from an older one; the drafts
        payload carries the revision and the review surface refreshes when it
        changes."""
        wire = self.to_dict()
        violations = validate_layout(self)
        if violations:
            raise ValueError(f"refusing to write an invalid layout: {violations}")
        versions = store.versions(store_path)
        revision = (versions[-1] + 1) if versions else 1
        stamped = {**wire, "revision": revision}
        store.write(store_path, json.dumps(stamped, indent=1, ensure_ascii=False) + "\n")


# the keys the artefact models itself — everything else is carried through
_LAYOUT_KEYS = frozenset({"page", "width", "height", "box_space", "lines", "unmatched"})

# the box coordinate frame the stage's entry points declare
BOX_SPACE_ORIGINAL = "original-image"


# detections, self-report, VLM boxes — each consumed once by the pure pass; no second function shares the group
def build_layout(
    page: str,
    width: int,
    height: int,
    vlm_text: str,
    detections: list[Detection],
    selfreport: list[UnsureWord] | None = None,
    vlm_boxes: dict[int, list[float]] | None = None,
) -> Layout:
    """The per-page layout the review surface reads.

    Anchors each VLM transcription line to its box — the VLM's OWN
    per-line boxes when the transcription carried geometry (``vlm_boxes``,
    normalized 0-1000 — the model that READ the page anchors each line it
    transcribed; the rec engine cannot read cursive and merges/misses its
    lines), else the detector's box (when one was found) —
    and computes the per-word confidence — the transcription model's own
    self-report (line + word), falling back to cross-reader agreement
    when no self-report has run; the unmatched detector lines ride along
    with conf 0. Coordinates are trusted as the original image's pixels —
    the detection stage asserts that before handing them over (a future
    engine change must fail loudly, not silently misalign).
    """
    vlm_lines = [line for line in vlm_text.split("\n") if line.strip()]
    association = associate_lines(vlm_lines, detections)
    matches, unmatched = association.matches, association.unmatched
    by_index = {match.vlm_index: match for match in matches}
    # the self-report cites 1-based line numbers; the layout lines are 0-based
    report_by_line = _selfreport_by_line(selfreport, len(vlm_lines))
    use_selfreport = selfreport is not None
    lines: list[LayoutLine] = []
    for vi, line in enumerate(vlm_lines):
        vw = vlm_line_words(line)
        if vlm_boxes and vi in vlm_boxes:
            # The marker box anchors ONLY when the Anchor says it is the
            # better source — the rec's ink-grounded content match wins
            # when the marker's estimate misses the text (2026-08-22:
            # page-01's marker boxes sat ~770px above the real text; the
            # single path anchored them unconditionally and the stage's
            # drops patched the symptom).
            anchor = Anchor(
                OrientationLine(index=vi, box=vlm_boxes[vi], degrees=0),
                by_index.get(vi),
                line,
                width,
                height,
            )
            words_out = _words_out(
                vw,
                selfreport_line=report_by_line.get(vi),
                rec_words=[],
                use_selfreport=use_selfreport,
            )
            line_conf = (sum(word.conf for word in words_out) / len(words_out)) if words_out else 0.0
            lines.append(
                LayoutLine(
                    index=vi,
                    text=line,
                    box=anchor.box,
                    conf=line_conf,
                    words=words_out,
                    box_source=anchor.box_source,
                )
            )
            continue
        match = by_index.get(vi)
        if match is None:
            lines.append(
                LayoutLine(
                    index=vi,
                    text=line,
                    box=None,
                    conf=0.0,
                    words=_words_out(
                        vw,
                        selfreport_line=report_by_line.get(vi),
                        rec_words=[],
                        use_selfreport=use_selfreport,
                    ),
                )
            )
            continue
        words_out = _words_out(
            vw,
            selfreport_line=report_by_line.get(vi),
            rec_words=match.rec_words,
            use_selfreport=use_selfreport,
        )
        line_conf = (sum(word.conf for word in words_out) / len(words_out)) if words_out else 0.0
        lines.append(
            LayoutLine(
                index=vi,
                text=line,
                box=match.box,
                conf=line_conf,
                rec_text=match.rec_text,
                rec_score=match.rec_score,
                words=words_out,
                det_words=match.det_words,
                box_source=match.box_source,
                orientation=match.orientation,
            )
        )
    # The single-orientation reading order (2026-08-20, user's
    # requirement): the transcription order IS the block-aware reading —
    # the model read the page block-by-block, and each block's text order
    # is its physical order. The reading-start sort read ROW-by-row
    # across same-y-band margin blocks, interleaving them (page-03's P.S.
    # margin and the address block bounced 10+ times). The single path
    # keeps the transcription order: the display matches the
    # transcription, and the image moves block-by-block, never bouncing.
    # (The MULTI path — multi_layout — keeps the physical sort: the
    # transcription order scrambled the postcard's multi reading.)
    return Layout(
        page=page,
        width=width,
        height=height,
        lines=lines,
        unmatched=[UnmatchedLine(box=det["box"], text=det["text"], conf=0.0) for det in unmatched],
    )


def _selfreport_by_line(selfreport: list[UnsureWord] | None, n_lines: int) -> dict[int, set[str]]:
    """The self-report words keyed by 0-based line index — the report
    cites 1-based line numbers; the layout lines are 0-based."""
    report_by_line: dict[int, set[str]] = {}
    if selfreport:
        for entry in selfreport:
            if 1 <= entry.line <= n_lines:
                report_by_line.setdefault(entry.line - 1, set()).add(normalize(entry.word))
    return report_by_line


def load_layout(path: Path) -> Layout:
    """Read a page's layout JSON (the drafts payload reads these)."""
    return Layout.from_dict(json.loads(path.read_text(encoding="utf-8")))


def load_layout_store(store: Any, store_path: str) -> Layout:
    """Read the latest version of a layout from a ``PipelineStore``."""
    return Layout.from_dict(json.loads(store.read_latest(store_path)))


def load_vlm_boxes(path: Path) -> dict[int, list[float]] | None:
    """The VLM's per-line boxes (normalized 0-1000) from a page's
    transcription sidecar (``page.vlm.json`` — written by
    pipeline.htr.htr_pages_vlm when the model returned geometry). Keyed by
    the line index in the page's .txt (the sidecar stores the non-blank
    entries in order — the .txt's own split skips blanks too). None when
    the page's transcription carried no geometry — the pipeline then
    falls back to the detector's association."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    entries = data.get("lines")
    if not isinstance(entries, list):
        return None
    boxes: dict[int, list[float]] = {}
    for i, entry in enumerate(entries):
        line = TranscriptionLine.of(entry)
        if line is not None:
            boxes[i] = line.box
    return boxes or None


def is_admissible(text: str, score: float) -> bool:
    """Admit a detected line only when the recognizer read real text at
    this orientation (confidence + plausibility) — never on box shape
    alone (PRD VR15)."""
    return float(score) >= REC_SCORE_GATE and sum(1 for ch in text if ch.isalpha()) >= MIN_LETTERS


def remap_box(
    box: list[float],
    degrees: int,
    original: PageSize,
    rotated: PageSize,
) -> list[float]:
    """A box from the rotated frame (rotated = rw×rh) mapped back to the
    original image (original = ow×oh) — the exact inverse of the applied
    rotation. The forward index map of ``Image.rotate(-degrees,
    expand=True)``:
      degrees 90  (CW):  (x, y) -> (oh-1-y, x)
      degrees 180 (flip): (x, y) -> (ow-1-x, oh-1-y)
      degrees 270 (CCW):  (x, y) -> (y, ow-1-x)
    The inverse maps the rotated-frame corners back exactly."""
    ow, oh = original.width, original.height
    del rotated  # the inverse needs only the original dims + the corner rule
    xs: list[float] = []
    ys: list[float] = []
    for x, y in ((box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])):
        if degrees == 90:
            nx, ny = y, oh - 1 - x
        elif degrees == 180:
            nx, ny = ow - 1 - x, oh - 1 - y
        elif degrees == 270:
            nx, ny = ow - 1 - y, x
        else:
            nx, ny = x, y  # 0 — identity
        xs.append(nx)
        ys.append(ny)
    return [round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)]


def admit_and_remap(
    detections: list[Detection],
    degrees: int,
    original: PageSize,
    rotated: PageSize,
) -> Admission:
    """Admit the detector's lines read as real text at this orientation
    (recognition-driven, never shape-only) and remap their boxes from the
    rotated frame back to the original image. Returns (kept, rejected)."""
    kept: list[Detection] = []
    rejected: list[Detection] = []
    for det in detections:
        text = det["text"].strip()
        score = float(det["score"])
        words = [
            DetectionWord(box=remap_box(word.box, degrees, original, rotated) if word.box else None)
            for word in det.get("words", [])
        ]
        if is_admissible(text, score):
            kept.append(
                Detection(
                    box=remap_box(det["box"], degrees, original, rotated),
                    text=text,
                    score=round(score, 2),
                    words=words,
                )
            )
        else:
            rejected.append(
                Detection(box=[round(v, 1) for v in det["box"]], text=text, score=round(score, 2), words=words)
            )
    return Admission(kept=kept, rejected=rejected)


def _drop_fragment_subsets(lines: list[LayoutLine], keep: list[bool]) -> None:
    """The fragment-subset rule: a SHORT line (<=2 tokens)
    whose tokens are a strict subset of another's is the same text
    read as a fragment — the mirror passes' rec reading a piece of an
    anchored line ('HOUSE,' next to 'HERNSPETH HOUSE,') — dropped even
    when its box landed elsewhere."""
    token_sets = [set(words(line.text)) for line in lines]
    for i in range(len(lines)):
        if not keep[i]:
            continue
        ta = token_sets[i]
        if not (0 < len(ta) <= 2):
            continue
        for j in range(len(lines)):
            if i == j or not keep[j]:
                continue
            if ta < token_sets[j]:
                keep[i] = False
                break


def _weaker_duplicate(a: LayoutLine, b: LayoutLine) -> bool:
    """Is ``a`` the weaker reading of ``b``'s physical region? Extracted
    from dedupe_regions. A boxless line has no region to dedupe — never
    a duplicate."""
    if a.box is None or b.box is None:
        return False
    return overlap(a.box, b.box) > _DEDUPE_OVERLAP and b.richness() > a.richness()


def dedupe_regions(lines: list[LayoutLine]) -> list[LayoutLine]:
    """Drop the weaker readings of the same physical region across
    orientations. The anchored lines (the model's authoritative
    transcription) are never dropped — its estimated boxes can overlap
    between DISTINCT lines, so the box-overlap rule applies only to the
    rec extras. The fragment-subset rule (a short line whose tokens are
    a subset of another's) applies to all. The survivors keep their index
    — the caller re-indexes after."""
    anchored = {i for i, line in enumerate(lines) if line.is_anchored()}
    keep = [True] * len(lines)
    for i, a in enumerate(lines):
        if i in anchored:
            continue
        for j, b in enumerate(lines):
            if i == j or not keep[i] or not keep[j]:
                continue
            if _weaker_duplicate(a, b):
                keep[i] = False
                break
    _drop_fragment_subsets(lines, keep)
    return [line for line, k in zip(lines, keep, strict=True) if k]


def _multi_line_words(text: str, boxes: list[DetectionWord], score: float) -> list[LayoutWord]:
    """The per-word entries for a multi-orientation line: the rec text's
    tokens (the display words — verbatim, vlm_line_words) paired with the
    detector's remapped word boxes (extra tokens get no box; extra boxes
    drop), and the flag convention — a line the rec read weakly flags ALL
    its words (conf 0.0: the review's red doubt + the mark-fine button).
    The words always carry their text — a blank line with no check
    buttons leaves the reader no way to mark it fine."""
    tokens = vlm_line_words(text)
    out: list[LayoutWord] = []
    for i, token in enumerate(tokens):
        box = boxes[i].box if i < len(boxes) else None
        out.append(LayoutWord(word=token, box=box, conf=0.0 if score < WORD_FLAG_THRESHOLD else score))
    return out


def _anchored_lines(
    geometry: PageGeometry,
    report_lines: list[OrientationLine],
    confirmed: set[int],
) -> list[LayoutLine]:
    """The model-anchored lines of the multi layout (2026-08-17): the
    report's transcription lines at their own boxes — the box holds the
    words it claims (VR14). ``confirmed`` = the report line indices a rec
    detection content-matched; those read clean, the rest flag."""
    lines: list[LayoutLine] = []
    for i, report in enumerate(report_lines):
        text = str(report.text or "").strip()
        if not text:
            continue
        b = report.box or [0, 0, 0, 0]
        is_confirmed = i in confirmed
        lines.append(
            LayoutLine(
                index=len(lines),
                text=text,
                box=[
                    b[0] / NORMALIZED_BOX_SCALE * geometry.width,
                    b[1] / NORMALIZED_BOX_SCALE * geometry.height,
                    b[2] / NORMALIZED_BOX_SCALE * geometry.width,
                    b[3] / NORMALIZED_BOX_SCALE * geometry.height,
                ],
                conf=1.0 if is_confirmed else 0.0,
                orientation=int(report.degrees),
                box_source=BOX_SOURCE_REPORT if is_confirmed else BOX_SOURCE_REPORT_UNCONFIRMED,
                words=[LayoutWord(word=w, box=None, conf=1.0 if is_confirmed else 0.0) for w in vlm_line_words(text)],
            )
        )
    return lines


class Anchor:
    """A line's geometry resolution — the box and orientation it takes
    when the sources disagree. The report's located box is the v3
    anchor. A CONTENT match's ink-grounded box overrides it only when
    the report's estimate misses the text's region (a disjoint box). A
    POSITIONAL match's box is only the line's real region when the rec
    READ the line's text there (the rec_words agree) — then it wins
    over a disjoint report estimate; otherwise the unrelated ink must
    not displace a good report box. The orientation is the first
    aspect-consistent candidate: the report's measured degrees when
    trusted (the clip-classified report), else the pass that READ the
    text (the 90-vs-270 flip's ground truth), then the report's
    estimate, then 0."""

    # the geometry resolution's six inputs — the report line, the match, the text, the page geometry, the trust
    # flag; a parameter object would obscure the pure decision (the same why as multi_layout's)
    def __init__(
        self,
        report_line: OrientationLine | None,
        match: LineMatch | None,
        text: str,
        width: int,
        height: int,
        trust_report_degrees: bool = False,
    ) -> None:
        (
            self._report_line,
            self._match,
            self._text,
            self._width,
            self._height,
            self._trust_report_degrees,
        ) = report_line, match, text, width, height, trust_report_degrees
        self._box: list[float] | None = None
        self._orientation = 0
        self._resolve()

    @property
    def box(self) -> list[float] | None:
        return self._box

    @property
    def orientation(self) -> int:
        return self._orientation

    @property
    def box_source(self) -> str:
        """Which source the chosen box came from: "report" (the located
        estimate), "content" (the rec's ink-grounded match) or
        "positional" (the fallback)."""
        return self._box_source

    @staticmethod
    def _report_refines(match: LineMatch, scaled: list[float], fallback_source: str) -> BoxChoice:
        """The report's located box refines the match's ink-grounded box
        when they agree (overlap); the match's OWN box keeps its source
        otherwise. The one decision both match branches make."""
        assert match.box is not None  # the callers refine only a located match
        if overlap(scaled, match.box) >= _LOCATED_OVERLAP:
            return BoxChoice(box=scaled, source=BOX_SOURCE_REPORT)
        return BoxChoice(box=match.box, source=fallback_source)

    def _resolve(self) -> None:
        report_line, match, text = self._report_line, self._match, self._text
        width, height = self._width, self._height
        self._box_source: str = BOX_SOURCE_POSITIONAL  # the provenance of the chosen box
        report_box = report_line.box if report_line else None
        if not (report_box and (report_box[2] > report_box[0] or report_box[3] > report_box[1])):
            self._box = match.box if match else None
            if match and match.confirms():
                self._box_source = BOX_SOURCE_CONTENT
            self._orientation = self._resolve_orientation(self._box)
            return
        scaled = [
            report_box[0] / NORMALIZED_BOX_SCALE * width,
            report_box[1] / NORMALIZED_BOX_SCALE * height,
            report_box[2] / NORMALIZED_BOX_SCALE * width,
            report_box[3] / NORMALIZED_BOX_SCALE * height,
        ]
        assert report_line is not None
        report_orientation = int(report_line.degrees)
        if (
            match
            and match.box
            and match.box_source == BOX_SOURCE_CONTENT
            and (text_extent_violation(text, match.box, match.orientation) is None)
        ):
            # the match read REAL text at a plausible size — its box is
            # ink-grounded; the report box is the per-line refinement
            # when they agree (page-03: the marker boxes sat ~200px
            # above the real text — the disjoint match box wins)
            choice = self._report_refines(match, scaled, BOX_SOURCE_CONTENT)
            self._box, self._box_source = choice.box, choice.source
            self._orientation = self._resolve_orientation(self._box)
            return
            # a false content match (noise) — the report's location anchors
        if (
            match
            and match.box
            and match.box_source == BOX_SOURCE_POSITIONAL
            and (text_extent_violation(text, match.box, match.orientation) is None)
        ):
            # the order-based fallback's box is only the line's region
            # when the rec READ the line's text there — a squeezed or
            # unrelated detection must never displace a good report
            # box. The report refines when they agree; the rec's OWN
            # reading of the match's box decides the disjoint case.
            choice = self._report_refines(match, scaled, BOX_SOURCE_POSITIONAL)
            self._box, self._box_source = choice.box, choice.source
            if (
                self._box_source == BOX_SOURCE_POSITIONAL
                and jaccard(match.rec_word_set(), set(words(text))) < MATCH_THRESHOLD
            ):
                # the rec did NOT read the line's own text there — the
                # unrelated ink must not displace the report box
                self._box, self._box_source = scaled, BOX_SOURCE_REPORT
            self._orientation = self._resolve_orientation(self._box)
            return
            # the match's box cannot hold the text — the report's location anchors
        if text_extent_violation(text, scaled, report_orientation) is None:
            self._box = scaled
            self._box_source = BOX_SOURCE_REPORT
            self._orientation = self._resolve_orientation(scaled)
            return
        self._box = None  # no candidate holds the text — boxless, flagged
        self._box_source = BOX_SOURCE_REPORT
        self._orientation = self._resolve_orientation(None)

    def _resolve_orientation(self, box: list[float] | None) -> int:
        candidates: list[int] = []
        report_line, match = self._report_line, self._match
        if self._trust_report_degrees and report_line:
            candidates.append(int(report_line.degrees))
        if match:
            candidates.append(match.orientation)
        if not self._trust_report_degrees and report_line:
            candidates.append(int(report_line.degrees))
        candidates.append(0)
        for degrees in candidates:
            if aspect_consistent(degrees, box):
                return degrees
        return candidates[0]


def drop_inkless_boxes(lines: list[LayoutLine], image: Path) -> int:
    """Gate D: a line's box must contain the ink it claims. A
    well-proportioned box in a blank region is an ESTIMATE, not an
    anchor, and the pure gates cannot see it (in-bounds,
    aspect-consistent, text-synced). The layout stage checks the ink
    share (the same deterministic rule as the clip guard) and drops the
    box — the line stays flagged, the page stays reviewable. Returns the
    count dropped; a missing/unreadable image drops nothing."""
    if not lines:
        return 0
    try:
        with Image.open(image) as im:
            w, h = im.size
            dropped = 0
            for line in lines:
                box = line.box
                if not isinstance(box, list) or len(box) != 4:
                    continue
                x0, y0, x1, y1 = (int(v) for v in box)
                x0, y0 = max(0, x0), max(0, y0)
                x1, y1 = min(w, x1), min(h, y1)
                if x1 <= x0 or y1 <= y0:
                    continue
                gray = im.crop((x0, y0, x1, y1)).convert("L")
                if sum(gray.histogram()[:128]) < _CLIP_INK_MIN * gray.width * gray.height:
                    line.box = None
                    dropped += 1
            return dropped
    except OSError:
        return 0


def anchor_guess_lines(
    geometry: PageGeometry,
    guess_lines: list[str],
    report_lines: list[OrientationLine],
    matches: list[LineMatch],
    trust_report_degrees: bool = False,
) -> list[LayoutLine]:
    """The v3 anchored lines (2026-08-17): the guess's authoritative
    transcription, each line LOCATED by the report (box + degrees keyed
    by the line index). A line the report couldn't locate takes its rec
    match's box, or none — flagged. Only the CONTENT matches confirm
    (the rec read the same words); a partial report degrades only the
    geometry, never the text.

    The line's orientation: the report's LOCATED degrees when they are
    trustworthy (``trust_report_degrees`` — the clip-classified report,
    whose per-line angles are measured from the actual text), else the
    rec match's pass orientation — the pass that READ the text is the
    ground truth for the view rotation when the report's estimates are
    the flaky full-page call's (the 2026-08-17 90-vs-270 flip). A
    mirrored-pass artifact (page-03's horizontal lines content-matched
    during the 90° pass and labeled 90°) is exactly why the clip
    report's located degrees must win over the pass."""
    by_index = {report.index: report for report in report_lines}
    match_by_index = {match.vlm_index: match for match in matches}
    confirmed = {match.vlm_index for match in matches if match.confirms()}
    lines: list[LayoutLine] = []
    for i, line_text in enumerate(guess_lines):
        is_confirmed = i in confirmed
        anchor = Anchor(
            by_index.get(i),
            match_by_index.get(i),
            line_text,
            geometry.width,
            geometry.height,
            trust_report_degrees,
        )
        lines.append(
            LayoutLine(
                index=len(lines),
                text=line_text,
                box=anchor.box,
                conf=1.0 if is_confirmed else 0.0,
                orientation=anchor.orientation,
                box_source=BOX_SOURCE_REPORT if is_confirmed else BOX_SOURCE_REPORT_UNCONFIRMED,
                words=[
                    LayoutWord(word=w, box=None, conf=1.0 if is_confirmed else 0.0) for w in vlm_line_words(line_text)
                ],
            )
        )
    return lines


def recognize_extra(
    image: Path,
    box: list[float],
    orientation: int,
    recognize: Callable[[Path], str | None],
) -> str | None:
    """The clip→rotate→recognize flow for an extra (rec-only) line
    (2026-08-20, user's direction): clip the line's box from the ORIGINAL
    image, rotate the clip UPRIGHT by its orientation, and recognize the
    de-rotated text — the rec engine's rotated-frame reading is fragment
    garbage for cursive; the VLM reads the upright clip. Fail fast
    (returns None — the line is DROPPED, never garbage-admitted): the
    clip is out of bounds, recognition returns nothing (Gate C), or the
    recognized text is wildly out of sync with the box's reading-axis
    extent (Gate B's check, applied to the recognized reading)."""
    x0, y0, x1, y1 = box
    try:
        with Image.open(image) as im:
            w, h = im.size
            if x0 < 0 or y0 < 0 or x1 > w or y1 > h or x1 <= x0 or y1 <= y0:
                return None
            # rotate(-degrees) makes `degrees`-oriented text upright —
            # the same transform the orientation pass applies to the page
            clip = im.crop((x0, y0, x1, y1)).rotate(-orientation, expand=True)
    except OSError:
        return None
    # deterministic ink guard: a blank clip has no text to recognize —
    # the model would spiral on it; fail fast BEFORE the call, the line
    # is dropped
    gray = clip.convert("L")
    if sum(gray.histogram()[:128]) < _CLIP_INK_MIN * clip.width * clip.height:
        return None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            clip.save(tmp, format="JPEG", quality=85)
            tmp_path = Path(tmp.name)
        try:
            text = recognize(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
    except OSError:
        return None
    text = (text or "").strip()
    if not text:
        return None
    if text_extent_violation(text, [x0, y0, x1, y1], float(orientation)):
        return None
    return text


def _extra_lines(
    unmatched: list[Detection],
    seam: ClipSeam | None = None,
) -> list[LayoutLine]:
    """The rec detections no text line claimed — the model-missed text —
    flagged extras at their pass orientation. With the clip seam
    (``image`` + ``recognize``) each extra is re-read from its OWN upright
    clip (recognize_extra): a successful reading replaces the rec
    fragment; a failed one DROPS the line — the rec's rotated-frame
    fragment garbage never reaches the review (2026-08-20)."""
    lines: list[LayoutLine] = []
    for det in unmatched:
        pass_orientation = det.get("orientation")
        pass_orientation = pass_orientation if isinstance(pass_orientation, int) else 0
        # the extra's orientation must be geometry-validated like the
        # anchored lines': a wide box is horizontal text even when the
        # rec read it during a vertical pass (2026-08-20: page-03's
        # merged wide boxes carried the 90° pass's label)
        orientation = pass_orientation if aspect_consistent(pass_orientation, det["box"]) else 0
        text = det["text"]
        if seam is not None:
            recognized = recognize_extra(seam.image, det["box"], orientation, seam.recognize)
            if recognized is None:
                continue  # fail fast — the fragment is not admitted
            text = recognized
        lines.append(
            LayoutLine(
                index=0,  # provisional — re-indexed after the dedupe + sort
                text=text,
                box=det["box"],
                conf=0.0,
                orientation=orientation,
                box_source=BOX_SOURCE_MULTI,
                words=_multi_line_words(text, det.get("words", []), 0.0),
            )
        )
    return lines


def _order_layout_lines(lines: list[LayoutLine]) -> list[LayoutLine]:
    """The layout's reading order (user's requirement): a page whose
    lines resolve to ONE orientation reads in the TRANSCRIPTION order —
    the model read the page block-by-block, so the margin blocks never
    interleave. A genuinely multi-orientation page reads by the
    block-aware order: each physical block (lines sharing ink) reads
    WHOLE, the blocks top-to-bottom — the postcard's 0° top and 90°
    message never bounce per line, and the rotation changes once per
    block. The order itself is the standalone reading tool's."""
    if len({line.orientation or 0 for line in lines}) > 1:
        return order_lines(lines)
    return lines


@dataclass(frozen=True)
class MultiInputs:
    """A multi-orientation layout's inputs — the page identity, geometry,
    the orientation passes, the report evidence, the guess text, the clip
    seam, the trust flag. One object the assembly reads whole (the record
    the 9-parameter tail was)."""

    geometry: PageGeometry
    passes: list[DetectionPass]
    report_lines: list[OrientationLine] | None = None
    vlm_text: str | None = None
    clip: ClipSeam | None = None
    trust_report_degrees: bool = False


class MultiAssembly:
    """The multi-orientation layout's assembly (PRD VR15): the threaded
    state — the content matches, the unmatched detections, the lines —
    and the chain that carries it (association, anchoring, extras,
    dedupe, ordering) as methods, so no step re-receives what the last
    one produced."""

    def __init__(self, inputs: MultiInputs) -> None:
        self._inputs = inputs
        self.matches: list[LineMatch] = []
        self.unmatched: list[Detection] = []
        self.lines: list[LayoutLine] = []

    def _detections(self) -> list[Detection]:
        """The passes' admitted lines, each stamped with its pass's orientation."""
        return cast(
            "list[Detection]",
            [{**entry, "orientation": p.degrees} for p in self._inputs.passes for entry in p.lines],
        )

    def _associate(self, texts: list[str]) -> None:
        association = associate_lines(texts, self._detections())
        self.matches, self.unmatched = association.matches, association.unmatched

    def _anchor(self) -> None:
        """The report-anchored lines: the guess's authoritative
        transcription located at its report box (v3, 2026-08-17), or the
        report's own transcription when no guess text was given (v2)."""
        report_lines = self._inputs.report_lines or []
        if self._inputs.vlm_text:
            guess_lines = [ln for ln in self._inputs.vlm_text.split("\n") if ln.strip()]
            self._associate(guess_lines)
            self.lines = anchor_guess_lines(
                self._inputs.geometry,
                guess_lines,
                report_lines,
                self.matches,
                trust_report_degrees=self._inputs.trust_report_degrees,
            )
        else:
            report_texts = [str(report.text or "") for report in report_lines]
            self._associate(report_texts)
            confirmed = {match.vlm_index for match in self.matches if match.confirms()}
            self.lines = _anchored_lines(self._inputs.geometry, report_lines, confirmed)

    def _add_extras(self) -> None:
        """The rec detections no text line claimed — the model-missed
        text — re-read from their own upright clips when the seam is
        given (a failed reading drops the line)."""
        self.lines += _extra_lines(self.unmatched, self._inputs.clip)

    def _rec_fallback(self) -> list[LayoutLine]:
        """Without the report: the rec-based pass lines are the layout
        (the v1 fallback)."""
        return [
            LayoutLine(
                index=0,  # provisional — re-indexed after the dedupe + sort
                text=entry["text"],
                box=entry["box"],
                conf=entry["score"],
                orientation=p.degrees if aspect_consistent(p.degrees, entry["box"]) else 0,
                box_source=BOX_SOURCE_MULTI,
                words=_multi_line_words(entry["text"], entry.get("words", []), entry["score"]),
            )
            for p in sorted(self._inputs.passes, key=lambda p: p.degrees)
            for entry in p.lines
        ]

    def build(self) -> list[LayoutLine]:
        """Assemble the combined lines: the report-anchored lines plus
        their extras, or the rec-based fallback when no report was given.
        The caller applies the dedupe, ordering and re-indexing to the
        returned lines."""
        if self._inputs.report_lines:
            self._anchor()
            self._add_extras()
        else:
            self.lines = self._rec_fallback()
        return self.lines


# the combined layout's heterogeneous inputs — the page identity, geometry, the passes, the report, the text
def multi_layout(
    page: str,
    width: int,
    height: int,
    passes: list[DetectionPass],
    report_lines: list[OrientationLine] | None = None,
    vlm_text: str | None = None,
    image: Path | None = None,
    recognize: Callable[[Path], str | None] | None = None,
    trust_report_degrees: bool = False,
) -> Layout:
    """The combined multi-orientation layout (PRD VR15).

    With the report's per-line geometry (``report_lines`` — box in the
    normalized 0-1000 frame + degrees, keyed by the line index) AND the
    page's known transcription (``vlm_text`` — the guess's corrected
    reading), the lines ARE that authoritative text, each located at its
    box — the box holds the words it claims (VR14). A rec detection
    agreeing on content marks the line confident; the rec lines no text
    line claims stay as flagged extras. Without the report, the
    rec-based pass lines are the layout (the v1 fallback).

    The lines order 0° first then each next direction; within a group the
    text order, then the extras by reading position; the same physical
    region keeps only its best reading (dedupe_regions)."""
    clip = ClipSeam(image, recognize) if image is not None and recognize is not None else None
    inputs = MultiInputs(PageGeometry(page, width, height), passes, report_lines, vlm_text, clip, trust_report_degrees)
    lines = MultiAssembly(inputs).build()
    lines = dedupe_regions(lines)
    # The reading order (2026-08-20, user's requirement): a page whose
    # lines resolve to ONE orientation reads in the TRANSCRIPTION order —
    # the model read the page block-by-block, so the margin blocks never
    # interleave (page-03: a single-orientation letter took the multi
    # path on the report's garbage degrees; the aspect rule resolved
    # every line to 0). A genuinely multi-orientation page reads by the
    # physical reading-start sort in the dominant frame (the postcard:
    # the transcription order scrambled the multi reading).
    lines = _order_layout_lines(lines)
    for i, line in enumerate(lines):
        line.index = i
    return Layout(page=page, width=width, height=height, lines=lines, unmatched=[])


def load_orientation_hint(path: Path) -> list[int]:
    """The page's distinct text orientations (0/90/180/270), written by
    the pipeline stage when the arbiter's scores suggested more than one
    direction (PRD VR15). [] = a single orientation — the plain
    single-orientation layout path applies. The sidecar is the report
    record — the v3 lines carry their own degrees, so the hints and the
    lines' degrees both feed the pass set."""
    report = load_orientation_report(path)
    degrees = {hint.degrees for hint in report.hints}
    degrees |= {line.degrees for line in report.lines if line.degrees in READING_DEGREES}
    return sorted(degrees) if len(degrees) >= 2 else []


def load_orientation_report(path: Path) -> OrientationReport:
    """The orientation report sidecar (the v2 shape): the region hints +
    the model's own per-line transcription with boxes and degrees. An
    empty report when absent or unreadable — the plain layout path."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return OrientationReport()
    if not isinstance(data, dict):
        return OrientationReport()
    return OrientationReport.from_dict(data)


def orientation_passes(degrees: list[int]) -> list[int]:
    """The detection passes for a page's reported orientations. A
    reported vertical direction (90 or 270) runs BOTH its mirrors: the
    vision model flips between 90 and 270 for the same physical block
    between calls, and a pass at the wrong direction leaves
    the block upside-down — the recognition admission then rejects it
    and the text is silently missed. The mirror pass costs one detection
    run (no model call) and admits nothing garbage."""
    out = {d for d in degrees}
    out.update({270 if d == 90 else 90 for d in degrees if d in (90, 270)})
    return sorted(out)


def rotate_detections(detections: list[Detection], quarters: int, w: int, h: int) -> list[Detection]:
    """The detection boxes rotated clockwise by 90° ``quarters`` (1, 2 or 3)
    in a w×h image — a rigid remap, exact for a rotation; the reviewer's
    orientation fix re-anchors the boxes without re-OCR. For an
    odd number of quarters the image dims swap. The text's orientation
    turns with the page — the reading direction rotates the same quarters
    CW — because the extent/aspect gates judge the box against it (a
    dropped orientation reads a tall box as horizontal and refuses the
    write)."""
    q = quarters % QUARTERS_PER_FULL_TURN
    if q == 0:
        return list(detections)
    rotated: list[Detection] = []
    for det in detections:
        x0, y0, x1, y1 = det["box"]
        if q == 1:  # 90° CW: (x, y) -> (h - y, x)
            box = [h - y1, x0, h - y0, x1]
        elif q == 2:  # 180°: (x, y) -> (w - x, h - y)
            box = [w - x1, h - y1, w - x0, h - y0]
        else:  # 270° CW: (x, y) -> (y, w - x)
            box = [y0, w - x1, y1, w - x0]
        rotated.append(
            Detection(
                box=box,
                text=det["text"],
                score=det["score"],
                words=det.get("words", []),
                orientation=(det.get("orientation", 0) + (360 // QUARTERS_PER_FULL_TURN) * q) % 360,
            )
        )
    return rotated
