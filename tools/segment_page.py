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
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image

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


def _parse_segments(text: str) -> list[dict[str, Any]]:
    """The parsed segments array — the model's JSON, tolerating a
    code-fence wrapper with a language tag (```json … ```) and locating
    the outermost braces (the house tolerance, tools/vlm.py
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
            raise SegmentPageError(f"the segment response has no JSON: {text[:200]}") from None
        parsed = json.loads(stripped[start : end + 1])
    if isinstance(parsed, dict):
        parsed = parsed.get("segments")
    if not isinstance(parsed, list):
        raise SegmentPageError(f"the segment response has no segments array: {text[:200]}")
    return parsed


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
