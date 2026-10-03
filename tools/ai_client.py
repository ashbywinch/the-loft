"""Thin OpenAI-compatible client for the elicitation model.

Adapted from books_to_anki/src/book_to_flashcards/opencode_translator.py (the
house pattern): urllib-only, retry/backoff on 429/5xx, thinking-disable
fallback, injectable urlopen for tests. The key comes from the environment,
never from code — `OPENAI_API_KEY` (the Cloudflare gateway token), else
auth.json (docs/coding-standards.md — secrets are shell-env only).
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, final

logger = logging.getLogger(__name__)

# The environment provides the Cloudflare AI Gateway URL and token. The
# OPENAI_BASE_URL convention is the standard (litellm, OpenAI SDK, all
# compatible clients) — the local proxy at :9123/v1 adds repo metadata
# and timeout headers. OPENAI_API_KEY is the Cloudflare gateway token.
# Fallback: the OpenCode endpoint (the legacy direct route).
_DEFAULT_URL = os.environ.get("OPENAI_BASE_URL")
if _DEFAULT_URL:
    DEFAULT_BASE_URL: str = _DEFAULT_URL
else:
    DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"

DEFAULT_MODEL = "dynamic/fallback2"

# Providers whose api keys opencode may have stored in its auth.json.
AUTH_JSON_PROVIDER_HINTS = ("opencode-go", "opencode")


class AIClientError(RuntimeError):
    """Raised when the configured model endpoint cannot be used."""


@final
class AIClient:
    """Chat completions against an OpenAI-compatible endpoint (JSON out)."""

    # — production constructs AIClient() bare or with a single max_tokens override (cli.py, pipeline.py); a config
    # object would be ceremony for one non-default construction site
    # lucidlint: ignore long-param-list the params are optional-with-defaults config plus the urlopen/_sleep test seams
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        max_tokens: int = 3000,
        timeout: float = 120.0,
        max_retries: int = 2,
        urlopen: Callable[..., Any] | None = None,
        _sleep: Callable[[float], None] | None = None,
        # the thinking-token cap for a reasoning call (OpenRouter's
        # normalized reasoning.max_tokens). OFF by default: measured on
        # the CI gateway (Cloudflare->openrouter->deepseek-v4-flash) the
        # param is not honored (a capped call burned ~16k reasoning
        # tokens anyway) AND it reshapes the response — the model's JSON
        # answer lands in the reasoning channel with empty content, the
        # stop-empty cascade. Local litellm honors it (a 400-token budget
        # gave a 135-token deliberation and a normal verdict), so it
        # stays as an opt-in for gateways that handle it.
        reasoning_budget: int | None = None,
    ) -> None:
        self.model: str = model or DEFAULT_MODEL
        self.base_url: str = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key: str = (
            api_key
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("CLOUDFLARE_AIGATEWAY_TOKEN")
            or find_api_key()
        )
        self.max_tokens: int = max_tokens
        self.timeout: float = timeout
        self.max_retries: int = max_retries
        self.reasoning_budget: int | None = reasoning_budget
        # the last response's reasoning — captured so a failed judgment is
        # diagnosable from its trace (user: "we should be able
        # to read the model's thought process to understand why it got it
        # wrong")
        self.last_reasoning: str = ""
        # injectable for tests
        self._urlopen: Callable[..., Any] = urlopen or urllib.request.urlopen
        self._sleep: Callable[[float], None] = _sleep or time.sleep

    def chat(self, system: str, user: str, *, thinking: bool = False) -> str:
        """One text chat completion call; returns the assistant text.

        *thinking* enables the model's reasoning: the review judgments
        flipped run to run at temperature 0 with it disabled, and the
        reasoning is captured in ``last_reasoning`` so a wrong judgment is
        diagnosable. Thinking needs output headroom — deepseek-v4-flash at
        3000 tokens spent the whole budget reasoning and returned empty
        content."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # thinking needs room for the reasoning plus the JSON verdict;
            # only used tokens are billed, so the headroom is free when the
            # model stops early. The length-empty burn is a deliberation
            # STALL, not deep thinking: the model circles the same decisions
            # until the budget runs out with no verdict (measured: 16,000
            # reasoning tokens, content a single space; the captured thinking
            # re-reads one instruction line ~27 times). The burn retry below
            # takes a fresh sample — the reasoning budget alone cannot bound
            # the circling on every gateway (the CI gateway ignores
            # reasoning.max_tokens).
            "max_tokens": 16000 if thinking else self.max_tokens,
            # reduces brittle failure modes caused by deterministic
            # repetition loops" (arXiv:2602.03664). A small temperature
            # breaks the attractor and gives the burn retry a genuinely
            # different sample (arXiv:2502.08235's sample-and-select); the
            # evals evaluate output properties, not draws, so this does not
            # loosen the gates. The non-thinking (direct-answer) path stays
            # at 0 for the deterministic fallback.
            "temperature": 0.3 if thinking else 0.0,
            # structured output: the API guarantees a syntactically valid JSON
            # response, eliminating truncated/bare-object responses
            "response_format": {"type": "json_object"},
            # the model thinks its way to the structured verdict (see the
            # docstring); a model that rejects the param falls back below
            # (the 400/422 retry)
            "thinking": {"type": "enabled" if thinking else "disabled"},
        }
        # the thinking-token cap — only when explicitly configured: the
        # CI gateway ignores the cap and reshapes the response (the JSON
        # lands in reasoning, content empty — the stop-empty cascade),
        # so the default is OFF; the local litellm path honors it.
        if thinking and self.reasoning_budget is not None:
            payload["reasoning"] = {"max_tokens": self.reasoning_budget}
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
        content = ""  # the completion content — set per attempt, used by the empty-path check
        finish_reason = ""  # the response's finish_reason — set per attempt, used by the empty-path log
        burn_retried = False  # the fresh-sample rescue fires ONCE — a second burn is a persistent stall
        while True:
            try:
                with self._urlopen(request, timeout=self.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                try:
                    choice = data["choices"][0]
                    message = choice.get("message") if isinstance(choice, dict) else None
                    # a choice can be a dict whose message is a non-dict (a string) —
                    # .get on it would raise the uncaught AttributeError the null-
                    # choice guard was meant to prevent
                    message = message if isinstance(message, dict) else {}
                    content = message.get("content") or ""
                    # why the completion is empty is the diagnostic, not the
                    # emptiness: finish_reason "length" with no content means
                    # the model spent its whole output budget reasoning.
                    finish_reason = str(choice.get("finish_reason") or "") if isinstance(choice, dict) else ""
                except (KeyError, IndexError, TypeError) as e:
                    raise AIClientError(f"unexpected API response: {json.dumps(data)[:300]}") from e
                self.last_reasoning = str(message.get("reasoning_content") or message.get("reasoning") or "")
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 529):
                    if attempt >= self.max_retries:
                        raise AIClientError(
                            f"model API error {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
                        ) from e
                    self._sleep(delay)
                    delay *= 2
                    attempt += 1
                    continue
                if e.code in (400, 422) and (payload.get("thinking") or payload.get("reasoning")):
                    # model/endpoint doesn't understand the reasoning params —
                    # retry without them; the fallback must NOT consume the
                    # retry budget
                    logger.warning(
                        "model %s rejected the reasoning params (HTTP %d); retrying without them",
                        self.model,
                        e.code,
                    )
                    payload.pop("thinking", None)
                    payload.pop("reasoning", None)
                    # temperature follows the thinking state too: a rejected
                    # thinking param must not leave the retry running at the
                    # thinking 0.3 — it is a non-thinking call at 0.0
                    payload["temperature"] = 0.0
                    request.data = json.dumps(payload).encode("utf-8")
                    continue
            if content and content.strip():
                return content
            thinking_enabled = bool((payload.get("thinking") or {}).get("type") == "enabled")
            if thinking_enabled and finish_reason == "length" and not burn_retried:
                # the completion is a deliberation stall: the model circled
                # its decisions and spent the whole budget reasoning without
                # a verdict (measured: 16,000 reasoning tokens, content a
                # single space; the captured thinking re-reads one
                # instruction line ~27 times). Decoding-side controls alone
                # cannot stop the circling (arXiv:2602.14798); the fix that
                # works keeps the reasoning and takes a FRESH sample
                # (arXiv:2502.08235's sample-and-select). The first pass at
                # this rescue added a tighter reasoning budget and a
                # conclude-now nudge — measured on the CI gateway: the
                # budget was ignored (the retry still burned the full
                # budget) and the nudge made the model wrap up INSIDE its
                # thinking and emit no content (finish=stop, 273 reasoning
                # chars, empty content — the budget-forcing failure mode).
                # Thinking is never disabled and the prompt is never
                # rewritten: only the sample changes.
                logger.warning(
                    "chat: thinking burned the output budget (finish_reason=length, %d reasoning tokens) — "
                    "retrying on a fresh sample",
                    len(self.last_reasoning),
                )
                # a different draw: the stall is stochastic, not a
                # deterministic attractor (the temperature-0 loop class is
                # already gone) — the new sample often concludes (2502.08235)
                payload["temperature"] = 0.5
                burn_retried = True
                request.data = json.dumps(payload).encode("utf-8")
                continue
            if (
                not content.strip()
                and finish_reason == "stop"
                and thinking_enabled
                and self._reasoning_is_answer(self.last_reasoning)
            ):
                # the provider put the structured answer in the reasoning
                # channel and produced zero content — the captured reasoning
                # IS the completion (measured: deepseek-v4-flash via the CF
                # gateway returns the verdict JSON in 'reasoning' with
                # content=="" on some draws; callers extract the JSON).
                # Gated on a parseable answer: deliberation prose with no
                # JSON is a genuine failure and must keep the retry path
                # (review-bot finding on PR #62).
                logger.warning(
                    "chat: empty content with finish_reason=stop — the reasoning holds the answer; "
                    "recovering it (reasoning_len=%d)",
                    len(self.last_reasoning),
                )
                return self.last_reasoning
            # a 200 with no content is a transient provider failure, not an
            # answer. Log the response's actual signals so the failure mode
            # is observable, then retry with the same backoff as a 5xx;
            # exhaust the budget before failing.
            logger.warning(
                "chat: empty completion (finish_reason=%s, content_len=%d, reasoning_len=%d) — retrying",
                finish_reason or "n/a",
                len(content),
                len(self.last_reasoning),
            )
            if attempt >= self.max_retries:
                raise AIClientError(f"empty response from API (finish_reason={finish_reason or 'n/a'})")
            self._sleep(delay)
            delay *= 2
            attempt += 1

    def _reasoning_is_answer(self, reasoning: str) -> bool:
        """True when the reasoning channel holds the structured answer — a
        parseable JSON object — rather than deliberation prose. The
        stop-empty recovery must not substitute prose for a failed
        completion (review-bot finding on PR #62)."""
        try:
            json_object(reasoning)
        except AIClientError:
            return False
        return True


