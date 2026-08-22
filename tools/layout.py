"""The layout model — how a page's review layout is built (TECH-SPEC
§16.16, 2026-08-15).

The VLM transcribes the words; PaddleOCR's detector supplies the geometry;
this module is the deterministic half: the content-based line association
(the engines read pages in different orders), the anchor resolution (which
box and orientation a line takes when the sources disagree — ``Anchor``),
the per-word flags, the reading order (``tools.reading``), and the
fail-fast gates (``tools.gates`` — a layout that fails them is never
written or served). It never imports PaddleOCR — the detection stage runs
under the .venv-htr interpreter (tools/layout_detect.py) and hands its raw
output to ``Layout.single`` / ``Layout.multi``.

The layout JSON per page (written beside ocr-guess, atomic):
    {"page", "width", "height",
     "lines": [{index, text, box, conf, box_source, words: [{word, box, conf}]}],
     "unmatched": [{box, text, conf: 0.0}]}

``box_source`` says how the anchor was found: "vlm" (the transcription
model's OWN per-line box — it read the page, so its box is text-anchored
and reading-consistent; the rec engine cannot read cursive and merges or
misses its lines, 2026-08-16), "content" (the detector's rec text matched
the line) or "positional" (the fallback filled the line with the next
unmatched detection in reading order — the geometry is real, the text
anchor is not; the surface renders these dashed). ``unmatched`` carries
the detector's lines that matched no VLM line and were not positionally
assigned (their geometry is real; a confident text anchor is not — conf 0).
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict, cast

from PIL import Image

from tools.atomic import atomic_write
from tools.box import aspect_consistent, overlap
from tools.gates import text_extent_violation, validate_layout
from tools.reading import order_lines
from tools.store import DiskStore  # noqa: F401
from tools.text import is_struck, jaccard, normalize, vlm_line_words, words


# A PaddleOCR recognition line + its box (the detection stage's output).
# box is [x0, y0, x1, y1] in the original oriented image's pixels.
class Detection(TypedDict):
    box: list[float]
    text: str
    score: float
    words: list[dict[str, Any]]


# The minimum word-set overlap (Jaccard) for a detector line to claim a VLM
# line. The rec text is noisy on cursive — that noise IS the confidence
# signal — so the matcher tolerates it: one word in common is not a match.
MATCH_THRESHOLD = 0.34

BOX_COORDINATE_COUNT = 4  # a box is [x0, y0, x1, y1]

# The VLM's box coordinate system: normalized 0-1000 (fractions of the
# image's width/height, times 1000), rescaled to pixels when anchored.
NORMALIZED_BOX_SCALE = 1000

# Float tolerance for division-underflow protection.
_MIN_AREA_EPSILON = 1e-9
QUARTERS_PER_FULL_TURN = 4  # a full rotation is four quarter-turns (90° each)

# The multi-orientation admission (PRD VR15, 2026-08-16 prototype): a
# detected line is admitted only when the recognizer read REAL text at
# that orientation — confidence + plausibility — never on box shape
# alone, so an accidental upside-down pass's boxes are rejected.
REC_SCORE_GATE = 0.85  # recognition confidence: real words read at the right orientation
MIN_LETTERS = 2  # plausibility: a "real word" has letters, not just shapes
_DEDUPE_OVERLAP = 0.3  # two passes' lines sharing this much of the smaller box are the same physical region
_LOCATED_OVERLAP = 0.5  # the report box must claim at least half of the matched detection's ink to anchor it
_CLIP_INK_MIN = 0.001  # a line clip must carry >= 0.1% dark pixels — a blank clip has nothing to recognize
# A multi line the rec read below this is doubtful — its words flag (conf
# 0.0), the review's red doubt + the mark-fine button (VR4, 2026-08-17:
# the multi path had no self-report, so the rec score is the doubt signal).
WORD_FLAG_THRESHOLD = 0.95


def _det_y(det: Detection) -> float:
    """The detection's top — the sort key for reading order (module-level:
    captures nothing, so it is not a closure)."""
    return det["box"][1]


def _by_top(d: Detection) -> float:
    """Sort key: the box's top — module-level (captures nothing)."""
    return d["box"][1]


def _by_vlm_index(m: dict[str, Any]) -> int:
    """Sort key: the VLM line index — module-level (captures nothing)."""
    return m["vlm_index"]


def _positional_box_plausible(text: str, box: list[float]) -> bool:
    """The positional fallback's guard (2026-08-20): an unmatched
    detection's box is only a plausible anchor for a boxless line when
    the line's text length roughly matches the box's extent — the gate's
    own rule (Gate B) applied at assignment. A single glyph in a 552px
    box ('③', page-05) is the wrong region; assigning it refused the
    whole page at the write gate."""
    if not text.strip():
        return False
    box_w = box[2] - box[0]
    box_h = box[3] - box[1]
    if box_w <= 0 or box_h <= 0:
        return False
    return text_extent_violation(text, box, 0.0) is None


