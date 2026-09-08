"""The single-pass segment-and-transcribe stage (TECH-SPEC §16.17): ONE
multimodal VLM call per page returns every text segment with its verbatim
text, its orientation, and its bounding box — text detection, box
detection and transcription in one pass, replacing the detect-then-match
pipeline (PaddleOCR boxes + separate VLM text + anchor matching).

The response contract (validated, fail-fast per the testing standard — a
garbage response raises, never silently skips):

    {"segments": [{"label": "header", "text": "POST CARD.",
                   "orientation": 0, "box_2d": [x0, y0, x1, y1]}, …]}

``box_2d`` is NORMALIZED 0-1000 (fractions of width/height × 1000 — the
house convention, tools/vlm.py); ``orientation`` is the text's reading
rotation in degrees (0/90/180/270). ``segment_page`` returns the segments
with boxes converted to ORIGINAL-IMAGE PIXELS. With ``grid`` the page
carries a labeled coordinate ruler and the boxes come back as "box_px"
read off that ruler."""

from __future__ import annotations

# lucidlint: ignore-file record-shape the stage's wire is the house group/segment dicts; the class lands in slice 5
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from tools.ink import union
from tools.layout import Layout
from tools.strip_measure import Strip, draw_numbered_strips
from tools.vlm import DEFAULT_BASE_URL, transcribe_image_vlm

_FENCE = "```"  # the markdown fence the model wraps its JSON in (tools/vlm.py)

_ORIENTATIONS = {0, 90, 180, 270}


def _tighten_to_ink(box: list[float], image: Path, pad: int = 12) -> list[float]:
    """Snap a grid-read box to the ink it encloses — a measurement
    inside a region the model already chose, never a segmentation
    decision. A box with no ink comes back unchanged (the gates judge
    it)."""
    with Image.open(image) as im:
        gray = im.convert("L")
        width, height = gray.size
    x0, y0, x1, y1 = (int(v) for v in box)
    px0, py0 = max(0, x0 - pad), max(0, y0 - pad)
    px1, py1 = min(width, x1 + pad), min(height, y1 + pad)
    if px1 <= px0 or py1 <= py0:
        return box
    crop = gray.crop((px0, py0, px1, py1))
    table = [255 if v < 128 else 0 for v in range(256)]
    bbox = crop.point(table).getbbox()  # the dark pixels' extent, in C speed
    if bbox is None:
        return box
    return [float(px0 + bbox[0]), float(py0 + bbox[1]), float(px0 + bbox[2]), float(py0 + bbox[3])]


class SegmentPageError(RuntimeError):
    """The segment response violated the contract — fail loudly, never
    silently skip (the fail-fast standard; a garbage response must stop
    the pipeline, not green it)."""


