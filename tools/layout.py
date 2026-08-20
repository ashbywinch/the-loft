"""The layout pass's pure logic (TECH-SPEC §16.16, 2026-08-15).

The VLM transcribes the words; PaddleOCR's detector supplies the geometry.
This module is the deterministic half: the content-based line association
(the engines read pages in different orders) and the per-word flag source
— the transcription model's OWN self-report of doubtful words (tools/vlm.py
``selfreport_words``) plus the ~~struck~~ markers, falling back to
cross-reader agreement when no self-report has run. It never imports
PaddleOCR — the detection stage runs under the .venv-htr interpreter
(tools/layout_detect.py) and hands its raw output to ``build_layout``.

The layout JSON per page (written beside ocr-guess, atomic):
    {"page", "width", "height",
     "lines": [{index, text, box, conf, box_source, words: [{word, box, conf}]}],
     "unmatched": [{box, text, conf: 0.0}]}

``lines`` follows the VLM transcription's line order — the review surface
renders the VLM text and anchors each line's box to the page geometry.
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
import re
import tempfile
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict, cast

from PIL import Image

from tools.atomic import atomic_write
from tools.store import DiskStore  # noqa: F401


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

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")
# Apostrophes are REMOVED, not spaced — the rec model drops them
# ("t'écrivons" reads as "tecrivons") so they must not split the token.
# Periods stay spaced so the P.S.I / P.S. I split artifact normalizes equal.
_APOS = re.compile(r"['’]")


def normalize(text: str) -> str:
    """The comparison form: case-folded, diacritics stripped, punctuation
    dropped.

    Diacritics are stripped because the rec model loses them ("Chère"
    reads as "Chere") — the comparison must not flag every accented word
    for that. The rec model's letter CONFUSIONS are the signal: "Aloxandra"
    vs "Alexandra" differ in the letters themselves and must flag.
    Punctuation is dropped so "P.S.]" and "P.S.I" normalize to the same
    token where the split artifact is the only difference.
    """
    folded = unicodedata.normalize("NFD", text).casefold()
    folded = "".join(c for c in folded if unicodedata.category(c) != "Mn")
    folded = unicodedata.normalize("NFC", folded)
    folded = _APOS.sub("", folded)
    return _WS.sub(" ", _PUNCT.sub(" ", folded)).strip()


def words(text: str) -> list[str]:
    """The comparison tokens of a text (normalized, non-empty)."""
    return [w for w in normalize(text).split(" ") if w]


def _overlap(a: set[str], b: set[str]) -> float:
    """Jaccard similarity — 0 when disjoint, 1 when identical."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


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
    return _text_extent_violation(text, box_w, box_h, 0.0) is None


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
            score = _overlap(det_set, vlm_sets[vi])
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


def vlm_line_words(line: str) -> list[str]:
    """The VLM line's display words — whitespace tokens, unnormalized (the
    verbatim discipline: the review shows exactly what the model wrote)."""
    return [w for w in line.split(" ") if w]


def is_struck(word: str) -> bool:
    """The VLM marks crossed-out words with ~~ — they always flag: struck
    text is content the reviewer must handle, whatever the confidence
    signal (walk finding 5, 2026-08-15)."""
    return "~~" in word


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


def reading_start(box: list[float], orientation: float) -> tuple[float, float]:
    """The corner where the line's FIRST character sits, in image pixels —
    the reading start used for the physical reading-order sort. The
    QUADRANT of the exact orientation picks the corner (the clip
    classifier returns exact angles like 88.4 — not rounded to 90 for the
    sort); the line's stored ``orientation`` stays exact.
    0/90 → top-left (a 90° line reads top-to-bottom, so its first char is
    the top of the tall box); 180 → bottom-right (upside-down text starts
    at the visual bottom-right); 270 → bottom-left (text reads
    bottom-to-top)."""
    o = orientation % 360
    x0, y0, x1, y1 = box
    if 135 <= o < 225:
        return (x1, y1)
    if 225 <= o < 315:
        return (x0, y1)
    return (x0, y0)


