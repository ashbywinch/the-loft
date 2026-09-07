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
with boxes converted to ORIGINAL-IMAGE PIXELS."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image

from tools.box import overlap
from tools.text import normalize
from tools.vlm import DEFAULT_BASE_URL, transcribe_image_vlm

_SEGMENTS_FORMAT = (
    'Return ONLY JSON: {"segments": [{"text": "the line verbatim", '
    '"orientation": 0, "box_2d": [x0, y0, x1, y1]}]} — ONE ENTRY PER LINE '
    "of writing, in reading order (top to bottom; a rotated block's lines "
    "in its own reading direction). Every handwritten or printed line is "
    "its own entry — never merge lines into a paragraph block. "
    '"orientation" is the line\'s reading rotation in degrees: 0 '
    "(upright), 90, 180 or 270 — a margin note running up the page's edge "
    "is 90 or 270, and each of its lines gets its own entry. "
    '"box_2d" is the line\'s bounding box in NORMALIZED coordinates '
    "0-1000 (fractions of the image's width and height, times 1000); it "
    "must enclose every glyph of that line, nothing else."
)

_SEGMENT_SYSTEM = (
    "You transcribe scanned family documents verbatim and locate every "
    "block of text on the page in one pass. Rules: the document's own "
    "words, nothing added, nothing removed — fix nothing, summarize "
    "nothing, invent nothing. Keep the line structure inside each segment. "
    "For printed text and handwriting alike, at any orientation — read "
    "each block in its own direction and report that direction. Unreadable "
    "words: transcribe your best literal guess. Formatting that matters — "
    "keep the markers, they are content: a word the writer CROSSED OUT is "
    "marked ~~word~~ (double tildes either side); a word the writer "
    "UNDERLINED is marked ~word~ (single tildes either side, the in-house "
    "sibling of the strike convention — markdown has no standard underline). " + _SEGMENTS_FORMAT
)

_FENCE = "```"  # the markdown fence the model wraps its JSON in (tools/vlm.py)

_ORIENTATIONS = {0, 90, 180, 270}


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