def _strip_fences(text: str) -> str:
    """The markdown fence the model sometimes wraps its JSON in."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped[len(_FENCE) :]
        if stripped.endswith("```"):
            stripped = stripped[: -len(_FENCE)]
    return stripped.strip()


def _parse_json_object(text: str, what: str) -> dict[str, Any]:
    """The model's JSON object, tolerating a code-fence wrapper with a
    language tag (```json … ```) and locating the outermost braces when
    bare parsing fails (the house tolerance, tools/vlm.py
    _extract_json)."""
    stripped = text.strip()
    if stripped.startswith(_FENCE):
        stripped = stripped.split("\n", 1)[-1]
        if stripped.endswith(_FENCE):
            stripped = stripped[: -len(_FENCE)]
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start < 0 or end <= start:
            raise SegmentPageError(f"the {what} has no JSON: {text[:200]}") from None
        parsed = json.loads(stripped[start : end + 1])
    if not isinstance(parsed, dict):
        raise SegmentPageError(f"the {what} is not a JSON object: {text[:200]}")
    return parsed


def _segment_index(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SegmentPageError(f"the verification's answer has no usable index: {value!r}")
    return int(value)


def _draw_reported_boxes(image: Path, segments: list[dict[str, Any]], path: Path) -> None:
    """The reported boxes drawn on the page in red, numbered — the
    model critiques what it sees (Set-of-Mark, 2023)."""
    with Image.open(image) as im:
        annotated = im.convert("RGB").copy()
    draw = ImageDraw.Draw(annotated)
    for i, s in enumerate(segments):
        box = s.get("box")
        if not isinstance(box, list) or len(box) != 4:
            continue
        x0, y0, x1, y1 = (int(v) for v in box)
        draw.rectangle((x0, y0, x1, y1), outline=(255, 0, 0), width=3)
        draw.text((x0 + 4, max(0, y0 - 18)), str(i), fill=(255, 0, 0))
    annotated.save(path)


# --- The grouping read (strip-grouping-plan slices 2/2b, 2026-09-08).
# Coordinate generation is gone for ALL pages: the Godolphin card's
# 90-degree message failed the coordinate path the same way the typed
# letter failed it — there is no working path to protect. The strips
# are MEASURED (tools.strip_measure) and drawn numbered on the page;
# the model GROUPS the numbered pieces into segments and transcribes
# each group verbatim — it never generates a coordinate (L3/L11).

GROUP_BATCH_PIECES = 50  # the coverage contract's batch ceiling (the plan, 2026-09-08)

_GROUP_SYSTEM = (
    "You transcribe scanned family documents verbatim and group their "
    "measured strips of writing into segments. Rules: the document's "
    "own words, nothing added, nothing removed — fix nothing, "
    "summarize nothing, invent nothing. Unreadable words: transcribe "
    "your best literal guess. Formatting that matters — keep the "
    "markers, they are content: a word the writer CROSSED OUT is "
    "marked ~~word~~ (double tildes either side); a word the writer "
    "UNDERLINED is marked ~word~ (single tildes either side). For "
    "printed text and handwriting alike, at any orientation — read "
    "each block in its own direction and report that direction. "
    "The page carries MEASURED rectangles: thin green outlines with "
    "margin numbers, each one a fragment of writing the line detector "
    "measured. Group the numbered pieces into SEGMENTS. A segment is "
    "the longest run of text on a single line that belongs together, "
    "and the definition is exact — do NOT:"
    " merge consecutive written lines of a paragraph into one segment"
    " (each written line is its own segment);"
    " let a segment cross a column boundary (each column's lines are "
    "their own segments);"
    " merge a margin annotation or side note with the body line it "
    "sits beside (the note is its own segment);"
    " merge text in a different hand into the same segment."
    " A piece with no writing on it — blank paper, a smudge, the "
    'margin number itself — belongs in "empty". '
    'Return ONLY JSON: {"lines": [{"pieces": [0, 3], "text": "the '
    'segment verbatim", "orientation": 0}], "empty": [7]} — the '
    "batch's numbered pieces partitioned exactly: every owned piece "
    "appears in exactly one line's pieces or in empty, never in both, "
    'never omitted. "orientation" is the line\'s reading rotation in '
    "degrees: 0 (upright), 90, 180 or 270 — read each line in its own "
    "direction and report that direction."
)


def _grouping_user_text(start: int, stop: int, total: int) -> str:
    """The batch's user message: which numbered pieces this call owns."""
    return (
        f"This batch owns pieces {start}..{stop - 1} ({total} rectangles "
        "are numbered on the page). Group ONLY these pieces."
    )