def find_api_key(_env: Mapping[str, str] | None = None, _home: Path | None = None) -> str:
    """Return the model API key from the environment or opencode's auth file.
    ``_env``/``_home`` are the injectable seams for tests (DI, never
    monkeypatch); None falls back to the process environment.

    Priority: OPENAI_API_KEY (Cloudflare gateway token),
    CLOUDFLARE_AIGATEWAY_TOKEN, OPENCODE_API_KEY (opencode's legacy env),
    or opencode's auth.json.
    """
    env = os.environ if _env is None else _env
    home = Path.home() if _home is None else _home
    for var in ("OPENAI_API_KEY", "CLOUDFLARE_AIGATEWAY_TOKEN", "OPENCODE_API_KEY"):
        value = env.get(var)
        if value:
            return value

    if os.name == "nt":
        base = Path(env.get("APPDATA", "")) / "opencode"
    else:
        data_home = env.get("XDG_DATA_HOME") or str(home / ".local/share")
        base = Path(data_home) / "opencode"
    auth_path = base / "auth.json"
    if auth_path.exists():
        try:
            auth = json.loads(auth_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise AIClientError(f"cannot read the opencode auth file {auth_path}: {e}") from e
        for hint in AUTH_JSON_PROVIDER_HINTS:
            entry = auth.get(hint)
            if isinstance(entry, dict) and entry.get("type") == "api" and entry.get("key"):
                return entry["key"]
    raise AIClientError(
        "No API key found. Set OPENAI_API_KEY or OPENCODE_API_KEY, or log in with `opencode` "
        "(its auth file is read automatically)."
    )


def json_object(text: str) -> dict[str, Any]:
    """Extract the LAST complete JSON object from model output, tolerating
    fences, prose, and MULTIPLE objects — a reasoning preamble followed by
    the verdict is the shape the model emits. Scanning with raw_decode
    skips a malformed brace instead of failing."""
    decoder = json.JSONDecoder()
    stripped = text.strip()
    found: dict[str, Any] | None = None
    idx = 0
    while idx < len(stripped):
        if stripped[idx] != "{":
            idx += 1
            continue
        try:
            obj, end = decoder.raw_decode(stripped, idx)
        except json.JSONDecodeError:
            idx += 1
            continue
        if isinstance(obj, dict):
            found = obj
        idx = end
    if found is None:
        raise AIClientError(f"no JSON object in model output: {text[:200]}")
    return found
