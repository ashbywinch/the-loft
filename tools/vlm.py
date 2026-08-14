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

from tools.ai_client import DEFAULT_BASE_URL, find_api_key

VLM_SYSTEM = (
    "You transcribe scanned family documents verbatim. Rules: the document's own "
    "words, nothing added, nothing removed — fix nothing, summarize nothing, invent "
    "nothing. Keep the line structure. For printed text and handwriting alike. "
    "Unreadable words: transcribe your best literal guess."
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


def transcribe_image_vlm(
    image: Path,
    *,
    model: str = "mimo-v2.5",
    system: str = VLM_SYSTEM,
    base_url: str = DEFAULT_BASE_URL,
    api_key: str | None = None,
    timeout: float = 300.0,
) -> tuple[str, dict[str, int]]:
    """One multimodal call; returns (text, token usage) — the cost measure."""
    key = api_key or find_api_key()
    mime = _MIME_BY_SUFFIX.get(image.suffix.lower(), "application/octet-stream")
    data_url = f"data:{mime};base64," + base64.b64encode(image.read_bytes()).decode("ascii")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": data_url}}]},
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
    except Exception as exc:  # network or API errors surface loudly
        raise VlmError(f"vision model call failed: {exc}") from exc
    try:
        text = str(body["choices"][0]["message"]["content"])
        usage = dict(body.get("usage", {}))
    except (KeyError, IndexError, TypeError) as exc:
        raise VlmError(f"unexpected vision response: {json.dumps(body)[:300]}") from exc
    return text, usage
