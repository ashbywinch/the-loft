"""A vision-language transcription path — the "standard image model" side of
the cost/accuracy comparison against specialist OCR (Azure Document
Intelligence etc., 2026-08-14).

Sends the page image to a multimodal chat model (the harness's opencode-go
vision role by default) with the verbatim-transcription discipline
(MULTI-DOC-IMPORT-PRD.md R10 / IMPORT-PRD Rule L): the document's own
words, nothing added, nothing removed. Returns the text and the token
usage (the cost measurement).

The specialist-vs-VLM question is empirical: VLMs see the whole page
(layout, callout boxes, mixed print/cursive) but benchmark ~3x worse on
pure handwriting CER; the numbers on the family's own pages decide.
"""

from __future__ import annotations

import base64
import json
import urllib.request
from pathlib import Path
from typing import Any

from tools.ai_client import DEFAULT_BASE_URL, find_api_key

VLM_SYSTEM = (
    "You transcribe scanned family documents verbatim. Rules: the document's own "
    "words, nothing added, nothing removed — fix nothing, summarize nothing, invent "
    "nothing. Keep the line structure. For printed text and handwriting alike. "
    "Unreadable words: transcribe your best literal guess. "
    "Formatting that matters — keep the markers, they are content: a word the "
    "writer CROSSED OUT is marked ~~word~~ (double tildes either side); a word the "
    "writer UNDERLINED is marked ~word~ (single tildes either side, the in-house "
    "sibling of the strike convention — markdown has no standard underline). "
    'Return ONLY JSON: {"lines": [{"text": "the line verbatim", "box": '
    "[x0, y0, x1, y1]}]} — one entry per line IN READING ORDER, top to bottom. "
    '"box" is the line\'s bounding box in NORMALIZED coordinates 0-1000 '
    "(fractions of the image's width and height, times 1000); it must enclose "
    "every glyph of that line, nothing else."
)

# A box smaller than a third of the median line height is degenerate — the
# model's boxes collapse at the page's bottom edge (2026-08-16), so the
# line falls back to the detector's association.
DEGENERATE_BOX_DIVISOR = 3

BOX_COORDINATE_COUNT = 4  # a box is [x0, y0, x1, y1]

_CODE_FENCE = "```"  # the markdown fence the model sometimes wraps its JSON in
_CODE_FENCE_LEN = len(_CODE_FENCE)


def transcription_system_with_context(
    *,
    people: list[str] | None = None,
    places: list[str] | None = None,
    label: str | None = None,
    previous_page: str | None = None,
) -> str:
    """The verbatim-transcription system prompt plus the context that helps
    the model READ: the family's known names (a familiar name is read
    correctly, not guessed letter-by-letter), the places, the pile's label,
    and the previous page's text for continuity (user, 2026-08-15: "whatever
    useful context we have to help it guess better")."""
    lines = [VLM_SYSTEM]
    if people or places:
        lines.append(
            "Context to help you read — known family people: "
            f"{', '.join(people) if people else 'none'}. "
            f"Known places: {', '.join(places) if places else 'none'}. "
            "Use these spellings when the writing matches them."
        )
    if label:
        lines.append(f"This page belongs to the pile: {label!r}.")
    if previous_page:
        lines.append(f"The previous page of this document read:\n---\n{previous_page}\n---")
    return "\n".join(lines)


SELFREPORT_SYSTEM = (
    "You transcribed a scanned handwritten letter. Below is your transcription, "
    "one line per numbered line. Mark the words you are LEAST sure about — where "
    "the handwriting was hard to read — AND any word that does not make sense in "
    "the context of the rest of the document: a word that reads oddly, breaks the "
    "sentence, or looks like a misreading is a great candidate (a transcription "
    "error often survives because the misread word still looks word-like). "
    "Context that helps: known family people: {people}. Known places: {places}. "
    'Return ONLY JSON: {{"unsure": [{{"line": <line number>, "word": "the '
    'word exactly as transcribed"}}]}}. If everything reads confidently, the '
    "list is short or empty."
)


class VlmError(RuntimeError):
    """A vision-model transcription failed."""


_MIME_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


