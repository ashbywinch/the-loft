"""Thin OpenAI-compatible client for the elicitation model.

Adapted from books_to_anki/src/book_to_flashcards/opencode_translator.py (the
house pattern): urllib-only, retry/backoff on 429/5xx, reasoning-param
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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, final

from pipeline.model.backoff import Backoff
from pipeline.model.chat_message import ChatMessage
from pipeline.model.chat_request import ChatRequest
from pipeline.model.config import ModelConfig
from pipeline.model.http_headers import HttpHeaders
from pipeline.model.reasoning import Reasoning

logger = logging.getLogger(__name__)


class AIClientError(RuntimeError):
    """Raised when the configured model endpoint cannot be used."""


@dataclass(frozen=True)
class _Reply:
    """A response as the endpoint sent it: the assistant message, parsed, and
    the whole body the response id and usage record live in."""

    message: Mapping[str, Any]
    body: Mapping[str, Any]


@dataclass(frozen=True)
class Attempt:
    """One send's 200 response, parsed once by ``_read_attempt`` into the
    single value the retry loop decides on: the reply, its reasoning, the
    content, why the model stopped, the usage record, and the gateway's cache
    verdict.

    Every field a decision reads is here, so no branch of the loop reads a
    value another branch assigned."""

    reply: _Reply
    reasoning: Reasoning
    content: str
    finish_reason: str
    usage: dict[str, Any]
    cache_status: str


@dataclass(frozen=True)
class _Rejected:
    """A send the endpoint refused at the transport: the HTTP error, handled
    by the same decision function as an attempt."""

    error: urllib.error.HTTPError


# The outcome of one send: the parsed attempt, or the refusal.
_Outcome = Attempt | _Rejected


@dataclass(frozen=True)
class _Step:
    """What the loop does with one send: the one decision, and the values
    carrying it out. ``kind`` names the case; ``payload`` is the request the
    next send uses; ``wait`` says the step takes a backoff slot; ``answer`` is
    the text to return; ``error``/``cause`` the failure to raise;
    ``burn_retried`` is the fresh-sample rescue's flag for the next
    iteration."""

    kind: Literal["return", "salvage", "burn", "retry", "ladder", "raise"]
    payload: ChatRequest
    wait: bool = False
    answer: str = ""
    error: str = ""
    cause: BaseException | None = None
    burn_retried: bool = False


# The statuses that mean "the endpoint is busy, try again" and the statuses
# that mean "this endpoint does not understand the request's reasoning params"
# — named, so the ladder below reads as its rule.
_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 529})
_REASONING_PARAM_STATUSES = frozenset({400, 422})


def _api_error(error: urllib.error.HTTPError) -> str:
    """The failure message for one refused send: the status and the body the
    endpoint sent with it (a bad model name and an expired key both live
    there)."""
    return f"model API error {error.code}: {error.read().decode('utf-8', 'replace')[:200]}"


def _read_attempt(body: Mapping[str, Any], headers: Mapping[str, str], requested: bool) -> Attempt:
    """Parse one 200 response into the ``Attempt`` the loop decides on.

    The content, the stop reason, the reasoning text (either channel a
    provider uses — the gateway sends ``reasoning``, some providers
    ``reasoning_content``), the usage record and the gateway's cache verdict
    are read here, once, so every later question is a field on the value.

    A body without a choice is the one malformed shape: it fails here, with
    the body in the error, never as an AttributeError from a later reader.
    A null (or non-dict) choice is not malformed — it is an empty completion
    and keeps the empty-content path."""
    try:
        choice = body["choices"][0]
    except (KeyError, IndexError, TypeError) as e:
        raise AIClientError(f"unexpected API response: {json.dumps(body)[:300]}") from e
    choice = choice if isinstance(choice, dict) else {}
    message_field = choice.get("message")
    message = message_field if isinstance(message_field, dict) else {}
    raw_reasoning = message.get("reasoning")
    if raw_reasoning is None:
        raw_reasoning = message.get("reasoning_content")
    usage_field = body.get("usage")
    return Attempt(
        reply=_Reply(message=message, body=body),
        reasoning=Reasoning(enabled=requested, text=str(raw_reasoning or "")),
        content=message.get("content") or "",
        finish_reason=str(choice.get("finish_reason") or ""),
        usage=usage_field if isinstance(usage_field, dict) else {},
        cache_status=headers.get("cf-aig-cache-status", "n/a"),
    )


@final
class AIClient:
    # The endpoint and the model aliases live in ModelConfig — the one file
    # that names the models. This is the Cloudflare AI Gateway
    # (OPENAI_BASE_URL from the operator's environment; OPENAI_API_KEY is the
    # gateway token).
    DEFAULT_BASE_URL: str = ModelConfig.GATEWAY_BASE_URL
    DEFAULT_MODEL = ModelConfig.CHAT_MODEL

    # Providers whose api keys opencode may have stored in its auth.json.
    AUTH_JSON_PROVIDER_HINTS = ("opencode-go", "opencode")

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
        # the reasoning-token cap for a reasoning call (OpenRouter's
        # normalized reasoning.max_tokens). OFF by default: measured on
        # the CI gateway (Cloudflare->openrouter->deepseek-v4-flash) the
        # param is not honored (a capped call burned ~16k reasoning
        # tokens anyway) AND it reshapes the response — the model's JSON
        # answer lands in the reasoning channel with empty content, the
        # stop-empty cascade. Local litellm honors it (a 400-token budget
        # gave a 135-token deliberation and a normal verdict), so it
        # stays as an opt-in for gateways that handle it.
        reasoning_budget: int | None = None,
        # A measurement must not be served from the gateway's cache: an
        # identical body gets the identical cached answer, which makes a
        # second "independent" run a replay of the first (measured: one run
        # re-used every response id of the previous). Evals build the client
        # with fresh=True; production keeps the cache, where an identical
        # question deserves its identical answer.
        fresh: bool = False,
    ) -> None:
        self.model: str = model or AIClient.DEFAULT_MODEL
        self.base_url: str = (base_url or AIClient.DEFAULT_BASE_URL).rstrip("/")
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
        self._fresh: bool = fresh
        # the last response's reasoning — captured so a failed judgment is
        # diagnosable from its trace (user: "we should be able
        # to read the model's thought process to understand why it got it
        # wrong"). ``last_reasoning`` is the compatibility view of its text.
        self._last_reasoning: Reasoning = Reasoning(enabled=False)
        # injectable for tests
        self._urlopen: Callable[..., Any] = urlopen or urllib.request.urlopen
        self._sleep: Callable[[float], None] = _sleep or time.sleep

    @property
    def last_reasoning(self) -> str:
        """The last reply's deliberation text (``""`` when it carried none).
        Kept as the compatibility view of the recorded attempt's reasoning —
        the trace and the evals read it."""
        return self._last_reasoning.text

    def chat(self, system: str, user: str, *, reasoning: bool = False) -> str:
        """One text chat completion call; returns the assistant text.

        *reasoning* enables the model's reasoning: the review judgments
        flipped run to run at temperature 0 with it disabled, and the
        reasoning is captured in ``last_reasoning`` so a wrong judgment is
        diagnosable. Thinking needs output headroom — deepseek-v4-flash at
        3000 tokens spent the whole budget reasoning and returned empty
        content."""
        # the request's reasoning state — the budget rides it only when the
        # switch is on; Reasoning refuses a cap on a disabled request
        request_reasoning = Reasoning(
            enabled=reasoning,
            budget=self.reasoning_budget if reasoning else None,
        )
        request = ChatRequest(
            model=self.model,
            messages=[
                ChatMessage(role="system", content=system),
                ChatMessage(role="user", content=user),
            ],
            # reasoning needs room for the reasoning plus the JSON verdict;
            # only used tokens are billed, so the headroom is free when the
            # model stops early. The length-empty burn is a deliberation
            # STALL, not deep reasoning: the model circles the same decisions
            # until the budget runs out with no verdict (measured: 16,000
            # reasoning tokens, content a single space; the captured reasoning
            # re-reads one instruction line ~27 times). The burn retry below
            # takes a fresh sample — the reasoning budget alone cannot bound
            # the circling on every gateway (the CI gateway ignores
            # reasoning.max_tokens).
            max_tokens=16000 if reasoning else self.max_tokens,
            # reduces brittle failure modes caused by deterministic
            # repetition loops" (arXiv:2602.03664). A small temperature
            # breaks the attractor and gives the burn retry a genuinely
            # different sample (arXiv:2502.08235's sample-and-select); the
            # evals evaluate output properties, not draws, so this does not
            # loosen the gates. The non-reasoning (direct-answer) path stays
            # at 0 for the deterministic fallback.
            temperature=0.3 if reasoning else 0.0,
            # the model thinks its way to the structured verdict (see the
            # docstring); a model that rejects the param falls back below
            # (the 400/422 retry)
            reasoning=request_reasoning,
            # structured output: the API guarantees a syntactically valid JSON
            # response, eliminating truncated/bare-object responses
            json_response=True,
        )
        return self._post(request)

    def _post(self, payload: ChatRequest) -> str:
        """Send one chat-completions request: send, read the attempt, act on
        the one decision it yields, repeat.

        The retry rules — the backoff budget, the parameter ladder, the
        fresh-sample burn rescue, the stop-empty salvage — are branches of
        ``_next_step``, each with the case it handles; this loop only carries
        out the step that function returns."""
        backoff = Backoff(delay=2.0, attempt=0)
        burn_retried = False  # the fresh-sample rescue fires ONCE — a second burn is a persistent stall
        while True:
            outcome = self._send(payload, skip_cache=self._fresh or backoff.attempt > 0)
            step = self._next_step(outcome, payload, attempts_made=backoff.attempt, burn_retried=burn_retried)
            if step.kind in ("return", "salvage"):
                return step.answer
            if step.kind == "raise":
                raise AIClientError(step.error) from step.cause
            payload = step.payload
            burn_retried = step.burn_retried
            if step.wait:
                backoff = backoff.advance(self._sleep)

    def _send(self, payload: ChatRequest, *, skip_cache: bool) -> _Outcome:
        """Send one request and read its outcome: a 200 parsed into the
        ``Attempt`` the loop decides on (and recorded for ``last_reasoning``),
        or the endpoint's refusal.

        The request is built per attempt, because a RETRY MUST BE A NEW
        SAMPLE. The gateway caches a completion by request body: re-sending
        the identical body replays the answer that just failed. Measured on an
        empty completion — three attempts, one response id,
        cf-aig-cache-status: HIT, byte-identical reasoning each time — so the
        retry could never rescue it. The VLM path skips the cache outright (a
        cached measurement is not a measurement); here the first attempt may
        cache, and only a retry must not."""
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload.to_dict()).encode("utf-8"),
            headers=HttpHeaders(
                content_type="application/json",
                authorization=f"Bearer {self.api_key}",
                user_agent=HttpHeaders.USER_AGENT,
                skip_gateway_cache=skip_cache,
            ).to_dict(),
            method="POST",
        )
        try:
            with self._urlopen(request, timeout=self.timeout) as response:
                attempt = _read_attempt(
                    json.loads(response.read().decode("utf-8")),
                    response.headers,
                    payload.reasoning is not None and payload.reasoning.enabled,
                )
        except urllib.error.HTTPError as e:
            return _Rejected(error=e)
        self._record_reasoning(attempt)
        return attempt

    def _next_step(self, outcome: _Outcome, payload: ChatRequest, *, attempts_made: int, burn_retried: bool) -> _Step:
        """What the loop does with one send — the only place a case is decided.

        The cases, one branch each:

        * refusal, transient status (429/5xx) with retry budget left — retry
          on the backoff, because the endpoint is busy, not broken;
        * refusal, transient status, budget exhausted — raise with the body,
          because a status that persists is not transient;
        * refusal, 400/422 to a request carrying reasoning — retry once
          without the reasoning params and at the non-reasoning temperature,
          taking no backoff slot, because the endpoint does not understand
          them (the schema ladder) and that is not a failure;
        * refusal, any other status — raise with the body, because a bad
          model name or an expired key must never read as an empty completion;
        * an attempt with content — return it;
        * an attempt whose reasoning burned the whole output budget
          (``length``) with the rescue unspent — retry once at a warmer
          temperature with reasoning kept, because a deliberation stall needs
          a fresh sample, never a rewritten prompt;
        * an attempt with empty content whose stop/error reasoning IS the
          structured answer — return the reasoning, because the provider put
          the answer in the reasoning channel;
        * any other empty attempt — retry on the backoff while the budget
          lasts, else raise, because a 200 with no content is a transient
          provider failure.
        """
        if isinstance(outcome, _Rejected):
            error = outcome.error
            if error.code in _TRANSIENT_STATUSES:
                if attempts_made >= self.max_retries:
                    return _Step(kind="raise", payload=payload, error=_api_error(error), cause=error)
                return _Step(kind="retry", payload=payload, wait=True, burn_retried=burn_retried)
            if error.code in _REASONING_PARAM_STATUSES and payload.reasoning is not None:
                logger.warning(
                    "model %s rejected the reasoning params (HTTP %d); retrying without them",
                    self.model,
                    error.code,
                )
                # temperature follows the reasoning state too: a rejected
                # reasoning param must not leave the retry running at the
                # reasoning 0.3 — it is a non-reasoning call at 0.0
                return _Step(
                    kind="ladder",
                    payload=replace(payload, reasoning=None, temperature=0.0),
                    burn_retried=burn_retried,
                )
            # any other status is a HARD client error — a bad model name, an
            # expired key, a wrong endpoint. Report it with the body, once.
            # Letting it fall through to the empty-completion path read a 400
            # "Invalid model name" as "empty response from API
            # (finish_reason=n/a)" and retried it as if transient: the real
            # failure stayed invisible for a whole session (2026-10-19).
            return _Step(kind="raise", payload=payload, error=_api_error(error), cause=error)

        attempt = outcome
        if attempt.content.strip():
            return _Step(kind="return", payload=payload, answer=attempt.content, burn_retried=burn_retried)
        if attempt.reasoning.enabled and attempt.finish_reason == "length" and not burn_retried:
            # the completion is a deliberation stall: the model circled its
            # decisions and spent the whole budget reasoning without a verdict
            # (measured: 16,000 reasoning tokens, content a single space; the
            # captured reasoning re-reads one instruction line ~27 times).
            # Decoding-side controls alone cannot stop the circling
            # (arXiv:2602.14798); the fix that works keeps the reasoning and
            # takes a FRESH sample (arXiv:2502.08235's sample-and-select). The
            # first pass at this rescue added a tighter reasoning budget and a
            # conclude-now nudge — measured on the CI gateway: the budget was
            # ignored (the retry still burned the full budget) and the nudge
            # made the model wrap up INSIDE its reasoning and emit no content
            # (finish=stop, 273 reasoning chars, empty content — the
            # budget-forcing failure mode). Thinking is never disabled and the
            # prompt is never rewritten: only the sample changes.
            logger.warning(
                "chat: reasoning burned the output budget (finish_reason=length, %d reasoning tokens) — "
                "retrying on a fresh sample",
                len(attempt.reasoning.text),
            )
            # a different draw: the stall is stochastic, not a deterministic
            # attractor (the temperature-0 loop class is already gone) — the
            # new sample often concludes (2502.08235)
            return _Step(kind="burn", payload=replace(payload, temperature=0.5), burn_retried=True)
        if attempt.finish_reason in ("stop", "error"):
            # the provider put the structured answer in the reasoning channel
            # and produced zero content — the reasoning IS the completion.
            # Measured on the CI gateway, the verdict JSON lands in
            # 'reasoning' with content=="" both on stop draws and on
            # stream-failed completions (finish_reason=error, 9,852 reasoning
            # chars, no content), which otherwise retry into the same provider
            # hiccup. ``_salvage`` decides: a parseable answer is recovered,
            # deliberation prose (or no reasoning at all) is a genuine failure
            # and keeps the retry path (review-bot finding on PR #62), and a
            # non-reasoning call never salvages.
            salvaged = self._salvage(attempt.reasoning)
            if salvaged is not None:
                logger.warning(
                    "chat: empty content with finish_reason=%s — the reasoning holds the answer; "
                    "recovering it (reasoning_len=%d)",
                    attempt.finish_reason,
                    len(salvaged),
                )
                return _Step(kind="salvage", payload=payload, answer=salvaged, burn_retried=burn_retried)
        # a 200 with no content is a transient provider failure, not an
        # answer. Log the response's actual signals so the failure mode is
        # observable, then retry with the same backoff as a 5xx; exhaust the
        # budget before failing.
        logger.warning(
            "chat: empty completion (finish_reason=%s, content_len=%d, reasoning_len=%d, gateway_cache=%s) — retrying",
            attempt.finish_reason or "n/a",
            len(attempt.content),
            len(attempt.reasoning.text),
            attempt.cache_status,
        )
        if attempts_made >= self.max_retries:
            return _Step(
                kind="raise",
                payload=payload,
                error=f"empty response from API (finish_reason={attempt.finish_reason or 'n/a'})",
                burn_retried=burn_retried,
            )
        return _Step(kind="retry", payload=payload, wait=True, burn_retried=burn_retried)

    def _record_reasoning(self, attempt: Attempt) -> None:
        """Record one attempt's reasoning — ``last_reasoning`` reads it back.

        The reasoning was parsed into ``attempt.reasoning`` by
        ``_read_attempt``, in either channel a provider uses (the gateway
        sends ``reasoning``; some providers ``reasoning_content``), so this is
        the only assignment of the call's reasoning state.

        A reasoning request that comes back with no reasoning is a SILENT
        degradation: the gateway accepted the request and answered without
        deliberating, and weeks of evals measured the disable path without
        anyone noticing. Name the model, the response id, the finish reason
        and the reasoning length and token count — never the reasoning text,
        which is family content here."""
        self._last_reasoning = attempt.reasoning
        if attempt.reasoning.enabled and not attempt.reasoning.has_text:
            logger.warning(
                "model %s served no reasoning for a reasoning request "
                "(response_id=%r, finish_reason=%r, reasoning_len=%d, reasoning_tokens=%s) — "
                "deliberation was requested but not served",
                self.model,
                attempt.reply.body.get("id", "absent"),
                attempt.finish_reason,
                len(attempt.reasoning.text),
                attempt.usage.get("reasoning_tokens", "absent"),
            )

    @staticmethod
    def _salvage(reasoning: Reasoning) -> str | None:
        """The reasoning's answer, or None when it holds none.

        The stop-empty recovery may only substitute the reasoning for a
        failed completion when that reasoning is a parseable JSON answer:
        deliberation prose is a genuine failure and keeps the retry path
        (review-bot finding on PR #62). A non-reasoning call is never
        salvaged, even if a provider sent a stray reasoning channel."""
        if not reasoning.enabled or not reasoning.has_text:
            return None
        try:
            json_object(reasoning.text)
        except AIClientError:
            return None
        return reasoning.text


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
        for hint in AIClient.AUTH_JSON_PROVIDER_HINTS:
            entry = auth.get(hint)
            if isinstance(entry, dict) and entry.get("type") == "api" and entry.get("key"):
                return entry["key"]
    raise AIClientError(
        "No API key found. Set OPENAI_API_KEY or OPENCODE_API_KEY, or log in with `opencode` "
        "(its auth file is read automatically)."
    )


def json_object(text: str) -> Mapping[str, Any]:
    """Extract the LAST complete JSON object from model output, tolerating
    fences, prose, and MULTIPLE objects — a reasoning preamble followed by
    the verdict is the shape the model emits. Scanning with raw_decode
    skips a malformed brace instead of failing.

    The object's shape is whatever the prompt asked for, so this returns
    the JSON document read-only: each caller reads the fields it knows
    (the verdict, the tool call) and names their own record for them."""
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