def _validated_grouping(answer: dict[str, Any], owned: set[int]) -> tuple[list[dict[str, Any]], set[int], set[int]]:
    """The batch's groups, its empty verdict, and the unaccounted
    pieces. A contract violation refuses (fail-loud): an unknown or
    duplicate piece index, a malformed entry, an orientation outside
    0/90/180/270. An empty-text group IS the model's no-writing
    verdict — its pieces join the empties."""

    def piece_index(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SegmentPageError(f"the grouping answer has no usable piece index: {value!r}")
        piece = int(value)
        if piece not in owned:
            raise SegmentPageError(f"piece {piece} is not one of this batch's pieces {sorted(owned)}")
        return piece

    raw_lines = answer.get("lines", [])
    if not isinstance(raw_lines, list):
        raise SegmentPageError(f"grouping 'lines' is not a list: {raw_lines!r}")
    raw_empty = answer.get("empty", [])
    if not isinstance(raw_empty, list):
        raise SegmentPageError(f"grouping 'empty' is not a list: {raw_empty!r}")
    empties = {piece_index(p) for p in raw_empty}
    claimed: set[int] = set()
    groups: list[dict[str, Any]] = []
    for entry in raw_lines:
        if not isinstance(entry, dict):
            raise SegmentPageError(f"grouping entry is not an object: {entry!r}")
        pieces_raw = entry.get("pieces")
        if not isinstance(pieces_raw, list) or not pieces_raw:
            raise SegmentPageError(f"a grouping entry has no pieces: {entry!r}")
        pieces = [piece_index(p) for p in pieces_raw]
        text = str(entry.get("text", "")).strip()
        orientation = int(entry.get("orientation", 0) or 0)
        if orientation not in _ORIENTATIONS:
            raise SegmentPageError(f"grouping orientation {orientation} is not 0/90/180/270: {entry!r}")
        for piece in pieces:
            if piece in claimed or piece in empties:
                raise SegmentPageError(f"piece {piece} appears in more than one place: {entry!r}")
            claimed.add(piece)
        groups.append({"pieces": pieces, "text": text, "orientation": orientation})
    lines = []
    for group in groups:
        if group["text"]:
            lines.append(group)
        else:
            empties |= set(group["pieces"])
    return lines, empties, owned - claimed - empties


def _merge_usage(total: dict[str, Any], usage: dict[str, Any]) -> None:
    """Fold one call's usage into the run's total — token counts sum,
    the reasoning trace concatenates (the two-pass pattern). Nested
    detail objects (the gateway's prompt_tokens_details) don't
    accumulate — the three top-level token counts are the cost."""
    for key, value in usage.items():
        if isinstance(value, str):
            total[key] = total.get(key, "") + value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            total[key] = total.get(key, 0) + value


# lucidlint: ignore latent-class these four share the store's group/segment dict contract; the class lands in slice 5
def group_segments(  # lucidlint: ignore long-param-list one required argument (image) plus defaulted call options
    image: Path,
    strips: list[Strip],
    work_dir: Path,
    *,
    model: str = "primary",
    base_url: str = DEFAULT_BASE_URL,
    api_key: str | None = None,
    max_tokens: int = 64000,
    urlopen: Callable[..., Any] | None = None,
) -> tuple[list[dict[str, Any]], set[int], dict[str, Any]]:
    """The grouping read: the measured strips drawn numbered on the
    page, ONE call per batch of <= GROUP_BATCH_PIECES pieces grouping
    them into segments with verbatim text and reading rotation. Every
    piece must be accounted — a line's pieces or "empty"; a batch with
    pieces missing after the ONE re-ask serves without them, the loss
    named in the run log and returned as the dropped set (the ruling,
    2026-09-08: the user judges from the served pages). Returns
    (groups, dropped pieces, token usage); raises SegmentPageError on
    any other contract violation — fail loudly, never skip."""
    if not strips:
        raise SegmentPageError("no strips measured — nothing to group")
    annotated = work_dir / "strips.jpg"
    draw_numbered_strips(image, strips, annotated)
    groups: list[dict[str, Any]] = []
    dropped: set[int] = set()
    usage_total: dict[str, Any] = {}
    for start in range(0, len(strips), GROUP_BATCH_PIECES):
        stop = min(start + GROUP_BATCH_PIECES, len(strips))
        owned = set(range(start, stop))
        batch_user = _grouping_user_text(start, stop, len(strips))

        def read_grouping(user_text: str) -> tuple[dict[str, Any], dict[str, Any]]:
            text, usage = transcribe_image_vlm(
                annotated,
                model=model,
                system=_GROUP_SYSTEM,
                user_text=user_text,
                base_url=base_url,
                api_key=api_key,
                max_tokens=max_tokens,
                urlopen=urlopen,
            )
            _merge_usage(usage_total, usage)
            return _parse_json_object(text, "grouping response"), usage

        answer, _ = read_grouping(batch_user)
        batch_groups, _, missing = _validated_grouping(answer, owned)
        if missing:
            reask = (
                f"Your response did not account for pieces {sorted(missing)}. "
                "Return the FULL contract again — every owned piece in "
                "exactly one line's pieces or in empty, none omitted."
            )
            answer, _ = read_grouping(f"{batch_user} {reask}")
            batch_groups, _, still_missing = _validated_grouping(answer, owned)
            if still_missing:
                dropped |= still_missing
                print(
                    f"grouping: pieces {sorted(still_missing)} unaccounted after "
                    "the re-ask — serving without them (the loss is named)"
                )
        groups.extend(batch_groups)
    return groups, dropped, usage_total


def measure_group_boxes(image: Path, groups: list[dict[str, Any]], strips: list[Strip]) -> list[dict[str, Any]]:
    """Each group's box = the ink projection of its band (pad ±6px) —
    NOT the union of its listed pieces (page-01's read under-listed a
    line's pieces: 104 chars on one 50px piece; the band measurement is
    immune). The band is the pieces' measured union; the ink inside it
    fixes the box, clamped to the page. A band with no ink keeps the
    measured band (the gates judge it)."""
    by_number = {strip.number: strip for strip in strips}
    segments = []
    for group in groups:
        pieces = [by_number[piece] for piece in group["pieces"]]
        band = union([piece.as_box() for piece in pieces])
        box = _tighten_to_ink(band, image, pad=6)
        # lucidlint: ignore record-shape the stage's wire is the established group/segment dicts
        segments.append(
            {
                "label": "line",
                "text": str(group["text"]),
                "orientation": int(group["orientation"]),
                "box": box,
                "pieces": list(group["pieces"]),
                "box_source": "grouped-strips",
            }
        )
    return segments


GROUPED_VERIFY_ROUNDS = 2  # the bounded loop: converge within two rounds or refuse (slice 4)

_GROUPED_VERIFY_FORMAT = (
    'Return ONLY JSON: {"corrections": [{"index": 2, "pieces": [12, 13], '
    '"text": "the segment verbatim", "orientation": 0}], "not_present": []} '
    "— corrections ONLY for segments whose entry carries a CHECK FAILED "
    "finding; pieces are the numbered green rectangles the segment "
    "actually covers; not_present lists indexes whose rectangle sits on "
    "blank paper. Every other segment stays as reported."
)

_GROUPED_VERIFY_SYSTEM = (
    "You are checking your own grouping of a scanned family document's "
    "measured strips. The image has the reported segments' rectangles "
    "drawn on it in red and numbered — the number is that segment's "
    "index. A segment is the longest run of text on a single line that "
    "belongs together: it never crosses a column boundary, never "
    "includes a neighboring written line, never merges a margin note "
    "with the body line beside it, never mixes hands. Segments whose "
    "entry carries a CHECK FAILED finding were measured by an automated "
    "checker: the finding names exactly what is wrong — read it, "
    "re-group that segment's pieces and re-transcribe it accordingly. "
    "The rectangles themselves are measured data: fix the grouping and "
    "the words, never invent a box. " + _GROUPED_VERIFY_FORMAT
)


def build_grouped_verify_prompt(segments: list[dict[str, Any]], errors: dict[int, str]) -> str:
    """The verification round's user prompt — deterministic from the
    grouped segments and the checker's findings (build_verify_prompt's
    contract, in the grouping contract's pieces-and-text terms)."""
    listed = []
    for i, segment in enumerate(segments):
        entry = f"- index {i}: text {str(segment.get('text', ''))!r}, pieces {segment.get('pieces', [])}"
        if i in errors:
            entry += f"\n  CHECK FAILED: {errors[i]}"
        listed.append(entry)
    findings = (
        f"\n{len(errors)} of them carry CHECK FAILED findings — those are gate measurements, proven wrong."
        if errors
        else ""
    )
    return "Your grouped segments:\n" + "\n".join(listed) + findings


def verify_grouped_segments(  # lucidlint: ignore long-param-list one required argument plus defaulted call options
    image: Path,
    strips: list[Strip],
    segments: list[dict[str, Any]],
    work_dir: Path,
    *,
    findings: dict[int, str],
    model: str = "primary",
    base_url: str = DEFAULT_BASE_URL,
    api_key: str | None = None,
    max_tokens: int = 64000,
    urlopen: Callable[..., Any] | None = None,
) -> tuple[dict[int, dict[str, Any]], set[int], dict[str, Any]]:
    """ONE bounded verification round (slice 4): the reported segments'
    rectangles drawn on the page in red and numbered, the checker's
    CHECK FAILED findings attached, and the flagged segments re-read in
    the grouping contract — corrected pieces and words, never a
    generated box. Returns ({index: corrected group}, not-present
    indexes, token usage); a contract violation raises."""
    annotated = work_dir / "verify.jpg"
    _draw_reported_boxes(image, segments, annotated)
    text, usage = transcribe_image_vlm(
        annotated,
        model=model,
        system=_GROUPED_VERIFY_SYSTEM,
        user_text=build_grouped_verify_prompt(segments, findings),
        base_url=base_url,
        api_key=api_key,
        max_tokens=max_tokens,
        urlopen=urlopen,
    )
    answer = _parse_json_object(text, "verification response")
    by_number = {strip.number for strip in strips}
    corrections: dict[int, dict[str, Any]] = {}
    dropped: set[int] = set()
    raw = answer.get("corrections", [])
    if not isinstance(raw, list):
        raise SegmentPageError(f"verification 'corrections' is not a list: {raw!r}")
    for entry in raw:
        if not isinstance(entry, dict):
            raise SegmentPageError(f"verification correction is not an object: {entry!r}")
        index = _segment_index(entry.get("index"))
        if not 0 <= index < len(segments):
            raise SegmentPageError(f"verification index {index} is out of range")
        pieces_raw = entry.get("pieces")
        if not isinstance(pieces_raw, list) or not pieces_raw:
            raise SegmentPageError(f"a correction has no pieces: {entry!r}")
        piece_numbers = []
        for piece in pieces_raw:
            if isinstance(piece, bool) or not isinstance(piece, (int, float)) or int(piece) not in by_number:
                raise SegmentPageError(f"correction names unknown piece {piece!r}")
            piece_numbers.append(int(piece))
        corrected_text = str(entry.get("text", "")).strip()
        if not corrected_text:
            raise SegmentPageError(f"a correction has no text: {entry!r}")
        orientation = int(entry.get("orientation", 0) or 0)
        if orientation not in _ORIENTATIONS:
            raise SegmentPageError(f"correction orientation {orientation} is not 0/90/180/270: {entry!r}")
        if index in corrections or index in dropped:
            raise SegmentPageError(f"segment {index} is corrected more than once: {entry!r}")
        corrections[index] = {"pieces": piece_numbers, "text": corrected_text, "orientation": orientation}
    raw_not_present = answer.get("not_present", [])
    if not isinstance(raw_not_present, list):
        raise SegmentPageError(f"verification 'not_present' is not a list: {raw_not_present!r}")
    for value in raw_not_present:
        index = _segment_index(value)
        if not 0 <= index < len(segments):
            raise SegmentPageError(f"verification index {index} is out of range")
        if index in corrections:
            raise SegmentPageError(f"segment {index} is both corrected and not present: {value!r}")
        dropped.add(index)
    return corrections, dropped, usage


def _grouped_layout(image: Path, segments: list[dict[str, Any]]) -> Layout:
    """The loop's working layout: the Layout the pipeline stores —
    indexed lines the findings map keys on, box_source marking the
    grouped provenance."""
    with Image.open(image) as im:
        width, height = im.size
    lines = [
        {
            "index": index,
            "text": segment["text"],
            "box": segment["box"],
            "conf": 1.0,
            "words": [],
            "orientation": segment["orientation"],
            "box_source": "grouped-strips",
        }
        for index, segment in enumerate(segments)
    ]
    return Layout("", width, height, lines, [])


# lucidlint: ignore latent-class the loop rebuilds from image, groups, segments per round — context object is slice 5's
def converge_grouped_layout(  # lucidlint: ignore long-param-list the loop's inputs are the read stage's own products
    image: Path,
    strips: list[Strip],
    groups: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    work_dir: Path,
    *,
    findings_fn: Callable[[Layout, list[str]], dict[int, str]],
    model: str = "primary",
    base_url: str = DEFAULT_BASE_URL,
    api_key: str | None = None,
    max_tokens: int = 64000,
    urlopen: Callable[..., Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The bounded findings loop (slice 4): the gates run on the grouped
    layout, violations map to per-segment findings, and a verification
    round re-reads with the checker's measurements attached. Still
    violated after GROUPED_VERIFY_ROUNDS, the page refuses honestly —
    SegmentPageError names the surviving violations. Returns (final
    segments, token usage)."""
    usage_total: dict[str, Any] = {}
    layout = _grouped_layout(image, segments)
    for _round in range(GROUPED_VERIFY_ROUNDS):
        violations = layout.validate()
        if not violations:
            return segments, usage_total
        findings = findings_fn(layout, violations)
        corrections, dropped, usage = verify_grouped_segments(
            image,
            strips,
            segments,
            work_dir,
            findings=findings,
            model=model,
            base_url=base_url,
            api_key=api_key,
            max_tokens=max_tokens,
            urlopen=urlopen,
        )
        _merge_usage(usage_total, usage)
        for index in sorted(dropped, reverse=True):
            print(
                f"grouping: segment {index} ({str(segments[index]['text'])[:30]!r}) — "
                "the verification found no such text on the page; segment dropped",
                file=sys.stderr,
            )
            del groups[index]
            del segments[index]
        for index, group in corrections.items():
            groups[index] = group
        segments = measure_group_boxes(image, groups, strips)
        layout = _grouped_layout(image, segments)
    violations = layout.validate()
    if violations:
        raise SegmentPageError(
            f"the grouped layout still fails the gates after "
            f"{GROUPED_VERIFY_ROUNDS} verification rounds: {violations[:3]}"
        )
    return segments, usage_total