def parse_transcription_response(text: str) -> tuple[str, dict[int, list[float]] | None]:
    """The vision model's transcription response — the JSON format the
    system prompt requests (lines with normalized boxes) or the plain-text
    format (a model that did not follow the instruction). Returns
    (transcription, boxes): the transcription lines joined with newlines
    (the .txt content), and the per-line boxes keyed by the line index in
    NORMALIZED 0-1000 units (the layout pass converts to the image's
    pixels). Empty lines are skipped — the .txt's own split skips them
    too, so the indexes stay aligned. ``boxes`` is None when the model
    returned no usable geometry (the pipeline falls back to the detector's
    association — 2026-08-16: the geometry must come from the model that
    can READ the cursive, not the rec engine that merges/misses its
    lines)."""
    try:
        data = _extract_json(text)
    except VlmError:
        return text.strip(), None
    if not isinstance(data, dict):
        return text.strip(), None
    entries = data.get("lines")
    if not isinstance(entries, list):
        return text.strip(), None
    collected = _collect_line_entries(entries)
    if collected is None:
        return text.strip(), None
    texts, boxes = collected
    return "\n".join(texts), (_drop_degenerate_boxes(boxes) or None)


def _collect_line_entries(entries: list[Any]) -> tuple[list[str], dict[int, list[float]]] | None:
    """The transcription lines and their boxes from the model's "lines"
    array — blank lines carry no box (the .txt's own split skips them too,
    so the indexes stay aligned). None when an entry is not a usable
    object — the caller falls back to the plain-text form."""
    texts: list[str] = []
    boxes: dict[int, list[float]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        t = entry.get("text")
        if not isinstance(t, str) or not t.strip():
            continue  # blank lines carry no box — the .txt split skips them too
        i = len(texts)
        texts.append(t)
        b = entry.get("box")
        if (
            isinstance(b, list)
            and len(b) == BOX_COORDINATE_COUNT
            and all(isinstance(v, (int, float)) and v == v for v in b)
        ):
            boxes[i] = [float(v) for v in b]
    return texts, boxes


def _drop_degenerate_boxes(boxes: dict[int, list[float]]) -> dict[int, list[float]]:
    """Drop the model's degenerate boxes — they COLLAPSE at the page's
    bottom edge (page-05's last four lines came back as a 9px sliver at
    y4633-4642, 2026-08-16): any box smaller than a third of the median
    line height is unusable; the line falls back to the detector's
    association."""
    if not boxes:
        return boxes
    heights = sorted(y1 - y0 for x0, y0, x1, y1 in boxes.values())
    median_h = heights[len(heights) // 2]
    if median_h > 0:
        boxes = {
            i: [x0, y0, x1, y1] for i, (x0, y0, x1, y1) in boxes.items() if y1 - y0 >= median_h / DEGENERATE_BOX_DIVISOR
        }
    return boxes


# (model/system/user_text/base_url/api_key/timeout) — a parameter object would add a type for the one required argument
# lucidlint: ignore long-param-list one required argument (image) plus defaulted call options
def transcribe_image_vlm(
    image: Path,
    *,
    model: str = "mimo-v2.5",
    system: str = VLM_SYSTEM,
    user_text: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    api_key: str | None = None,
    timeout: float = 300.0,
) -> tuple[str, dict[str, int]]:
    """One multimodal call; returns (text, token usage) — the cost measure.
    ``user_text`` rides the user message alongside the image (the
    self-report pass hands the model its own transcription with line
    numbers to review)."""
    key = api_key or find_api_key()
    mime = _MIME_BY_SUFFIX.get(image.suffix.lower(), "application/octet-stream")
    data_url = f"data:{mime};base64," + base64.b64encode(image.read_bytes()).decode("ascii")
    user_content: list[dict[str, Any]] = [{"type": "image_url", "image_url": {"url": data_url}}]
    if user_text:
        user_content.append({"type": "text", "text": user_text})
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0,
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "the-loft/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    # lucidlint: ignore broad-except the module's contract — every failure surfaces as VlmError
    except Exception as exc:  # network or API errors surface loudly
        raise VlmError(f"vision model call failed: {exc}") from exc
    try:
        text = str(body["choices"][0]["message"]["content"])
        usage = dict(body.get("usage", {}))
    except (KeyError, IndexError, TypeError) as exc:
        raise VlmError(f"unexpected vision response: {json.dumps(body)[:300]}") from exc
    return text, usage


def selfreport_words(
    image: Path,
    guess_text: str,
    *,
    people: list[str] | None = None,
    places: list[str] | None = None,
    transcribe: Any = None,
) -> list[dict[str, Any]]:
    """The transcription model's own doubt (user, 2026-08-15): which of its
    words is it least sure of, or that read oddly in context — the flag
    source that replaces the noisy cross-reader agreement. ``transcribe``
    is the injectable seam (transcribe_image_vlm shape). The guess text is
    numbered so the model can cite exact lines; the returned list is
    validated (int lines, string words)."""
    numbered = "\n".join(f"{i + 1}| {line}" for i, line in enumerate(guess_text.split("\n")))
    system = SELFREPORT_SYSTEM.format(
        people=", ".join(people) if people else "none",
        places=", ".join(places) if places else "none",
    )
    call = transcribe if transcribe is not None else transcribe_image_vlm
    text, _usage = call(image, system=system, user_text=f"Your transcription:\n{numbered}")
    data = _extract_json(text)
    unsure = data.get("unsure", []) if isinstance(data, dict) else []
    validated: list[dict[str, Any]] = []
    for entry in unsure:
        if not isinstance(entry, dict):
            continue
        line = entry.get("line")
        word = entry.get("word")
        if isinstance(line, int) and isinstance(word, str) and word.strip():
            validated.append({"line": line, "word": word.strip()})
    return validated


def _extract_json(text: str) -> Any:
    """The model's JSON, tolerating a code-fence wrapper (the probe wrapped
    its answer in ```json … ```)."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1]
        if stripped.endswith(_CODE_FENCE):
            stripped = stripped[:-_CODE_FENCE_LEN]
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                raise VlmError(f"self-report returned no JSON: {text[:300]}") from None
        raise VlmError(f"self-report returned no JSON: {text[:300]}") from None


_ORIENTATION_SYSTEM = "You analyse document layouts precisely. Reply with the requested JSON only."
_ORIENTATION_PROMPT = (
    "This is a photo of a document page. Its text may run in more than one direction "
    "(for example a message upright and another block rotated 90 degrees). Transcribe ALL "
    "the text verbatim, ONE LINE PER ENTRY, and for every line give its bounding box and its "
    "orientation relative to the image exactly as shown. Reply with JSON only: "
    '{"lines": [{"text": "<one line>", "box": [x0, y0, x1, y1], "degrees": 0|90|180|270}], '
    '"orientation_hint": [{"region": "<short name>", "degrees": 0|90|180|270, '
    '"approx_box": [x0, y0, x1, y1]}]} — box coordinates are 0-1000 fractions of the '
    "image width and height."
)


def orientation_report(image: Path) -> dict[str, Any]:
    """The text orientations present on a page, structured — used by the
    layout stage when the arbiter's scores suggest more than one direction
    (PRD VR15). Returns {"orientation_hint": [...], "lines": [...]} — the
    lines carry the model's OWN per-line transcription, box (normalized
    0-1000) and degrees, so the layout anchors every transcribed line to
    the box the model drew around it (VR14, 2026-08-17: every piece of
    text has a box, and the box holds the words it claims)."""
    text, _ = transcribe_image_vlm(
        image,
        system=_ORIENTATION_SYSTEM,
        user_text=_ORIENTATION_PROMPT,
    )
    try:
        data = _extract_json(text)
    except VlmError:
        return {}
    if not isinstance(data, dict):
        return {}
    hints = data.get("orientation_hint") if isinstance(data.get("orientation_hint"), list) else []
    hints = [h for h in hints if isinstance(h, dict) and h.get("degrees") in (0, 90, 180, 270)]
    raw_lines = data.get("lines") if isinstance(data.get("lines"), list) else []
    lines = [
        {
            "text": str(entry.get("text", "")).strip(),
            "box": entry.get("box"),
            "degrees": entry.get("degrees"),
        }
        for entry in raw_lines
        if isinstance(entry, dict)
        and entry.get("text")
        and isinstance(entry.get("box"), list)
        and len(entry.get("box")) == 4
        and entry.get("degrees") in (0, 90, 180, 270)
    ]
    return {"orientation_hint": hints, "lines": lines}
