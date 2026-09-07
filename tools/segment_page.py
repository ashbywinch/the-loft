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

import json
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from tools.box import overlap
from tools.text import normalize
from tools.vlm import DEFAULT_BASE_URL, transcribe_image_vlm

_SEGMENTS_FORMAT = (
    'Return ONLY JSON: {"segments": [{"text": "the segment verbatim", '
    '"orientation": 0, "box_2d": [x0, y0, x1, y1]}]} — one entry per '
    "segment, in reading order. "
    '"orientation" is the segment\'s reading rotation in degrees: 0 '
    "(upright), 90, 180 or 270 — a margin note running up the page's edge "
    "is 90 or 270, and each of its written lines gets its own entry. "
    '"box_2d" is the segment\'s bounding box in NORMALIZED coordinates '
    "0-1000 (fractions of the image's width and height, times 1000)."
)


def _segments_format(grid: bool) -> str:
    """The response format, in the mode's own units: the grid mode reads
    PIXELS off the drawn ruler, so its template must say box_px
    (2026-09-07: the model followed the template's key, not the grid
    blurb's, and the mismatch refused good reads)."""
    if not grid:
        return _SEGMENTS_FORMAT
    return (
        'Return ONLY JSON: {"segments": [{"text": "the segment verbatim", '
        '"orientation": 0, "box_px": [x0, y0, x1, y1]}]} — one entry per '
        "segment, in reading order. "
        '"orientation" is the segment\'s reading rotation in degrees: 0 '
        "(upright), 90, 180 or 270 — a margin note running up the page's "
        "edge is 90 or 270, and each of its written lines gets its own "
        'entry. "box_px" is the segment\'s bounding box in PIXELS — the '
        "same units the grid is labeled in."
    )


_GRID_SPACING_PX = 100

_GRID_PROMPT = (
    f" A coordinate grid is drawn on the page: thin lines every "
    f"{_GRID_SPACING_PX} pixels, each labeled with its pixel value along "
    "the top and left edges. Report every box in PIXELS read off that "
    'grid as "box_px": [x0, y0, x1, y1] — use the printed labels, and '
    "never guess a coordinate you cannot read from the grid. The box "
    "will be snapped to the ink it encloses, so cover the segment's own "
    "writing completely and stay inside its column."
)

_FENCE = "```"  # the markdown fence the model wraps its JSON in (tools/vlm.py)

_ORIENTATIONS = {0, 90, 180, 270}
_segment_system_cache: dict[bool, str] = {}


def _segment_system(grid: bool) -> str:
    """The system prompt, in the mode's own units (see _segments_format)."""
    if grid not in _segment_system_cache:
        _segment_system_cache[grid] = (
            "You transcribe scanned family documents verbatim and locate "
            "every segment of writing on the page in one pass. Rules: the "
            "document's own words, nothing added, nothing removed — fix "
            "nothing, summarize nothing, invent nothing. Unreadable "
            "words: transcribe your best literal guess. Formatting that "
            "matters — keep the markers, they are content: a word the "
            "writer CROSSED OUT is marked ~~word~~ (double tildes either "
            "side); a word the writer UNDERLINED is marked ~word~ "
            "(single tildes either side, the in-house sibling of the "
            "strike convention — markdown has no standard underline). "
            "For printed text and handwriting alike, at any orientation "
            "— read each block in its own direction and report that "
            "direction. "
            + _segments_format(grid)
            + (_GRID_PROMPT if grid else "")
            + " A segment is the longest run of text on a single line "
            "that belongs together, and the definition is exact — do NOT:"
            " merge consecutive written lines of a paragraph into one "
            "segment (each written line is its own segment);"
            " let a segment cross a column boundary (each column's lines "
            "are their own segments);"
            " merge a margin annotation or side note with the body line "
            "it sits beside (the note is its own segment);"
            " merge text in a different hand into the same segment;"
            " let a box enclose anything but its own segment's writing — "
            "never the neighboring column, never the lines above or "
            "below, never blank card, never past the page edge."
        )
    return _segment_system_cache[grid]


