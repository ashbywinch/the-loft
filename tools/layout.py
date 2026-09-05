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
import math
import re
import unicodedata
from pathlib import Path
from typing import Any, TypedDict

from tools.atomic import atomic_write


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
QUARTERS_PER_FULL_TURN = 4  # a full rotation is four quarter-turns (90° each)

# The multi-orientation admission (PRD VR15, 2026-08-16 prototype): a
# detected line is admitted only when the recognizer read REAL text at
# that orientation — confidence + plausibility — never on box shape
# alone, so an accidental upside-down pass's boxes are rejected.
REC_SCORE_GATE = 0.85  # recognition confidence: real words read at the right orientation
MIN_LETTERS = 2  # plausibility: a "real word" has letters, not just shapes
_DEDUPE_OVERLAP = 0.3  # two passes' lines sharing this much of the smaller box are the same physical region

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


# lucidlint: ignore closures one coherent greedy-match algorithm — the closures are sort keys
def associate_lines(vlm_lines: list[str], detections: list[Detection]) -> tuple[list[dict[str, Any]], list[Detection]]:
    """Match detector lines to VLM transcription lines by content.

    Reading orders differ (the engines disagree on where a marginal note
    sits), so the match is best normalized word-set overlap above
    MATCH_THRESHOLD, ties broken by reading order (y-first). Each VLM line
    claims at most one detector line and vice versa. Returns (matches,
    unmatched_detections), where matches are in VLM line order:
        {"vlm": str, "vlm_index": int, "box": [x0,y0,x1,y1],
         "rec_text": str, "rec_score": float,
         "rec_words": [str, ...]}
    """
    vlm_sets = [set(words(line)) for line in vlm_lines]
    used_vlm: set[int] = set()
    used_det: set[int] = set()
    matches: list[dict[str, Any]] = []

    def y_of(det: Detection) -> float:
        return det["box"][1]

    # Greedy in detector reading order: each detector line claims its best
    # still-free VLM line. The pair is dropped when no candidate clears the
    # threshold (the rec text is too noisy to anchor).
    for di in sorted(range(len(detections)), key=lambda i: y_of(detections[i])):
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
                }
            )
    matches.sort(key=lambda m: m["vlm_index"])
    unmatched = [d for i, d in enumerate(detections) if i not in used_det]
    # Positional fallback (2026-08-16: the audit found 101 of 323 lines
    # boxless — the rec model cannot read cursive, so whole pages never
    # content-match). The boxless VLM lines take the unmatched detections in
    # reading order: both lists run top-to-bottom, so the k-th boxless line
    # takes the k-th unmatched detection's geometry. The anchor is
    # positional, not textual (the rec text never matched) — the caller
    # marks it, and the surface renders positional boxes dashed.
    boxless = [vi for vi in range(len(vlm_lines)) if vi not in used_vlm]
    unmatched.sort(key=lambda d: d["box"][1])
    matches.extend(
        {
            "vlm": vlm_lines[vi],
            "vlm_index": vi,
            "box": det["box"],
            "rec_text": det["text"],
            "rec_score": det["score"],
            "rec_words": words(det["text"]),
            "det_words": det.get("words", []),
            "box_source": "positional",
        }
        for vi, det in zip(boxless, unmatched, strict=False)
    )
    matches.sort(key=lambda m: m["vlm_index"])
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
    original image (original = ow×oh) — the inverse of the applied
    rotation, exact for a rigid quarter-turn."""
    ow, oh = original
    rw, rh = rotated
    rad = math.radians(degrees)
    ox, oy = ow / 2, oh / 2
    rx, ry = rw / 2, rh / 2
    xs: list[float] = []
    ys: list[float] = []
    for x, y in ((box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])):
        dx, dy = x - rx, y - ry
        xs.append(dx * math.cos(rad) - dy * math.sin(rad) + ox)
        ys.append(dx * math.sin(rad) + dy * math.cos(rad) + oy)
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
    return (x * y) / min(_box_area(a), _box_area(b), 1e-9)


def _richness(line: dict[str, Any]) -> tuple[int, float]:
    """The reading's strength — more letters beat fewer; ties by score.
    The dedupe keeps the BEST reading of a physical region across the
    orientation passes (2026-08-17: the postcard's vertical strips were
    read at 0°, 90° AND 270° — 'MHOTH' (90°) vs 'HARBOTTLE, MORPETH'
    (270°) share a box at IoU 0.97; only the richer survives)."""
    return sum(1 for ch in line["text"] if ch.isalpha()), float(line["conf"])


def dedupe_regions(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop the weaker readings of the same physical region across
    orientations: a line is kept only when no other line overlaps its box
    with a strictly richer reading. Ties keep the earlier line. The
    survivors keep their index — the caller re-indexes after."""
    keep = [True] * len(lines)
    for i, a in enumerate(lines):
        for j, b in enumerate(lines):
            if i == j or not keep[i] or not keep[j]:
                continue
            if _box_overlap(a["box"], b["box"]) > _DEDUPE_OVERLAP and _richness(b) > _richness(a):
                keep[i] = False
                break
    return [line for line, k in zip(lines, keep, strict=True) if k]


def multi_layout(
    page: str,
    width: int,
    height: int,
    passes: list[tuple[int, list[dict[str, Any]]]],
) -> dict[str, Any]:
    """The combined multi-orientation layout (PRD VR15): the admitted
    lines from each orientation pass, ordered 0° first then each next
    direction, each line carrying the orientation it was read at. The
    passes' boxes are already remapped to the original image's pixels;
    width/height are the original (oriented) image's. The rec text is
    the provisional transcription (VR14) — the reviewer corrects it.
    The same physical region read in several passes keeps only its
    best reading (dedupe_regions)."""
    lines: list[dict[str, Any]] = []
    for degrees, admitted in sorted(passes, key=lambda p: p[0]):
        for entry in admitted:
            lines.append(
                {
                    "index": len(lines),
                    "text": entry["text"],
                    "box": entry["box"],
                    "conf": entry["score"],
                    "orientation": degrees,
                    "box_source": "multi",
                    "words": [{"box": w.get("box"), "conf": entry["score"]} for w in entry.get("words", [])],
                }
            )
    lines = dedupe_regions(lines)
    for i, line in enumerate(lines):
        line["index"] = i
    return {"page": page, "width": width, "height": height, "lines": lines, "unmatched": []}


def load_orientation_hint(path: Path) -> list[int]:
    """The page's distinct text orientations (0/90/180/270), written by
    the pipeline stage when the arbiter's scores suggested more than one
    direction (PRD VR15). [] = a single orientation — the plain
    single-orientation layout path applies."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    degrees = {int(h.get("degrees")) for h in data if isinstance(h, dict) and h.get("degrees") in (0, 90, 180, 270)}
    return sorted(degrees) if len(degrees) >= 2 else []


def orientation_passes(degrees: list[int]) -> list[int]:
    """The detection passes for a page's reported orientations. A
    reported vertical direction (90 or 270) runs BOTH its mirrors: the
    vision model flips between 90 and 270 for the same physical block
    between calls (2026-08-17), and a pass at the wrong direction leaves
    the block upside-down — the recognition admission then rejects it
    and the text is silently missed. The mirror pass costs one detection
    run (no model call) and admits nothing garbage."""
    out = set(degrees)
    for d in degrees:
        if d in (90, 270):
            out.add(270 if d == 90 else 90)
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
    write-then-rename)."""
    atomic_write(path, json.dumps(layout, indent=1, ensure_ascii=False) + "\n")