def segment_page(  # lucidlint: ignore long-param-list one required argument (image) plus defaulted call options
    image: Path,
    *,
    model: str = "dynamic/image",
    base_url: str = DEFAULT_BASE_URL,
    api_key: str | None = None,
    max_tokens: int = 64000,
    urlopen: Callable[..., Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """ONE multimodal call: the page's text segments with verbatim text,
    orientation, and pixel boxes. Returns (segments, token usage).

    Each segment: {"label": str, "text": str, "orientation": 0|90|180|270,
    "box": [x0, y0, x1, y1] in ORIGINAL-IMAGE PIXELS}. Raises
    SegmentPageError on a contract violation — fail loudly, never skip."""
    with Image.open(image) as im:
        width, height = im.size

    text, usage = transcribe_image_vlm(
        image,
        model=model,
        system=_SEGMENT_SYSTEM,
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
        box_2d = entry.get("box_2d")
        orientation = int(entry.get("orientation", 0) or 0)
        if not seg_text:
            raise SegmentPageError(f"a segment has no text: {entry!r}")
        if not isinstance(box_2d, list) or len(box_2d) != 4:
            raise SegmentPageError(f"a segment's box_2d is not [x0, y0, x1, y1]: {entry!r}")
        if orientation not in _ORIENTATIONS:
            raise SegmentPageError(f"segment orientation {orientation} is not 0/90/180/270: {entry!r}")
        x0, y0, x1, y1 = (float(v) for v in box_2d)
        box = [
            max(0.0, min(x0 * width / 1000, width)),
            max(0.0, min(y0 * height / 1000, height)),
            max(0.0, min(x1 * width / 1000, width)),
            max(0.0, min(y1 * height / 1000, height)),
        ]
        segments.append(
            {
                "label": str(entry.get("label", "line")),
                "text": seg_text,
                "orientation": orientation,
                "box": box,
            }
        )
    return segments, usage


_REPAIR_FORMAT = (
    'Return ONLY JSON: {"relocated": [{"index": 16, "box_2d": [x0, y0, x1, y1]}], '
    '"not_present": []} — every index you were given appears in exactly one of '
    "the two lists. box_2d is NORMALIZED 0-1000 and must enclose every glyph "
    "of that line, nothing else."
)

_REPAIR_SYSTEM = (
    "You are correcting one pass of a scanned-document transcription. The "
    "lines listed below were reported on this page, but each one's reported "
    "box landed where the page has no ink. For each line: either locate "
    "that exact text on the page and return its true bounding box, or — if "
    "the text does not actually appear on the page — declare it in "
    "not_present. The text is fixed data: never invent, never "
    "re-transcribe. " + _REPAIR_FORMAT
)


def build_repair_prompt(failures: list[dict[str, Any]], width: int, height: int) -> str:
    """The second pass's user prompt — generated deterministically from
    the first pass's recorded failure facts (the same failure yields the
    same bytes), naming ONLY the failed lines: tokens are not spent
    re-asking about the segments that were already correct (2026-09-07,
    user)."""
    listed = "\n".join(
        f"- index {f['index']}: text {f['text']!r}; rejected box, normalized: "
        f"[{f['box_2d'][0]:.0f}, {f['box_2d'][1]:.0f}, {f['box_2d'][2]:.0f}, {f['box_2d'][3]:.0f}]; "
        f"in pixels: [{f['px'][0]:.0f}, {f['px'][1]:.0f}, {f['px'][2]:.0f}, {f['px'][3]:.0f}]"
        for f in failures
    )
    return (
        f"The page is {width}x{height} px. These reported lines failed the "
        f"ink check — their boxes hold no writing:\n{listed}"
    )


def _repair_index(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SegmentPageError(f"the repair's answer has no usable index: {value!r}")
    return int(value)


def relocate_segments(
    image: Path,
    failures: list[dict[str, Any]],
    *,
    model: str = "dynamic/image",
    base_url: str = DEFAULT_BASE_URL,
    api_key: str | None = None,
    max_tokens: int = 32000,
    urlopen: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """The bounded second pass: ONE call covering only the lines the ink
    gate dropped, prompted by the deterministic repair prompt. Returns
    {"relocated": {index: pixel box}, "not_present": [index, ...]} —
    every failed index answered exactly once. A contract violation
    raises SegmentPageError (the page refuses); the gates, never this
    pass, decide what serves."""
    if not failures:
        return {"relocated": {}, "not_present": []}
    with Image.open(image) as im:
        width, height = im.size

    text, _usage = transcribe_image_vlm(
        image,
        model=model,
        system=_REPAIR_SYSTEM,
        user_text=build_repair_prompt(failures, width, height),
        base_url=base_url,
        api_key=api_key,
        max_tokens=max_tokens,
        urlopen=urlopen,
    )

    answer = _parse_json_object(text, "repair response")
    given = {int(f["index"]) for f in failures}
    relocated: dict[int, list[float]] = {}
    for entry in answer.get("relocated", []):
        if not isinstance(entry, dict):
            raise SegmentPageError(f"the repair's relocated entry is not an object: {entry!r}")
        index = _repair_index(entry.get("index"))
        if index not in given or index in relocated:
            raise SegmentPageError(f"the repair answered index {index} twice or unasked")
        box_2d = entry.get("box_2d")
        if not isinstance(box_2d, list) or len(box_2d) != 4:
            raise SegmentPageError(f"a relocated box_2d is not [x0, y0, x1, y1]: {entry!r}")
        x0, y0, x1, y1 = (float(v) for v in box_2d)
        relocated[index] = [
            max(0.0, min(x0 * width / 1000, width)),
            max(0.0, min(y0 * height / 1000, height)),
            max(0.0, min(x1 * width / 1000, width)),
            max(0.0, min(y1 * height / 1000, height)),
        ]
    not_present: list[int] = []
    for value in answer.get("not_present", []):
        index = _repair_index(value)
        if index not in given or index in relocated or index in not_present:
            raise SegmentPageError(f"the repair answered index {index} twice or unasked")
        not_present.append(index)
    missing = sorted(given - set(relocated) - set(not_present))
    if missing:
        raise SegmentPageError(f"the repair never answered index {missing[0]}")
    return {"relocated": relocated, "not_present": not_present}


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


def segment_page_two_pass(
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
    finding, 2026-08-22) — each half's boxes stitched into the page
    frame, the overlap band deduped deterministically: by region overlap,
    or by equal text when the cut shifted a line's box. Same contract as
    segment_page; the segments' order is the top half then the bottom."""
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
                    half_path, model=model, base_url=base_url, api_key=api_key, max_tokens=max_tokens, urlopen=urlopen
                )
                for key in usage_total:
                    usage_total[key] += int(usage.get(key, 0))
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