def _draw_coordinate_grid(image: Path, out: Path) -> None:
    """The coordinate ruler drawn ON the page: thin lines every
    GRID_SPACING_PX, labeled with their pixel value along the top and
    left edges. The model reads boxes off the ruler instead of
    imagining the frame — the crop-grid lesson (2026-08-22): never trust
    the model's imagined frame; Set-of-Mark grounding (2023)."""
    with Image.open(image) as im:
        page = im.convert("RGB").copy()
    draw = ImageDraw.Draw(page)
    width, height = page.size
    font = ImageFont.load_default()
    for x in range(0, width + 1, _GRID_SPACING_PX):
        draw.line((x, 0, x, height), fill=(150, 150, 255), width=1)
        if x + 40 < width:
            draw.text((x + 3, 3), str(x), fill=(180, 0, 0), font=font)
    for y in range(0, height + 1, _GRID_SPACING_PX):
        draw.line((0, y, width, y), fill=(150, 150, 255), width=1)
        if y + 20 < height:
            draw.text((3, y + 3), str(y), fill=(180, 0, 0), font=font)
    page.save(out)


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


def _parse_segments(text: str) -> list[dict[str, Any]]:
    """The parsed segments array — the model's JSON, fence-tolerant."""
    segments = _parse_json_object(text, "segment response").get("segments")
    if not isinstance(segments, list):
        raise SegmentPageError(f"the segment response has no segments array: {text[:200]}")
    return segments


def _segment_box(entry: dict[str, Any], grid: bool, width: int, height: int, image: Path) -> list[float]:
    """The segment's pixel box: the normalized 0-1000 contract converted,
    or — in grid mode — grid-read pixels clamped and snapped to the ink
    they enclose."""
    if grid:
        raw_box = entry.get("box_px")
        if not isinstance(raw_box, list) or len(raw_box) != 4:
            raise SegmentPageError(f"a segment's box_px is not [x0, y0, x1, y1]: {entry!r}")
        gx0, gy0, gx1, gy1 = (float(v) for v in raw_box)
        box = [
            max(0.0, min(gx0, width)),
            max(0.0, min(gy0, height)),
            max(0.0, min(gx1, width)),
            max(0.0, min(gy1, height)),
        ]
        return _tighten_to_ink(box, image)
    box_2d = entry.get("box_2d")
    if not isinstance(box_2d, list) or len(box_2d) != 4:
        raise SegmentPageError(f"a segment's box_2d is not [x0, y0, x1, y1]: {entry!r}")
    x0, y0, x1, y1 = (float(v) for v in box_2d)
    return [
        max(0.0, min(x0 * width / 1000, width)),
        max(0.0, min(y0 * height / 1000, height)),
        max(0.0, min(x1 * width / 1000, width)),
        max(0.0, min(y1 * height / 1000, height)),
    ]