def associate_lines(vlm_lines: list[str], detections: list[Detection]) -> tuple[list[dict[str, Any]], list[Detection]]:
    """Match detector lines to VLM transcription lines by content.

    Reading orders differ (the engines disagree on where a marginal note
    sits), so the match is best normalized word-set overlap above
    MATCH_THRESHOLD, ties broken by reading order (y-first). Each VLM line
    claims at most one detector line and vice versa. Returns (matches,
    unmatched_detections), where matches are in VLM line order:
        {"vlm": str, "vlm_index": int, "box": [x0,y0,x1,y1],
         "rec_text": str, "rec_score": float,
    """
    vlm_sets = [set(words(line)) for line in vlm_lines]
    used_vlm: set[int] = set()
    used_det: set[int] = set()
    matches: list[dict[str, Any]] = []

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
            matches.append(
                {
                    "vlm": vlm_lines[vi],
                    "vlm_index": vi,
                    "box": detections[di]["box"],
                    "rec_text": detections[di]["text"],
                    "rec_score": detections[di]["score"],
                    "rec_words": words(detections[di]["text"]),
                    "det_words": detections[di].get("words", []),
                    "box_source": "content",
                    "orientation": detections[di].get("orientation", 0),
                }
            )
    matches.sort(key=_by_vlm_index)
    unmatched = [d for i, d in enumerate(detections) if i not in used_det]
    # Positional fallback (2026-08-16: the audit found 101 of 323 lines
    # boxless — the rec model cannot read cursive, so whole pages never
    # content-match). The boxless VLM lines take the unmatched detections in
    # reading order: both lists run top-to-bottom, so the k-th boxless line
    # takes the k-th unmatched detection's geometry. The anchor is
    # positional, not textual (the rec text never matched) — the caller
    # marks it, and the surface renders positional boxes dashed.
    boxless = [vi for vi in range(len(vlm_lines)) if vi not in used_vlm]
    unmatched.sort(key=_by_top)
    matches.extend(
        {
            "vlm": vlm_lines[vi],
            "vlm_index": vi,
            # The positional guard (2026-08-20): the detection's box
            # anchors the boxless line ONLY when it plausibly holds the
            # line's text — page-05's '③' (one glyph) was paired with a
            # 552px detection box, which refused the whole page at the
            # write gate. An absurd box is dropped (the line stays
            # boxless, flagged), never assigned.
            "box": det["box"] if _positional_box_plausible(vlm_lines[vi], det["box"]) else None,
            "rec_text": det["text"],
            "rec_score": det["score"],
            "rec_words": words(det["text"]),
            "det_words": det.get("words", []),
            "box_source": "positional",
            "orientation": det.get("orientation", 0),
        }
        for vi, det in zip(boxless, unmatched, strict=False)
    )
    matches.sort(key=_by_vlm_index)
    return matches, unmatched[len(boxless) :]