def order_lines_by_reading(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Physical reading order for the review pane: a STABLE top-to-bottom,
    left-to-right sort by each line's reading-start corner. The model's
    transcription order scrambles multi-orientation pages (2026-08-20:
    page-03's guess interleaved the P.S. box with the body). Each line's
    ``index`` is PRESERVED — the review surface keys edits and selections
    by it; only the display order changes. Boxless or degenerate lines
    keep their input relative order, after the boxed lines."""
    boxed: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    for line in lines:
        box = line.get("box")
        if isinstance(box, list) and len(box) == 4 and box[2] > box[0] and box[3] > box[1]:
            boxed.append(line)
        else:
            rest.append(line)
    # reading_start returns (x, y); the reading ORDER compares top-to-bottom
    # first (y), then left-to-right (x)
    boxed.sort(
        key=lambda line: (
            reading_start(line["box"], line.get("orientation", 0))[1],
            reading_start(line["box"], line.get("orientation", 0))[0],
        )
    )
    return boxed + rest


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
            b = vlm_boxes[vi]
            words_out = _words_out(
                vw,
                selfreport_line=report_by_line.get(vi),
                rec_words=[],
                use_selfreport=use_selfreport,
            )
            line_conf = (sum(w["conf"] for w in words_out) / len(words_out)) if words_out else 0.0
            x0, y0, x1, y1 = b
            lines.append(
                {
                    "index": vi,
                    "text": line,
                    "box": [
                        x0 / NORMALIZED_BOX_SCALE * width,
                        y0 / NORMALIZED_BOX_SCALE * height,
                        x1 / NORMALIZED_BOX_SCALE * width,
                        y1 / NORMALIZED_BOX_SCALE * height,
                    ],
                    "conf": line_conf,
                    "words": words_out,
                    "box_source": "vlm",
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
    # physical reading order for the review pane — the transcription order
    # scrambles multi-orientation pages (2026-08-20); the sort preserves
    # each line's index (the edit key), only the display order changes
    lines = order_lines_by_reading(lines)
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


def admission_gate(text: str, score: float) -> bool:
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
        if admission_gate(text, score):
            entry["box"] = remap_box(det["box"], degrees, original, rotated)
            kept.append(entry)
        else:
            entry["box"] = [round(v, 1) for v in det["box"]]
            rejected.append(entry)
    return kept, rejected


def _box_area(box: list[float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _box_overlap(a: list[float], b: list[float]) -> float:
    """The intersection over the SMALLER box — a tall strip inside a wide
    box still claims the same region."""
    x = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    y = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return (x * y) / min(_box_area(a), _box_area(b), _MIN_AREA_EPSILON)


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
            if _box_overlap(a["box"], b["box"]) > _DEDUPE_OVERLAP and _richness(b) > _richness(a):
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


def _located_box(
    report: dict[str, Any] | None,
    match: dict[str, Any] | None,
    width: int,
    height: int,
) -> list[float] | None:
    """The line's box: the report's located box (normalized 0-1000 scaled
    to pixels; [0,0,0,0] = not located) when it claims the same ink a
    CONTENT match read (the per-line refinement, the v3 design), else
    the content match's box — the detector's ink-grounded geometry
    (2026-08-20: page-03's transcription boxes sat ~200px above the real
    text; a report box disjoint from the matched detection is an
    estimate, not an anchor). A POSITIONAL match's box is unrelated ink
    (the k-th unmatched detection), never evidence — the report's box
    anchors over it (the v3 design). Else the report's box, else the
    match's box, else None — a boxless line is flagged (2026-08-17)."""
    b = report.get("box") if report else None
    if b and (b[2] > b[0] or b[3] > b[1]):
        scaled = [
            b[0] / NORMALIZED_BOX_SCALE * width,
            b[1] / NORMALIZED_BOX_SCALE * height,
            b[2] / NORMALIZED_BOX_SCALE * width,
            b[3] / NORMALIZED_BOX_SCALE * height,
        ]
        if match and match.get("box_source") == "content":
            if _box_overlap(scaled, match["box"]) >= _LOCATED_OVERLAP:
                return scaled
            return match["box"]
        return scaled
    return match["box"] if match else None


def _aspect_consistent(degrees: int, box: list[float] | None) -> bool:
    """Is the orientation consistent with the box's aspect — Gate A's
    deterministic rule, shared by the orientation resolution (a line's
    orientation must come from geometry-validated data, 2026-08-20): a
    clearly-wide box is horizontal text, a clearly-tall box is vertical.
    Near-square boxes and diagonal angles (45°) are always consistent
    (lenient — a diagonal line is genuinely diagonal). ``None`` box (no
    geometry) is always consistent."""
    if not box:
        return True
    box_w = box[2] - box[0]
    box_h = box[3] - box[1]
    if box_w <= 2 * box_h and box_h <= 2 * box_w:
        return True  # near-square — no aspect constraint
    axis = degrees % 180
    vertical = 60 <= axis <= 120
    horizontal = axis <= 30 or axis >= 150
    if box_w > 2 * box_h:
        return not vertical  # clearly wide: horizontal text only
    return not horizontal  # clearly tall: vertical text only


def _line_orientation(
    r: dict[str, Any] | None,
    match: dict[str, Any] | None,
    trust_report_degrees: bool,
    box: list[float] | None,
) -> int:
    """The anchored line's orientation — the precedence resolved against
    the box's aspect (extracted from _vlm_text_lines 2026-08-20 when the
    trust flag pushed its cyclomatic complexity over lucidlint's bar).
    The candidates: the report's LOCATED degrees first when trustworthy
    (the clip-classified report, whose per-line angles are measured from
    the actual text), else the rec match's pass orientation — the pass
    that READ the text is the ground truth for the view rotation when
    the report's estimates are the flaky full-page call's (the 2026-08-17
    90-vs-270 flip) — then the report's degrees, then 0. Only the first
    ASPECT-CONSISTENT candidate wins (a 90° label on a wide box is a
    mirrored-pass artifact: page-03's horizontal lines were
    content-matched during the 90° pass); near-square boxes accept the
    first candidate."""
    candidates: list[int] = []
    if trust_report_degrees and r and isinstance(r.get("degrees"), (int, float)):
        candidates.append(int(r["degrees"]))
    if match and isinstance(match.get("orientation"), int):
        candidates.append(int(match["orientation"]))
    if not trust_report_degrees and r and isinstance(r.get("degrees"), (int, float)):
        candidates.append(int(r["degrees"]))
    candidates.append(0)
    for degrees in candidates:
        if _aspect_consistent(degrees, box):
            return degrees
    return candidates[0]


# the anchored-lines assembly's six inputs — the page geometry, the report evidence, the trust flag — are one
# pure function's data; a parameter object would obscure it (the same why as multi_layout's suppression)
# lucidlint: ignore long-param-list a parameter object would obscure the pure function
def _vlm_text_lines(
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
        located = _located_box(r, match, width, height)
        orientation = _line_orientation(r, match, trust_report_degrees, located)
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
    if _text_extent_violation(text, x1 - x0, y1 - y0, float(orientation)):
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
        orientation = pass_orientation if _aspect_consistent(pass_orientation, det["box"]) else 0
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
            lines = _vlm_text_lines(
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
                "orientation": degrees if _aspect_consistent(degrees, entry["box"]) else 0,
                "box_source": "multi",
                "words": _multi_line_words(entry["text"], entry.get("words", []), entry["score"]),
            }
            for degrees, admitted in sorted(passes, key=lambda p: p[0])
            for entry in admitted
        ]
    lines = dedupe_regions(lines)
    # physical reading order — replaces the old by-orientation grouping
    # (2026-08-20: the report's text order scrambled multi-orientation
    # pages); the sort is stable and the indices are renumbered to the
    # display order (these lines are the detection admissions, not the
    # guess text)
    lines = order_lines_by_reading(lines)
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


def _orientation_violation(orientation: float, box_w: float, box_h: float, text: str) -> str | None:
    """Gate A (2026-08-20): the line's orientation must be consistent
    with its box's aspect. The AXIS (mod 180) handles EXACT angles — an
    88.4° line is vertical-axis and must have a tall box. Fails only on
    the clearly-wrong cases (aspect >= 2x against a clearly-opposite
    axis); diagonal angles and near-square boxes pass (lenient — a 45°
    line is genuinely diagonal). Returns the violation or None."""
    axis = orientation % 180
    clearly_wide = box_w > 2 * box_h
    clearly_tall = box_h > 2 * box_w
    vertical_axis = 60 <= axis <= 120
    horizontal_axis = axis <= 30 or axis >= 150
    if (clearly_wide and vertical_axis) or (clearly_tall and horizontal_axis):
        return f"{text[:20]!r}: orientation {orientation:.1f}° inconsistent with a {int(box_w)}x{int(box_h)} box"
    return None


def _text_extent_violation(text: str, box_w: float, box_h: float, orientation: float | None) -> str | None:
    """Gate B (2026-08-20): the recognized text length must not be
    WILDLY out of sync with the box's reading-axis extent — a 500px-wide
    box holding 3 characters is empty or truncated; a 50px box holding
    40 characters is impossible. The gate is loose (only ~2-80 px/char
    fails — the far-too-short nonsense is the >80 side) so handwriting
    variance never false-positives; an empty text with a box fails
    ("nothing there"). The axis defaults to horizontal (width) when the
    line has no orientation. Returns the violation or None."""
    axis = (orientation or 0) % 180
    reading_extent = box_w if (axis <= 45 or axis >= 135) else box_h
    if not text.strip() and reading_extent > 0:
        return f"{text[:20]!r}: empty text in a {int(box_w)}x{int(box_h)} box"
    if text.strip():
        px_per_char = reading_extent / len(text.strip())
        if px_per_char < 2 or px_per_char > 80:
            return (
                f"{text[:20]!r}: text length {len(text.strip())} wildly out of "
                f"sync with a {int(reading_extent)}px reading axis ({px_per_char:.0f} px/char)"
            )
    return None


def _line_violations(line: dict[str, Any], width: int, height: int, tolerance: float) -> list[str]:
    """The per-line fail-fast checks, one line's violations ([] = clean).
    Extracted from validate_layout (2026-08-20) when the two new gates
    pushed its cyclomatic complexity over lucidlint's bar — the loop
    itself is trivial; this carries the actual judgement. ``None`` boxes
    pass (the line is flagged, the review shows it without a box)."""
    violations: list[str] = []
    box = line.get("box")
    if box is None:
        return violations
    if len(box) != 4 or not all(isinstance(v, (int, float)) for v in box):
        violations.append(f"{line.get('text', '')[:20]!r}: malformed box {box}")
        return violations
    x0, y0, x1, y1 = box
    if x1 <= x0 or y1 <= y0:
        violations.append(f"{line.get('text', '')[:20]!r}: degenerate box {box}")
        return violations
    if x0 < -tolerance or y0 < -tolerance or x1 > width + tolerance or y1 > height + tolerance:
        violations.append(f"{line.get('text', '')[:20]!r}: box outside the image {box}")
        return violations
    box_w = x1 - x0
    box_h = y1 - y0
    text = line.get("text", "")
    orientation = line.get("orientation")
    if isinstance(orientation, (int, float)):
        gate_a = _orientation_violation(orientation, box_w, box_h, text)
        if gate_a:
            violations.append(gate_a)
        gate_b = _text_extent_violation(text, box_w, box_h, orientation)
    else:
        gate_b = _text_extent_violation(text, box_w, box_h, None)
    if gate_b:
        violations.append(gate_b)
    return violations


def validate_layout(layout: dict[str, Any], tolerance: float = 4.0) -> list[str]:
    """The fail-fast box guard (2026-08-17): a layout whose line has a
    box that is degenerate or outside the image must NEVER reach the
    front end — the reviewer must never see wrong boxes (the reproduced
    incident: page-02's reprocessed layout carried approximate boxes to
    the review surface silently). Returns the violations; [] = clean.
    ``None`` boxes are fine (the line is flagged, the review shows it
    without a box); the tolerance covers the model's estimate slop.

    Two more gates (2026-08-20), both in user-need language from the
    multi-orientation review: the line's orientation must be consistent
    with its box's aspect (Gate A), and the recognized text length must
    not be wildly out of sync with the box's reading-axis extent (Gate B).
    Both handle EXACT angles (88.4°, 271.2°) via the orientation's axis
    (mod 180), and both are deliberately lenient — a 45° diagonal line and
    a near-square box are never flagged. page-03's orientation report
    labeled 26 horizontal lines as 90°, which cascaded into the layout,
    the UI rotation, and the reading-order sort: Gate A catches that class
    with no model in the loop. Gate B's >80 px/char side catches the
    "far-too-short" fragments; the <2 px/char side catches impossible
    density."""
    width = int(layout.get("width", 0))
    height = int(layout.get("height", 0))
    violations: list[str] = []
    for line in layout.get("lines", []):
        violations.extend(_line_violations(line, width, height, tolerance))
    return violations


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