def segment_page(  # lucidlint: ignore long-param-list one required argument (image) plus defaulted call options
    image: Path,
    *,
    grid: bool = False,
    model: str = "dynamic/image",
    base_url: str = DEFAULT_BASE_URL,
    api_key: str | None = None,
    max_tokens: int = 64000,
    urlopen: Callable[..., Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """ONE multimodal call: the page's text segments with verbatim text,
    orientation, and pixel boxes. Returns (segments, token usage).

    Each segment: {"label": str, "text": str, "orientation": 0|90|180|270,
    "box": [x0, y0, x1, y1] in ORIGINAL-IMAGE PIXELS}. With ``grid`` the
    page carries a labeled coordinate ruler; the boxes are read off the
    grid in pixels, then snapped to the ink they enclose — reading the
    model's chosen region off a visible scale instead of trusting its
    imagined frame. Raises SegmentPageError on a contract violation —
    fail loudly, never skip."""
    with Image.open(image) as im:
        width, height = im.size
    system = _segment_system(grid)
    call_image = image
    with tempfile.TemporaryDirectory() as tmp:
        if grid:
            call_image = Path(tmp) / "gridded.png"
            _draw_coordinate_grid(image, call_image)
        text, usage = transcribe_image_vlm(
            call_image,
            model=model,
            system=system,
            base_url=base_url,
            api_key=api_key,
            max_tokens=max_tokens,
            urlopen=urlopen,
        )

    segments: list[dict[str, Any]] = []
    for entry in _parse_segments(text):
        if not isinstance(entry, dict):
            raise SegmentPageError(f"segment entry is not an object: {entry!r}")
        seg_text = str(entry.get("text", "")).strip()
        orientation = int(entry.get("orientation", 0) or 0)
        if not seg_text:
            raise SegmentPageError(f"a segment has no text: {entry!r}")
        if orientation not in _ORIENTATIONS:
            raise SegmentPageError(f"segment orientation {orientation} is not 0/90/180/270: {entry!r}")
        box = _segment_box(entry, grid, width, height, image)
        segments.append(
            {
                "label": str(entry.get("label", "line")),
                "text": seg_text,
                "orientation": orientation,
                "box": box,
            }
        )
    return segments, usage


_VERIFY_FORMAT = (
    'Return ONLY JSON: {"corrections": [{"index": 2, "box_px": [x0, y0, x1, y1]}], '
    '"not_present": []} — list ONLY the segments whose rectangle is wrong; a '
    "rectangle that already encloses exactly its own writing must not appear. "
    "box_px is in PIXELS read off the drawn grid."
)

_VERIFY_SYSTEM = (
    "You are checking your own segmentation of a scanned family document. "
    "The image has your reported rectangles drawn on it in red and "
    "numbered, over the same labeled coordinate grid the read used — the "
    "number beside a rectangle is that segment's index. A segment is the "
    "longest run of text on a single line that belongs together: it "
    "never crosses a column boundary, never includes a neighboring "
    "written line, never merges a margin note with the body line beside "
    "it, never mixes hands. Check every numbered rectangle against that "
    "definition and against the page: a rectangle that sits on blank "
    "card, spans two columns, covers neighboring lines, or runs past the "
    "page edge is wrong. For each wrong one, give the corrected box in "
    "grid-read pixels; if a segment's text does not actually appear on "
    "the page, declare it in not_present. The texts are fixed data: "
    "never invent, never re-transcribe. " + _VERIFY_FORMAT
)


def build_verify_prompt(segments: list[dict[str, Any]], width: int, height: int) -> str:
    """The verification pass's user prompt — generated deterministically
    from the reported segments (the same report yields the same bytes)."""
    listed = "\n".join(f"- index {i}: text {str(s.get('text', ''))!r}" for i, s in enumerate(segments))
    return f"The page is {width}x{height} px. Your reported segments:\n{listed}"


def _segment_index(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SegmentPageError(f"the verification's answer has no usable index: {value!r}")
    return int(value)


def _draw_reported_boxes(image: Path, segments: list[dict[str, Any]], path: Path) -> None:
    """The reported boxes drawn on the gridded page in red, numbered —
    the model critiques what it sees, reading corrections off the same
    ruler the read used (Set-of-Mark, 2023)."""
    _draw_coordinate_grid(image, path)
    with Image.open(path) as im:
        annotated = im.copy()
    draw = ImageDraw.Draw(annotated)
    for i, s in enumerate(segments):
        box = s.get("box")
        if not isinstance(box, list) or len(box) != 4:
            continue
        x0, y0, x1, y1 = (int(v) for v in box)
        draw.rectangle((x0, y0, x1, y1), outline=(255, 0, 0), width=3)
        draw.text((x0 + 4, max(0, y0 - 18)), str(i), fill=(255, 0, 0))
    annotated.save(path)


def _apply_verification_corrections(
    answer: dict[str, Any],
    segments: list[dict[str, Any]],
    width: int,
    height: int,
    image: Path,
) -> list[int]:
    """Apply the verification answer to the reported segments in place:
    corrected rectangles (grid-read pixels, snapped to the ink they
    enclose, marked box_source "verified") and the invented segments
    removed — loudly. Returns the dropped indices."""
    corrections: set[int] = set()
    for entry in answer.get("corrections", []):
        if not isinstance(entry, dict):
            raise SegmentPageError(f"the verification's correction is not an object: {entry!r}")
        index = _segment_index(entry.get("index"))
        if not 0 <= index < len(segments) or index in corrections:
            raise SegmentPageError(f"the verification corrected index {index} unasked or twice")
        corrections.add(index)
        raw_box = entry.get("box_px")
        if not isinstance(raw_box, list) or len(raw_box) != 4:
            raise SegmentPageError(f"a corrected box_px is not [x0, y0, x1, y1]: {entry!r}")
        cx0, cy0, cx1, cy1 = (float(v) for v in raw_box)
        segments[index]["box"] = [
            max(0.0, min(cx0, width)),
            max(0.0, min(cy0, height)),
            max(0.0, min(cx1, width)),
            max(0.0, min(cy1, height)),
        ]
        segments[index]["box"] = _tighten_to_ink(segments[index]["box"], image)
        segments[index]["box_source"] = "verified"
    not_present: list[int] = []
    for value in answer.get("not_present", []):
        index = _segment_index(value)
        if not 0 <= index < len(segments) or index in not_present:
            raise SegmentPageError(f"the verification declared index {index} unasked or twice")
        if index in corrections:
            raise SegmentPageError(f"the verification answered index {index} twice")
        not_present.append(index)
    return not_present


def verify_segments(  # lucidlint: ignore long-param-list one required argument (image) plus defaulted call options
    image: Path,
    segments: list[dict[str, Any]],
    *,
    model: str = "dynamic/image",
    base_url: str = DEFAULT_BASE_URL,
    api_key: str | None = None,
    max_tokens: int = 32000,
    urlopen: Callable[..., Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """The visual verification pass (2026-09-07, user: draw the boxes on
    the image and give it back so the model can learn from its
    mistakes). ONE call: the reported boxes drawn on the gridded page in
    red and numbered; the model corrects the wrong rectangles and
    declares the invented segments. Same contract as segment_page — the
    segments come back with corrected boxes (marked box_source
    "verified") and the not-present segments removed. A contract
    violation raises SegmentPageError (the page refuses); the gates,
    never this pass, decide what serves."""
    if not segments:
        return segments, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    with Image.open(image) as im:
        width, height = im.size

    with tempfile.TemporaryDirectory() as tmp:
        annotated = Path(tmp) / "reported.png"
        _draw_reported_boxes(image, segments, annotated)
        text, usage = transcribe_image_vlm(
            annotated,
            model=model,
            system=_VERIFY_SYSTEM,
            user_text=build_verify_prompt(segments, width, height),
            base_url=base_url,
            api_key=api_key,
            max_tokens=max_tokens,
            urlopen=urlopen,
        )

    answer = _parse_json_object(text, "verification response")
    not_present = _apply_verification_corrections(answer, segments, width, height, image)
    for i in not_present:
        print(
            f"segment {i} ({str(segments[i]['text'])[:30]!r}) — the verification "
            "found no such text on the page; segment dropped",
            file=sys.stderr,
        )
    return [s for i, s in enumerate(segments) if i not in set(not_present)], usage


TWO_PASS_ASPECT = 1.2  # taller than this and the model's full-page box placement degrades down the page


def page_needs_two_pass(image: Path) -> bool:
    """Whether the page reads as TWO overlapping halves: portrait sheets
    above the aspect line — the model's full-page box placement degrades
    down a tall page (the crop-grid finding, 2026-08-22; the user,
    2026-09-07: the two-pass read). Small cards read whole, so no tokens
    are spent where the single pass already works (L10)."""
    with Image.open(image) as im:
        width, height = im.size
    return height / width > TWO_PASS_ASPECT


def segment_page_two_pass(  # lucidlint: ignore long-param-list one required argument plus defaults
    image: Path,
    *,
    split_top: float = 0.55,
    split_bottom: float = 0.45,
    model: str = "dynamic/image",
    base_url: str = DEFAULT_BASE_URL,
    api_key: str | None = None,
    max_tokens: int = 64000,
    urlopen: Callable[..., Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """The two-pass read: ONE call per overlapping half — the model's
    geometry is trustworthy when the question is local (the crop-grid
    finding, 2026-08-22) — each half read over its own labeled grid, the
    half's boxes stitched into the page frame, the overlap band deduped
    deterministically: by region overlap, or by equal text when the cut
    shifted a line's box. Same contract as segment_page; the segments'
    order is the top half then the bottom."""
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    halves: list[tuple[int, list[dict[str, Any]]]] = []
    with Image.open(image) as im:
        width, height = im.size
        top_cut = int(height * split_top)
        bottom_cut = int(height * split_bottom)
        with tempfile.TemporaryDirectory() as tmp:
            for name, y0, y1 in (("top", 0, top_cut), ("bottom", bottom_cut, height)):
                half_path = Path(tmp) / f"{name}.png"
                im.crop((0, y0, width, y1)).save(half_path)
                half_segments, usage = segment_page(
                    half_path,
                    grid=True,
                    model=model,
                    base_url=base_url,
                    api_key=api_key,
                    max_tokens=max_tokens,
                    urlopen=urlopen,
                )
                for key in usage_total:
                    usage_total[key] += usage.get(key, 0)
                halves.append((y0, half_segments))

    top_segments = halves[0][1]
    bottom_offset = halves[1][0]
    bottom_segments = [
        {**s, "box": [s["box"][0], s["box"][1] + bottom_offset, s["box"][2], s["box"][3] + bottom_offset]}
        for s in halves[1][1]
    ]
    deduped_bottom = []
    for seg in bottom_segments:
        duplicate = any(
            overlap(seg["box"], top["box"]) >= 0.5
            or (normalize(str(seg["text"])) == normalize(str(top["text"])) and overlap(seg["box"], top["box"]) > 0)
            for top in top_segments
        )
        if not duplicate:
            deduped_bottom.append(seg)
    return top_segments + deduped_bottom, usage_total
