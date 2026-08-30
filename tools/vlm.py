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
import logging
import re
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tools.ai_client import DEFAULT_BASE_URL, find_api_key

logger = logging.getLogger(__name__)

_VLM_READING_RULES = (
    "You transcribe scanned family documents verbatim. Rules: the document's own "
    "words, nothing added, nothing removed — fix nothing, summarize nothing, invent "
    "nothing. Keep the line structure. For printed text and handwriting alike. "
    "Unreadable words: transcribe your best literal guess. "
    "Formatting that matters — keep the markers, they are content: a word the "
    "writer CROSSED OUT is marked ~~word~~ (double tildes either side); a word the "
    "writer UNDERLINED is marked ~word~ (single tildes either side, the in-house "
    "sibling of the strike convention — markdown has no standard underline). "
)

VLM_FORMAT_JSON = (
    'Return ONLY JSON: {"lines": [{"text": "the line verbatim", "box": '
    "[x0, y0, x1, y1]}]} — one entry per line IN READING ORDER, top to bottom. "
    '"box" is the line\'s bounding box in NORMALIZED coordinates 0-1000 '
    "(fractions of the image's width and height, times 1000); it must enclose "
    "every glyph of that line, nothing else."
)

# The no-boxes format (2026-08-25): the ink-column pipeline measures
# geometry from the rec's ink, so its reads need no coordinates. Plain
# text costs a fraction of the tokens — headroom the reasoning budget
# was eating (empty content and truncated '{"lines": ...' echoes were
# both completion-budget failures) — and gives the model no structure
# to fail mid-echoing.
VLM_FORMAT_PLAIN = (
    "Return ONLY the transcription as plain text: one output line per line of "
    "the document, in reading order, top to bottom; skip blank lines. No "
    "coordinates, no JSON, no commentary — just the lines."
)

VLM_SYSTEM = _VLM_READING_RULES + VLM_FORMAT_JSON
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
    request_boxes: bool = True,
) -> str:
    """The verbatim-transcription system prompt plus the context that helps
    the model READ: the family's known names (a familiar name is read
    correctly, not guessed letter-by-letter), the places, the pile's label,
    and the previous page's text for continuity (user, 2026-08-15: "whatever
    useful context we have to help it guess better").

    ``request_boxes=False`` swaps the JSON-and-coordinates format for
    plain text — for callers whose geometry comes from elsewhere (the
    ink-column batch measures from the rec's ink; 2026-08-25)."""
    lines = [_VLM_READING_RULES + (VLM_FORMAT_JSON if request_boxes else VLM_FORMAT_PLAIN)]
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


def transcription_problem(text: str) -> str | None:
    """Why this transcription response cannot build a layout — None when
    it can. The retry ladder's decision (2026-08-25): page-02 emitted the
    identical raw-JSON prefix in two separate runs, and empty content is
    the same completion-budget failure; both are worth a re-read rather
    than letting the gates refuse the page on garbage. Usable: plain
    text, or JSON in the requested structure (parse_transcription_response
    extracts it). Unusable: blank, an unparseable JSON echo (the model
    wrote the requested format instead of transcribing), or parsed JSON
    without the "lines" structure."""
    if not text or not text.strip():
        return "empty response"
    try:
        data = _extract_json(text)
    except VlmError:
        first = text.lstrip()[:1]
        if first in ("{", "["):
            return "unparseable JSON echo"
        return None  # plain text — the fine case
    if isinstance(data, dict) and isinstance(data.get("lines"), list):
        return None  # the model followed the requested structure
    return "JSON without the lines structure"


