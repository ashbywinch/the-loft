"""Thin OpenAI-compatible client for the elicitation model.

Adapted from books_to_anki/src/book_to_flashcards/opencode_translator.py (the
house pattern): urllib-only, retry/backoff on 429/5xx, thinking-disable
fallback, injectable urlopen for tests. The key comes from the environment,
never from code — `LOFT_AI_KEY`, else `OPENCODE_API_KEY`, else opencode's
auth.json (docs/coding-standards.md — secrets are shell-env only).
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, final

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"
DEFAULT_MODEL = "deepseek-v4-flash"

# Providers whose api keys opencode may have stored in its auth.json.
AUTH_JSON_PROVIDER_HINTS = ("opencode-go", "opencode")


class AIClientError(RuntimeError):
    """Raised when the configured model endpoint cannot be used."""


@final
class AIClient:
    """Chat completions against an OpenAI-compatible endpoint (JSON out)."""

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        max_tokens: int = 3000,
        timeout: float = 120.0,
        max_retries: int = 2,
        urlopen: Callable[..., Any] | None = None,
    ) -> None:
        self.model: str = model or os.environ.get("LOFT_AI_MODEL") or DEFAULT_MODEL
        self.base_url: str = (base_url or os.environ.get("LOFT_AI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.api_key: str = api_key or os.environ.get("LOFT_AI_KEY") or find_api_key()
        self.max_tokens: int = max_tokens
        self.timeout: float = timeout
        self.max_retries: int = max_retries
        # injectable for tests
        self._urlopen: Callable[..., Any] = urlopen or urllib.request.urlopen

    def chat(self, system: str, user: str) -> str:
        """One text chat completion call; returns the assistant text."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": self.max_tokens,
            # structured output: the API guarantees a syntactically valid JSON
            # response, eliminating truncated/bare-object responses
            "response_format": {"type": "json_object"},
            # deterministic decoding: structured tasks are far more consistent
            # at temperature 0
            "temperature": 0.0,
        }
        # deepseek-v4-flash otherwise spends its whole output budget on
        # reasoning and returns empty content
        payload["thinking"] = {"type": "disabled"}
        return self._post(payload)

    def _post(self, payload: dict[str, Any]) -> str:
        """Send one chat-completions request with the retry/backoff loop."""
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                # Cloudflare in front of the API rejects the urllib default UA
                "User-Agent": "opencode/1.14.20",
            },
            method="POST",
        )
        delay = 2.0
        attempt = 0
        while True:
            try:
                with self._urlopen(request, timeout=self.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 529):
                    if attempt >= self.max_retries:
                        raise AIClientError(
                            f"model API error {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
                        ) from e
                    time.sleep(delay)
                    delay *= 2
                    attempt += 1
                    continue
                if e.code in (400, 422) and payload.get("thinking"):
                    # model doesn't understand the thinking param — retry
                    # without it; the fallback must NOT consume the retry budget
                    logger.warning(
                        "model %s rejected the thinking param (HTTP %d); retrying without it",
                        self.model,
                        e.code,
                    )
                    payload.pop("thinking")
                    request.data = json.dumps(payload).encode("utf-8")
                    continue
                raise AIClientError(f"model API error {e.code}: {e.read().decode('utf-8', 'replace')[:200]}") from e
            except (urllib.error.URLError, OSError) as e:
                # transport-level failures (connection refused, DNS, read
                # timeouts) are OSErrors, not HTTPErrors; retry with the same
                # backoff
                if attempt >= self.max_retries:
                    raise AIClientError(f"model API request failed: {e!r}") from e
                time.sleep(delay)
                delay *= 2
                attempt += 1
                continue
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise AIClientError(f"unexpected API response: {json.dumps(data)[:300]}") from e
        if not content or not content.strip():
            raise AIClientError("empty response from API")
        return content


def find_api_key() -> str:
    """Return the model API key from the environment or opencode's auth file."""
    env_key = os.environ.get("OPENCODE_API_KEY")
    if env_key:
        return env_key

    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", "")) / "opencode"
    else:
        data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
        base = Path(data_home) / "opencode"
    auth_path = base / "auth.json"
    if auth_path.exists():
        try:
            auth = json.loads(auth_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            auth = {}
        for hint in AUTH_JSON_PROVIDER_HINTS:
            entry = auth.get(hint)
            if isinstance(entry, dict) and entry.get("type") == "api" and entry.get("key"):
                return entry["key"]
    raise AIClientError(
        "No API key found. Set LOFT_AI_KEY or OPENCODE_API_KEY, or log in with `opencode` "
        "(its auth file is read automatically)."
    )


def json_object(text: str) -> dict[str, Any]:
    """Extract one JSON object from model output, tolerating fences/prose."""
    stripped = text.strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end <= start:
        raise AIClientError(f"no JSON object in model output: {text[:200]}")
    try:
        return json.loads(stripped[start : end + 1])
    except ValueError as e:
        raise AIClientError(f"invalid JSON in model output: {e}") from e