def drop_conflicting_boxes(lines: list[dict[str, Any]]) -> int:
    """Gate E as a correction (2026-08-22): when two lines claim the same
    region with DIFFERENT text, the lower-confidence line's box is an
    estimate that shadows the confirmed anchor — page-03's boxless
    "critic's view. To quote:" box sat on the P.S. margin, refusing the
    whole page at the serve gate. The lower-conf box drops (the line
    stays flagged); the confirmed anchor keeps its region. The same text
    in one region is the dedupe's job, never dropped here. Returns the
    count dropped."""
    boxed = [ln for ln in lines if ln.get("box")]
    dropped = 0
    for i, a in enumerate(boxed):
        for b in boxed[i + 1 :]:
            if not a.get("box") or not b.get("box"):
                continue
            if overlap(a["box"], b["box"]) >= 0.5 and normalize(a.get("text", "")) != normalize(b.get("text", "")):
                if float(a.get("conf", 0.0)) < float(b.get("conf", 0.0)):
                    a["box"] = None
                else:
                    b["box"] = None
                dropped += 1
    return dropped


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
    """The per-word flag source (user, 2026-08-15). With a self-report the
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
) -> list[dict[str, Any]]:
    """The per-word layout entries for one line — the flag source applies
    per word (self-report / cross-reader fallback / struck)."""
    out = []
    for w in vw:
        conf = _word_flag(
            w,
            selfreport_line=selfreport_line,
            rec_words=rec_words,
            use_selfreport=use_selfreport,
        )
        out.append({"word": w, "box": None, "conf": conf})
    return out


class Layout:
    """A page's review layout — the lines with their boxes, orientations
    and confidence. Built from the transcription and the geometry sources
    (``Layout.single`` for one-orientation pages, ``Layout.multi`` for the
    combined passes), validated by the gates, ordered for the review pane,
    and written through the store. The dict form (``to_dict``) is the
    JSON the review surface reads."""

    def __init__(
        self,
        page: str,
        width: int,
        height: int,
        lines: list[dict[str, Any]],
        unmatched: list[dict[str, Any]],
    ) -> None:
        self.page = page
        self.width = width
        self.height = height
        self.lines = lines
        self.unmatched = unmatched

    # the single-path build's inputs mirror build_layout's — a parameter object would obscure the pure pass
    # lucidlint: ignore long-param-list a parameter object would obscure the pure pass
    @classmethod
    def single(
        cls,
        page: str,
        width: int,
        height: int,
        vlm_text: str,
        detections: list[Detection],
        selfreport: list[dict[str, Any]] | None = None,
        vlm_boxes: dict[int, list[float]] | None = None,
    ) -> Layout:
        """The single-orientation layout: the guess text anchored at the
        transcription's own boxes, the rec association filling the rest."""
        return cls(
            **build_layout(page, width, height, vlm_text, detections, selfreport=selfreport, vlm_boxes=vlm_boxes)
        )

    # the multi-path build's inputs mirror multi_layout's — a parameter object would obscure the combined pass
    # lucidlint: ignore long-param-list a parameter object would obscure the combined pass
    @classmethod
    def multi(
        cls,
        page: str,
        width: int,
        height: int,
        passes: list[tuple[int, list[dict[str, Any]]]],
        report_lines: list[dict[str, Any]] | None = None,
        vlm_text: str | None = None,
        image: Path | None = None,
        recognize: Callable[[Path], str | None] | None = None,
        trust_report_degrees: bool = False,
    ) -> Layout:
        """The multi-orientation layout: a detection pass at each reported
        orientation, the guess text anchored at the report's per-line
        boxes, the extras re-read from their own upright clips."""
        return cls(
            **multi_layout(
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
        )

    def validate(self, tolerance: float = 4.0) -> list[str]:
        """The gates' findings — [] = the layout is fit to write and
        serve."""
        return validate_layout(self.to_dict(), tolerance)

    def in_reading_order(self) -> Layout:
        """The block-aware reading order for the review pane — each
        physical block reads whole, the blocks top-to-bottom."""
        self.lines = order_lines(self.lines)
        return self

    def drop_inkless(self, image: Path) -> int:
        """Gate D: the boxes whose region holds no ink are estimates, not
        anchors — dropped (the lines stay flagged). Returns the count."""
        return drop_inkless_boxes(self.lines, image)

    def drop_conflicts(self) -> int:
        """Gate E as a correction: when two lines claim the same region
        with different text, the lower-confidence box is an estimate that
        shadows the confirmed anchor — dropped (the line stays flagged).
        Returns the count."""
        return drop_conflicting_boxes(self.lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "width": self.width,
            "height": self.height,
            "lines": self.lines,
            "unmatched": self.unmatched,
        }


# detections, self-report, VLM boxes — each consumed once by the pure pass; no second function shares the group
# lucidlint: ignore long-param-list the layout pass's heterogeneous inputs — page identity, geometry, transcription,
def build_layout(
    page: str,
    width: int,
    height: int,
    vlm_text: str,
    detections: list[Detection],
    selfreport: list[dict[str, Any]] | None = None,
    vlm_boxes: dict[int, list[float]] | None = None,
) -> dict[str, Any]:
    """The per-page layout the review surface reads.

    Anchors each VLM transcription line to its box — the VLM's OWN
    per-line boxes when the transcription carried geometry (``vlm_boxes``,
    normalized 0-1000 — the model that READ the page anchors each line it
    transcribed; the rec engine cannot read cursive and merges/misses its
    lines, 2026-08-16), else the detector's box (when one was found) —
    and computes the per-word confidence — the transcription model's own
    self-report (line + word), falling back to cross-reader agreement
    when no self-report has run; the unmatched detector lines ride along
    with conf 0. Coordinates are trusted as the original image's pixels —
    the detection stage asserts that before handing them over (a future
    engine change must fail loudly, not silently misalign).
    """
    vlm_lines = [line for line in vlm_text.split("\n") if line.strip()]
    matches, unmatched = associate_lines(vlm_lines, detections)
    by_index = {m["vlm_index"]: m for m in matches}
    # the self-report cites 1-based line numbers; the layout lines are 0-based
    report_by_line = _selfreport_by_line(selfreport, len(vlm_lines))
    use_selfreport = selfreport is not None
    lines: list[dict[str, Any]] = []
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
                {"box": vlm_boxes[vi], "degrees": 0},
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
            line_conf = (sum(w["conf"] for w in words_out) / len(words_out)) if words_out else 0.0
            lines.append(
                {
                    "index": vi,
                    "text": line,
                    "box": anchor.box,
                    "conf": line_conf,
                    "words": words_out,
                    "box_source": "vlm" if anchor.box_source == "report" else anchor.box_source,
                }
            )
            continue
        match = by_index.get(vi)
        if match is None:
            lines.append(
                {
                    "index": vi,
                    "text": line,
                    "box": None,
                    "conf": 0.0,
                    "words": _words_out(
                        vw,
                        selfreport_line=report_by_line.get(vi),
                        rec_words=[],
                        use_selfreport=use_selfreport,
                    ),
                }
            )
            continue
        words_out = _words_out(
            vw,
            selfreport_line=report_by_line.get(vi),
            rec_words=match["rec_words"],
            use_selfreport=use_selfreport,
        )
        line_conf = (sum(w["conf"] for w in words_out) / len(words_out)) if words_out else 0.0
        lines.append(
            {
                "index": vi,
                "text": line,
                "box": match["box"],
                "conf": line_conf,
                "rec_text": match["rec_text"],
                "rec_score": match["rec_score"],
                "words": words_out,
                "det_words": match["det_words"],
                "box_source": match["box_source"],
            }
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
    return {
        "page": page,
        "width": width,
        "height": height,
        "lines": lines,
        "unmatched": [{"box": d["box"], "text": d["text"], "conf": 0.0} for d in unmatched],
    }


def _selfreport_by_line(selfreport: list[dict[str, Any]] | None, n_lines: int) -> dict[int, set[str]]:
    """The self-report words keyed by 0-based line index — the report
    cites 1-based line numbers; the layout lines are 0-based."""
    report_by_line: dict[int, set[str]] = {}
    if selfreport:
        for entry in selfreport:
            line_no = entry.get("line")
            if isinstance(line_no, int) and 1 <= line_no <= n_lines:
                report_by_line.setdefault(line_no - 1, set()).add(normalize(entry.get("word", "")))
    return report_by_line


def load_layout(path: Path) -> dict[str, Any]:
    """Read a page's layout JSON (the drafts payload reads these)."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_layout_store(store: Any, store_path: str) -> dict[str, Any]:
    """Read the latest version of a layout from a ``PipelineStore``."""
    return json.loads(store.read_latest(store_path))


def load_vlm_boxes(path: Path) -> dict[int, list[float]] | None:
    """The VLM's per-line boxes (normalized 0-1000) from a page's
    transcription sidecar (``page.vlm.json`` — written by
    tools/htr.htr_pages_vlm when the model returned geometry). Keyed by
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
        b = entry.get("box") if isinstance(entry, dict) else None
        if (
            isinstance(b, list)
            and len(b) == BOX_COORDINATE_COUNT
            and all(isinstance(v, (int, float)) and v == v for v in b)
        ):
            boxes[i] = [float(v) for v in b]
    return boxes or None


def is_admissible(text: str, score: float) -> bool:
    """Admit a detected line only when the recognizer read real text at
    this orientation (confidence + plausibility) — never on box shape
    alone (PRD VR15)."""
    return float(score) >= REC_SCORE_GATE and sum(1 for ch in text if ch.isalpha()) >= MIN_LETTERS


def remap_box(
    box: list[float],
    degrees: int,
    original: tuple[int, int],
    rotated: tuple[int, int],
) -> list[float]:
    """A box from the rotated frame (rotated = rw×rh) mapped back to the
    original image (original = ow×oh) — the exact inverse of the applied
    rotation. The forward index map of ``Image.rotate(-degrees,
    expand=True)``, verified empirically (2026-08-20 — the old matrix
    form mirrored the 90°/270° boxes: page-03's rebuilt layout put the
    letter's lines at the image top):
      degrees 90  (CW):  (x, y) -> (oh-1-y, x)
      degrees 180 (flip): (x, y) -> (ow-1-x, oh-1-y)
      degrees 270 (CCW):  (x, y) -> (y, ow-1-x)
    The inverse maps the rotated-frame corners back exactly."""
    ow, oh = original
    rw, rh = rotated
    del rw, rh  # the inverse needs only the original dims + the corner rule
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
    original: tuple[int, int],
    rotated: tuple[int, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Admit the detector's lines read as real text at this orientation
    (recognition-driven, never shape-only) and remap their boxes from the
    rotated frame back to the original image. Returns (kept, rejected)."""
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for det in detections:
        text = det["text"].strip()
        score = float(det["score"])
        entry: dict[str, Any] = {
            "text": text,
            "score": round(score, 2),
            "words": [{"box": remap_box(w["box"], degrees, original, rotated)} for w in det.get("words", [])],
        }
        if is_admissible(text, score):
            entry["box"] = remap_box(det["box"], degrees, original, rotated)
            kept.append(entry)
        else:
            entry["box"] = [round(v, 1) for v in det["box"]]
            rejected.append(entry)
    return kept, rejected


def _richness(line: dict[str, Any]) -> tuple[int, float]:
    """The reading's strength — more letters beat fewer; ties by score.
    The dedupe keeps the BEST reading of a physical region across the
    orientation passes (2026-08-17: the postcard's vertical strips were
    read at 0°, 90° AND 270° — 'MHOTH' (90°) vs 'HARBOTTLE, MORPETH'
    (270°) share a box at IoU 0.97; only the richer survives)."""
    return sum(1 for ch in line["text"] if ch.isalpha()), float(line["conf"])


def _drop_fragment_subsets(lines: list[dict[str, Any]], keep: list[bool]) -> None:
    """The fragment-subset rule (2026-08-17): a SHORT line (<=2 tokens)
    whose tokens are a strict subset of another line's is the same text
    read as a fragment — the mirror passes' rec reading a piece of an
    anchored line ('HOUSE,' next to 'HERNSPETH HOUSE,') — dropped even
    when its box landed elsewhere."""
    token_sets = [set(words(line["text"])) for line in lines]
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


def _weaker_duplicate(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Is ``a`` the weaker reading of ``b``'s physical region? Extracted
    from dedupe_regions (2026-08-20) when the boxless guard pushed its
    cyclomatic complexity to lucidlint's bar. A boxless line has no
    region to dedupe — never a duplicate."""
    if not a.get("box") or not b.get("box"):
        return False
    return overlap(a["box"], b["box"]) > _DEDUPE_OVERLAP and _richness(b) > _richness(a)


def dedupe_regions(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop the weaker readings of the same physical region across
    orientations. The anchored lines (the model's authoritative
    transcription) are never dropped — its estimated boxes can overlap
    between DISTINCT lines, so the box-overlap rule applies only to the
    rec extras (2026-08-17: the eval caught 'POST CARD.' being dropped
    when the model's 180° box overlapped a longer line's box). The
    fragment-subset rule (a short line whose tokens are a subset of
    another's) applies to all. The survivors keep their index — the
    caller re-indexes after."""
    keep = [True] * len(lines)
    anchored = {i for i, line in enumerate(lines) if line.get("box_source") in ("vlm", "vlm-unconfirmed")}
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


def _multi_line_words(text: str, boxes: list[dict[str, Any]], score: float) -> list[dict[str, Any]]:
    """The per-word entries for a multi-orientation line: the rec text's
    tokens (the display words — verbatim, vlm_line_words) paired with the
    detector's remapped word boxes (extra tokens get no box; extra boxes
    drop), and the flag convention — a line the rec read weakly flags ALL
    its words (conf 0.0: the review's red doubt + the mark-fine button).
    Before 2026-08-17 the words carried no text and never flagged — the
    review rendered blank lines with no check buttons (reproduced on the
    Caradog 1915 sample, 2026-08-17)."""
    tokens = vlm_line_words(text)
    out: list[dict[str, Any]] = []
    for i, token in enumerate(tokens):
        box = boxes[i].get("box") if i < len(boxes) else None
        out.append({"word": token, "box": box, "conf": 0.0 if score < WORD_FLAG_THRESHOLD else score})
    return out


def _anchored_lines(
    report_lines: list[dict[str, Any]],
    confirmed: set[int],
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    """The model-anchored lines of the multi layout (2026-08-17): the
    report's transcription lines at their own boxes — the box holds the
    words it claims (VR14). ``confirmed`` = the report line indices a rec
    detection content-matched; those read clean, the rest flag."""
    lines: list[dict[str, Any]] = []
    for i, report in enumerate(report_lines):
        text = str(report.get("text", "")).strip()
        if not text:
            continue
        b = report.get("box") or [0, 0, 0, 0]
        is_confirmed = i in confirmed
        lines.append(
            {
                "index": len(lines),
                "text": text,
                "box": [
                    b[0] / NORMALIZED_BOX_SCALE * width,
                    b[1] / NORMALIZED_BOX_SCALE * height,
                    b[2] / NORMALIZED_BOX_SCALE * width,
                    b[3] / NORMALIZED_BOX_SCALE * height,
                ],
                "conf": 1.0 if is_confirmed else 0.0,
                "orientation": int(report.get("degrees", 0)),
                "box_source": "vlm" if is_confirmed else "vlm-unconfirmed",
                "words": [{"word": w, "box": None, "conf": 1.0 if is_confirmed else 0.0} for w in vlm_line_words(text)],
            }
        )
    return lines


class Anchor:
    """A line's geometry resolution — the box and orientation it takes
    when the sources disagree (2026-08-20). The report's located box is
    the v3 anchor; a CONTENT match's ink-grounded box overrides it only
    when the report's estimate misses the text's proportions (a false
    content match — the rec's merged bands — never overrides). The
    orientation is the first aspect-consistent candidate: the report's
    measured degrees when trusted (the clip-classified report), else the
    pass that READ the text (the 90-vs-270 flip's ground truth), then
    the report's estimate, then 0."""

    # the geometry resolution's six inputs — the report line, the match, the text, the page geometry, the trust
    # flag; a parameter object would obscure the pure decision (the same why as multi_layout's)
    # lucidlint: ignore long-param-list a parameter object would obscure the pure decision
    def __init__(
        self,
        report_line: dict[str, Any] | None,
        match: dict[str, Any] | None,
        text: str,
        width: int,
        height: int,
        trust_report_degrees: bool = False,
    ) -> None:
        self._report_line = report_line
        self._match = match
        self._text = text
        self._width = width
        self._height = height
        self._trust_report_degrees = trust_report_degrees
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

    def _resolve(self) -> None:
        report_line, match, text = self._report_line, self._match, self._text
        width, height = self._width, self._height
        self._box_source: str = "positional"  # the provenance of the chosen box
        report_box = report_line.get("box") if report_line else None
        if not (report_box and (report_box[2] > report_box[0] or report_box[3] > report_box[1])):
            self._box = match["box"] if match else None
            if match and match.get("box_source") == "content":
                self._box_source = "content"
            self._orientation = self._resolve_orientation(self._box)
            return
        scaled = [
            report_box[0] / NORMALIZED_BOX_SCALE * width,
            report_box[1] / NORMALIZED_BOX_SCALE * height,
            report_box[2] / NORMALIZED_BOX_SCALE * width,
            report_box[3] / NORMALIZED_BOX_SCALE * height,
        ]
        assert report_line is not None
        report_orientation = int(report_line["degrees"]) if isinstance(report_line.get("degrees"), (int, float)) else 0
        if match and match.get("box_source") == "content":
            match_orientation = int(match["orientation"]) if isinstance(match.get("orientation"), int) else 0
            if text_extent_violation(text, match["box"], match_orientation) is None:
                # the match read REAL text at a plausible size — its box is
                # ink-grounded; the report box is the per-line refinement
                # when they agree (page-03: the marker boxes sat ~200px
                # above the real text — the disjoint match box wins)
                if overlap(scaled, match["box"]) >= _LOCATED_OVERLAP:
                    self._box = scaled
                    self._box_source = "report"
                else:
                    self._box = match["box"]
                    self._box_source = "content"
                self._orientation = self._resolve_orientation(self._box)
                return
            # a false content match (noise) — the report's location anchors
        if text_extent_violation(text, scaled, report_orientation) is None:
            self._box = scaled
            self._box_source = "report"
            self._orientation = self._resolve_orientation(scaled)
            return
        self._box = None  # no candidate holds the text — boxless, flagged
        self._box_source = "report"
        self._orientation = self._resolve_orientation(None)

    def _resolve_orientation(self, box: list[float] | None) -> int:
        candidates: list[int] = []
        report_line, match = self._report_line, self._match
        if self._trust_report_degrees and report_line and isinstance(report_line.get("degrees"), (int, float)):
            candidates.append(int(report_line["degrees"]))
        if match and isinstance(match.get("orientation"), int):
            candidates.append(int(match["orientation"]))
        if not self._trust_report_degrees and report_line and isinstance(report_line.get("degrees"), (int, float)):
            candidates.append(int(report_line["degrees"]))
        candidates.append(0)
        for degrees in candidates:
            if aspect_consistent(degrees, box):
                return degrees
        return candidates[0]


def drop_inkless_boxes(lines: list[dict[str, Any]], image: Path) -> int:
    """Gate D (2026-08-20): a line's box must contain the ink it claims.
    page-03's transcription boxes sat ~200px above the real text — a
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
                box = line.get("box")
                if not isinstance(box, list) or len(box) != 4:
                    continue
                x0, y0, x1, y1 = (int(v) for v in box)
                x0, y0 = max(0, x0), max(0, y0)
                x1, y1 = min(w, x1), min(h, y1)
                if x1 <= x0 or y1 <= y0:
                    continue
                gray = im.crop((x0, y0, x1, y1)).convert("L")
                if sum(gray.histogram()[:128]) < _CLIP_INK_MIN * gray.width * gray.height:
                    line["box"] = None
                    dropped += 1
            return dropped
    except OSError:
        return 0


# the anchored-lines assembly's six inputs — the page geometry, the report evidence, the trust flag — are one
# pure function's data; a parameter object would obscure it (the same why as multi_layout's suppression)
# lucidlint: ignore long-param-list a parameter object would obscure the pure function
def anchor_guess_lines(
    guess_lines: list[str],
    report_lines: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    width: int,
    height: int,
    trust_report_degrees: bool = False,
) -> list[dict[str, Any]]:
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
    by_index = {int(r["index"]): r for r in report_lines if isinstance(r.get("index"), int)}
    match_by_index = {m["vlm_index"]: m for m in matches}
    confirmed = {m["vlm_index"] for m in matches if m.get("box_source") == "content"}
    lines: list[dict[str, Any]] = []
    for i, line_text in enumerate(guess_lines):
        r = by_index.get(i)
        match = match_by_index.get(i)
        is_confirmed = i in confirmed
        anchor = Anchor(r, match, line_text, width, height, trust_report_degrees)
        located = anchor.box
        orientation = anchor.orientation
        lines.append(
            {
                "index": len(lines),
                "text": line_text,
                "box": located,
                "conf": 1.0 if is_confirmed else 0.0,
                "orientation": orientation,
                "box_source": "vlm" if is_confirmed else "vlm-unconfirmed",
                "words": [
                    {"word": w, "box": None, "conf": 1.0 if is_confirmed else 0.0} for w in vlm_line_words(line_text)
                ],
            }
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
    # deterministic ink guard (2026-08-20): a blank clip has no text to
    # recognize — the model would spiral on it (the 4000-token reasoning
    # tail); fail fast BEFORE the call, the line is dropped
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
    image: Path | None = None,
    recognize: Callable[[Path], str | None] | None = None,
) -> list[dict[str, Any]]:
    """The rec detections no text line claimed — the model-missed text —
    flagged extras at their pass orientation. With the clip seam
    (``image`` + ``recognize``) each extra is re-read from its OWN upright
    clip (recognize_extra): a successful reading replaces the rec
    fragment; a failed one DROPS the line — the rec's rotated-frame
    fragment garbage never reaches the review (2026-08-20)."""
    lines: list[dict[str, Any]] = []
    for det in unmatched:
        pass_orientation = det.get("orientation")
        pass_orientation = pass_orientation if isinstance(pass_orientation, int) else 0
        # the extra's orientation must be geometry-validated like the
        # anchored lines': a wide box is horizontal text even when the
        # rec read it during a vertical pass (2026-08-20: page-03's
        # merged wide boxes carried the 90° pass's label)
        orientation = pass_orientation if aspect_consistent(pass_orientation, det["box"]) else 0
        text = det["text"]
        if image is not None and recognize is not None:
            recognized = recognize_extra(image, det["box"], orientation, recognize)
            if recognized is None:
                continue  # fail fast — the fragment is not admitted
            text = recognized
        lines.append(
            {
                "index": 0,  # provisional — re-indexed after the dedupe + sort
                "text": text,
                "box": det["box"],
                "conf": 0.0,
                "orientation": orientation,
                "box_source": "multi",
                "words": _multi_line_words(text, det.get("words", []), 0.0),
            }
        )
    return lines


def _order_layout_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The layout's reading order (2026-08-20, user's requirement): a
    page whose lines resolve to ONE orientation reads in the
    TRANSCRIPTION order — the model read the page block-by-block, so
    margin blocks never interleave (page-03). A genuinely
    multi-orientation page reads by the block-aware order: each physical
    block (lines sharing ink) reads WHOLE, the blocks top-to-bottom —
    the postcard's 0° top and 90° message never bounce per line, and
    the rotation changes once per block."""
    if len({line.get("orientation", 0) for line in lines}) > 1:
        return order_lines(lines)
    return lines


# the combined layout's heterogeneous inputs — the page identity, geometry, the passes, the report, the text
# lucidlint: ignore long-param-list a parameter object would obscure the pure function
def multi_layout(
    page: str,
    width: int,
    height: int,
    passes: list[tuple[int, list[dict[str, Any]]]],
    report_lines: list[dict[str, Any]] | None = None,
    vlm_text: str | None = None,
    image: Path | None = None,
    recognize: Callable[[Path], str | None] | None = None,
    trust_report_degrees: bool = False,
) -> dict[str, Any]:
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
    if report_lines:
        detections = cast(
            "list[Detection]",
            [{**entry, "orientation": degrees} for degrees, admitted in passes for entry in admitted],
        )
        if vlm_text:
            # v3 (2026-08-17): the layout's text is the guess's
            # authoritative transcription; the report LOCATES each line
            guess_lines = [ln for ln in vlm_text.split("\n") if ln.strip()]
            matches, unmatched = associate_lines(guess_lines, detections)
            lines = anchor_guess_lines(
                guess_lines,
                report_lines,
                matches,
                width,
                height,
                trust_report_degrees=trust_report_degrees,
            )
        else:
            # v2: the report's own transcription (no known text was given)
            report_texts = [str(r.get("text", "")) for r in report_lines]
            matches, unmatched = associate_lines(report_texts, detections)
            confirmed = {m["vlm_index"] for m in matches if m.get("box_source") == "content"}
            lines = _anchored_lines(report_lines, confirmed, width, height)
        lines += _extra_lines(unmatched, image, recognize)
    else:
        lines = [
            {
                "index": 0,  # provisional — re-indexed after the dedupe + sort
                "text": entry["text"],
                "box": entry["box"],
                "conf": entry["score"],
                "orientation": degrees if aspect_consistent(degrees, entry["box"]) else 0,
                "box_source": "multi",
                "words": _multi_line_words(entry["text"], entry.get("words", []), entry["score"]),
            }
            for degrees, admitted in sorted(passes, key=lambda p: p[0])
            for entry in admitted
        ]
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
        line["index"] = i
    return {"page": page, "width": width, "height": height, "lines": lines, "unmatched": []}


def load_orientation_hint(path: Path) -> list[int]:
    """The page's distinct text orientations (0/90/180/270), written by
    the pipeline stage when the arbiter's scores suggested more than one
    direction (PRD VR15). [] = a single orientation — the plain
    single-orientation layout path applies. The sidecar is the report
    dict — the v3 lines carry their own degrees (2026-08-17), so the
    hints and the lines' degrees both feed the pass set."""
    report = load_orientation_report(path)
    degrees = {int(h.get("degrees")) for h in report.get("orientation_hint", [])}
    degrees |= {int(ln.get("degrees")) for ln in report.get("lines", []) if ln.get("degrees") in (0, 90, 180, 270)}
    return sorted(degrees) if len(degrees) >= 2 else []


def load_orientation_report(path: Path) -> dict[str, Any]:
    """The orientation report sidecar (the v2 shape, 2026-08-17): the
    region hints + the model's own per-line transcription with boxes and
    degrees. {} when absent or unreadable — the plain layout path."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    hints = [h for h in data.get("orientation_hint", []) if isinstance(h, dict)]
    lines = [ln for ln in data.get("lines", []) if isinstance(ln, dict)]
    return {"orientation_hint": hints, "lines": lines}


def orientation_passes(degrees: list[int]) -> list[int]:
    """The detection passes for a page's reported orientations. A
    reported vertical direction (90 or 270) runs BOTH its mirrors: the
    vision model flips between 90 and 270 for the same physical block
    between calls (2026-08-17), and a pass at the wrong direction leaves
    the block upside-down — the recognition admission then rejects it
    and the text is silently missed. The mirror pass costs one detection
    run (no model call) and admits nothing garbage."""
    out = {d for d in degrees}
    out.update({270 if d == 90 else 90 for d in degrees if d in (90, 270)})
    return sorted(out)


def layout_detections(layout: dict[str, Any]) -> list[Detection]:
    """Reconstruct the detection pass from a layout JSON — the reviewer's
    rotate fix re-anchors these (2026-08-16): the matched lines carry their
    detection (box + rec text + score + per-word data), the unmatched ride
    along with their geometry. The texts are rotation-invariant, so the
    reconstruction is exact for a rigid rotation."""
    detections: list[Detection] = []
    detections.extend(
        Detection(
            box=line["box"],
            # the VLM-anchored lines carry no rec text — their OWN
            # text is the content anchor, so the rotation's rebuild
            # re-associates them exactly (2026-08-16)
            text=line.get("rec_text") or line.get("text", ""),
            score=line.get("rec_score", 0.0),
            words=line.get("det_words") or [],
        )
        for line in layout.get("lines", [])
        if line.get("box")
    )
    detections.extend(
        Detection(box=u["box"], text=u.get("text", ""), score=0.0, words=[]) for u in layout.get("unmatched", [])
    )
    return detections


def rotate_detections(detections: list[Detection], quarters: int, w: int, h: int) -> list[Detection]:
    """The detection boxes rotated clockwise by 90° ``quarters`` (1, 2 or 3)
    in a w×h image — a rigid remap, exact for a rotation (2026-08-16: the
    reviewer's orientation fix re-anchors the boxes without re-OCR). For an
    odd number of quarters the image dims swap."""
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
        rotated.append(Detection(box=box, text=det["text"], score=det["score"], words=det.get("words", [])))
    return rotated


def write_layout(layout: dict[str, Any], path: Path) -> None:
    """Publish a page's layout atomically — a reader must never meet a
    half-written layout (house rule: files other code reads are
    write-then-rename). Fail-fast (2026-08-17): a layout with a
    degenerate or out-of-image box is REFUSED — a bad layout must never
    be persisted, let alone served."""
    violations = validate_layout(layout)
    if violations:
        raise ValueError(f"refusing to write an invalid layout: {violations}")
    atomic_write(path, json.dumps(layout, indent=1, ensure_ascii=False) + "\n")


def write_layout_store(
    layout: dict[str, Any],
    store: Any,
    store_path: str,
) -> None:
    """Versioned layout write via the ``PipelineStore`` — a re-run creates
    a new version instead of overwriting (2026-08-18: the page-02 incident
    was a direct atomic_write to a fixed path, which lost the previous
    good layout)."""
    violations = validate_layout(layout)
    if violations:
        raise ValueError(f"refusing to write an invalid layout: {violations}")
    store.write(store_path, json.dumps(layout, indent=1, ensure_ascii=False) + "\n")