def transcribe_with_fallbacks(
    image: Path,
    variants: list[dict[str, Any]],
    *,
    usable: Callable[[str], bool] | None = None,
    transcribe: Callable[..., tuple[str, dict[str, int]]] | None = None,
) -> tuple[str, dict[str, int]]:
    """Try each call spec in order; return the first usable response as
    (text, usage). A variant dict passes straight to transcribe_image_vlm
    (model, system, max_tokens, ...). Unusable responses and call errors
    print their reason to stderr and fall through to the next variant.
    When every variant is exhausted: the LAST unusable response comes
    back (the gates refuse it downstream — never a silent drop) unless
    every attempt ERRORED, in which case the last exception re-raises.
    The returned usage sums every attempt's tokens — the honest cost."""
    usable = usable or (lambda text: transcription_problem(text) is None)
    # the injectable seam (2026-08-29): the tests pass a fake instead of
    # monkeypatching the module attribute
    call = transcribe or transcribe_image_vlm
    last_error: Exception | None = None
    last_text: str | None = None
    total_tokens = 0
    name = getattr(image, "name", str(image))
    for attempt, spec in enumerate(variants, start=1):
        try:
            text, usage = call(image, **spec)
        except Exception as exc:
            last_error = exc
            print(f"vlm {name} attempt {attempt}/{len(variants)}: {exc}", file=sys.stderr)
            continue
        total_tokens += int(usage.get("total_tokens", 0) or 0)
        problem = None if usable(text) else (transcription_problem(text) or "failed the caller's checks")
        if problem is None:
            return text, {"total_tokens": total_tokens}
        last_text = text
        print(f"vlm {name} attempt {attempt}/{len(variants)} unusable ({problem}) — falling back", file=sys.stderr)
    if last_text is None and last_error is not None:
        raise last_error
    assert last_text is not None  # exhausted on unusable responses
    return last_text, {"total_tokens": total_tokens}


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
    model: str = "dynamic/image",
    system: str = VLM_SYSTEM,
    user_text: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    api_key: str | None = None,
    timeout: float = 900.0,
    max_tokens: int = 64000,
    urlopen: Callable[..., Any] | None = None,
) -> tuple[str, dict[str, int]]:
    """One multimodal call; returns (text, token usage) — the cost measure.
    ``user_text`` rides the user message alongside the image. ``max_tokens``
    bounds the completion: reasoning models need large headroom for
    location tasks (64000) but a line-crop classification is done with a
    small budget (1000). ``urlopen`` is the test seam (DI, never
    monkeypatch); None uses urllib.request.urlopen."""
    mime = _MIME_BY_SUFFIX.get(image.suffix.lower(), "application/octet-stream")
    data_url = f"data:{mime};base64," + base64.b64encode(image.read_bytes()).decode("ascii")
    user_content: list[dict[str, Any]] = [{"type": "image_url", "image_url": {"url": data_url}}]
    if user_text:
        user_content.append({"type": "text", "text": user_text})
    body = _vision_post(
        base_url=base_url,
        key=api_key or find_api_key(),
        payload={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
            # thinking disabled: transcription is an extraction task, not a
            # judgment — a reasoning model will otherwise spend the whole
            # budget reasoning and return empty content (2026-08-30: the
            # CI's postcard eval). A model that rejects the param gets one
            # retry without it (the AIClient house pattern).
            "thinking": {"type": "disabled"},
        },
        timeout=timeout,
        urlopen=urlopen,
    )
    try:
        choice = body.get("choices", [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        finish_reason = choice.get("finish_reason")
        reasoning = message.get("reasoning") or message.get("reasoning_content") or ""
        usage = dict(body.get("usage", {}))
        # The model's thinking, always captured — a failed call is diagnosable
        # from its trace (2026-08-20: the orientation calls burned 64K tokens
        # of reasoning with zero content; without the reasoning the cause was
        # invisible). Mirrors AIClient.last_reasoning.
        if finish_reason == "length" and not content.strip():
            raise VlmError(
                "vision model produced only reasoning tokens, no content — "
                f"the max_tokens limit was hit. reasoning={len(reasoning)} chars, "
                f"tokens={usage.get('completion_tokens')}. tail: …{reasoning[-300:]}"
            )
        if not content.strip():
            raise VlmError(
                f"vision model returned empty content (finish_reason={finish_reason}); "
                f"reasoning={len(reasoning)} chars, tokens={usage.get('completion_tokens')}. "
                f"tail: …{reasoning[-300:]}"
            )
        text = str(content)
    except (KeyError, IndexError, TypeError) as exc:
        raise VlmError(f"unexpected vision response: {json.dumps(body)[:300]}") from exc
    return text, usage


def _vision_post(
    *,
    base_url: str,
    key: str,
    payload: dict[str, Any],
    timeout: float,
    urlopen: Callable[..., Any] | None,
) -> dict[str, Any]:
    """POST one chat-completions payload. On a 400/422 that the model
    blames on the ``thinking`` param, retry once without it; every other
    failure surfaces as VlmError (the module's contract)."""
    do_open = urlopen or urllib.request.urlopen
    while True:
        try:
            with do_open(
                urllib.request.Request(
                    f"{base_url.rstrip('/')}/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {key}",
                        # Cloudflare in front of the API rejects the urllib default UA
                        "User-Agent": "opencode/1.14.20",
                    },
                    method="POST",
                ),
                timeout=timeout,
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            if e.code in (400, 422) and "thinking" in payload:
                # model doesn't understand the thinking param — retry once
                # without it (mirrors AIClient._post)
                payload.pop("thinking")
                logger.info(
                    "model %s rejected the thinking param (HTTP %d); retrying without it",
                    payload.get("model"),
                    e.code,
                )
                continue
            raise VlmError(f"vision model call failed: HTTP {e.code} - {detail}") from e
        # lucidlint: ignore broad-except the module's contract — every failure surfaces as VlmError
        except Exception as exc:  # network or API errors surface loudly
            raise VlmError(f"vision model call failed: {exc}") from exc


ANGLE_PROMPT = (
    "What is the rotation angle of the text in this image, in degrees "
    "clockwise from upright (0 = the text reads left-to-right with the "
    "image upright)? Reply with just the number."
)


def line_orientation_degrees(crop: Path, *, max_tokens: int = 4000, timeout: float = 120.0) -> float:
    """The exact clockwise angle of one clipped text line, in degrees.
    A single line crop is a trivial task for the model — ~600 total tokens,
    ~6s — vs the full-page location call that burned 64K reasoning tokens
    with zero content (2026-08-20). The exact value disambiguates the
    90-vs-270 flip the rounded question never could."""
    text, _usage = transcribe_image_vlm(
        crop,
        system="You measure text orientation precisely.",
        user_text=ANGLE_PROMPT,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        raise VlmError(f"could not parse an angle from the model's answer: {text[:80]!r}")
    return float(match.group(0)) % 360


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
    "This is a photo of a document page. A previous transcription read the text "
    "below, ONE LINE PER ENTRY. Some lines may run in a different direction to the "
    "page. For EVERY line, give its bounding box and its orientation relative to the "
    "image exactly as shown. If a line cannot be located, give box [0, 0, 0, 0]. "
    "Reply with JSON only: "
    '{"lines": [{"index": <the line number>, "box": [x0, y0, x1, y1], '
    '"degrees": 0|90|180|270}]} — box coordinates are 0-1000 fractions of the '
    "image width and height.\n\nThe transcription:\n"
)


def _parse_report_lines(raw_lines: list[Any]) -> list[dict[str, Any]]:
    """The report's located lines: {index, box (0-1000), degrees} — the
    index keys to the given transcription's line numbers (2026-08-17)."""
    lines: list[dict[str, Any]] = []
    for i, entry in enumerate(raw_lines):
        if not isinstance(entry, dict):
            continue
        if not (isinstance(entry.get("box"), list) and len(entry.get("box")) == 4):
            continue
        if entry.get("degrees") not in (0, 90, 180, 270):
            continue
        lines.append(
            {
                "index": int(entry.get("index")) if isinstance(entry.get("index"), int) else i,
                "box": entry.get("box"),
                "degrees": entry.get("degrees"),
            }
        )
    return lines


def orientation_report(image: Path, text: str | None = None) -> dict[str, Any]:
    """The page's text geometry, structured — used by the layout stage when
    the arbiter's scores suggest more than one direction (PRD VR15).

    v3 (2026-08-17): when the page's transcription is known (``text`` —
    the guess's corrected reading), the report LOCATES that text — the
    model assigns each known line its box and orientation, so the layout
    keeps the authoritative text and a partial report degrades only the
    geometry, never the text (the reproduced fault: the report's own
    transcription varied between calls and could drop whole paragraphs).
    Returns {"orientation_hint": [...], "lines": [{"index", "box",
    "degrees"}]} — the lines keyed to the given text's line numbers."""
    numbered = "\n".join(f"{i}. {line}" for i, line in enumerate((text or "").splitlines()))
    prompt = _ORIENTATION_PROMPT + numbered if text else _ORIENTATION_TRANSCRIBE_PROMPT
    raw, _ = transcribe_image_vlm(
        image,
        system=_ORIENTATION_SYSTEM,
        user_text=prompt,
    )
    try:
        data = _extract_json(raw)
    except VlmError:
        return {}
    if not isinstance(data, dict):
        return {}
    hints = data.get("orientation_hint") if isinstance(data.get("orientation_hint"), list) else []
    hints = [h for h in hints if isinstance(h, dict) and h.get("degrees") in (0, 90, 180, 270)]
    raw_lines = data.get("lines") if isinstance(data.get("lines"), list) else []
    lines = _parse_report_lines(raw_lines)
    return {"orientation_hint": hints, "lines": lines}


_ORIENTATION_TRANSCRIBE_PROMPT = (
    "This is a photo of a document page. Its text may run in more than one direction "
    "(for example a message upright and another block rotated 90 degrees). Transcribe ALL "
    "the text verbatim, ONE LINE PER ENTRY, and for every line give its bounding box and its "
    "orientation relative to the image exactly as shown. Reply with JSON only: "
    '{"lines": [{"index": 0, "text": "<one line>", "box": [x0, y0, x1, y1], "degrees": 0|90|180|270}], '
    '"orientation_hint": [{"region": "<short name>", "degrees": 0|90|180|270, '
    '"approx_box": [x0, y0, x1, y1]}]} — box coordinates are 0-1000 fractions of the '
    "image width and height."
)
