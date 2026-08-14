"""Azure Document Intelligence Read — the specialist OCR comparison point
(2026-08-14). Same seam as tools/vlm.py: page image in, verbatim text out,
token/page cost out. Requires a Document Intelligence resource (free F0
tier: 500 pages/month): the endpoint + key go in the environment as
LOFT_AZURE_ENDPOINT and LOFT_AZURE_KEY (never in code).

The Read model extracts text (printed AND handwriting) in reading order
across the whole page — the mixed-form and callout-box cases it was
benchmarked on (8.67% WER handwriting, strong mixed handling).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

API_VERSION = "2024-11-30"


class AzureOcrError(RuntimeError):
    """The Azure Read call failed; the message is the plain-language line."""


def transcribe_read(
    image: Path,
    *,
    endpoint: str | None = None,
    key: str | None = None,
    timeout: float = 120.0,
) -> tuple[str, dict[str, Any]]:
    """Read the page's text (printed + handwriting) via prebuilt-read.

    Returns (text, meta) — meta carries the page's line count and word
    count for the cost/accuracy comparison.
    """
    endpoint = endpoint or os.environ.get("LOFT_AZURE_ENDPOINT", "")
    key = key or os.environ.get("LOFT_AZURE_KEY", "")
    if not endpoint or not key:
        raise AzureOcrError(
            "LOFT_AZURE_ENDPOINT / LOFT_AZURE_KEY not set — create the Document Intelligence resource first"
        )

    def _request(method: str, url: str, body: bytes | None = None, ctype: str | None = None) -> dict[str, Any]:
        headers = {"Ocp-Apim-Subscription-Key": key}
        if ctype:
            headers["Content-Type"] = ctype
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raise AzureOcrError(
                f"Azure Read returned HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}"
            ) from exc

    analyze_url = (
        f"{endpoint.rstrip('/')}/documentintelligence/documentModels/prebuilt-read:analyze?api-version={API_VERSION}"
    )
    response = _request("POST", analyze_url, image.read_bytes(), "application/octet-stream")
    operation = response.get("operation-location")
    if not operation:
        raise AzureOcrError(f"Azure analyze did not return an operation-location: {str(response)[:200]}")

    deadline = time.time() + timeout
    while time.time() < deadline:
        result = _request("GET", operation)
        status = result.get("status")
        if status == "succeeded":
            break
        if status == "failed":
            raise AzureOcrError(f"Azure Read failed: {str(result.get('error', result))[:300]}")
        time.sleep(2.0)
    else:
        raise AzureOcrError("Azure Read timed out waiting for the analysis")

    content = str(result.get("analyzeResult", {}).get("content", ""))
    words = sum(len(page.get("words", [])) for page in result.get("analyzeResult", {}).get("pages", []))
    return content, {"words": words, "pages": len(result.get("analyzeResult", {}).get("pages", []))}
