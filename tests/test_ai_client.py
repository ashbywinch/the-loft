"""Tests for the AI client: the retry/backoff contract, the thinking-param
fallback, JSON extraction, and key resolution. No network — the urlopen is
injected (books_to_anki test pattern)."""

from __future__ import annotations

import io
import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from http.client import HTTPMessage
from pathlib import Path
from typing import Any

import pytest

from tools.ai_client import AIClient, AIClientError, find_api_key, json_object


class FakeResponse:
    def __init__(self, payload: dict[str, object] | str) -> None:
        self._payload: str = payload if isinstance(payload, str) else json.dumps(payload)

    def read(self) -> bytes:
        return self._payload.encode("utf-8")

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


Urlopen = Callable[..., Any]


def make_fake_urlopen(responses: list[object]) -> tuple[Urlopen, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    def urlopen(request: urllib.request.Request, timeout: float) -> object:
        raw = request.data
        if isinstance(raw, bytes):
            text = raw.decode("utf-8")
        elif isinstance(raw, bytearray):
            text = bytes(raw).decode("utf-8")
        else:
            text = str(raw)
        calls.append({"url": request.full_url, "body": json.loads(text), "timeout": timeout})
        response = responses.pop(0)
        if isinstance(response, urllib.error.HTTPError):
            raise response
        return response

    return urlopen, calls


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://fake", code, f"err {code}", HTTPMessage(), io.BytesIO(b"nope"))


def test_chat_sends_system_user_and_returns_content() -> None:
    urlopen, calls = make_fake_urlopen([FakeResponse({"choices": [{"message": {"content": '{"ok": true}'}}]})])
    client = AIClient(api_key="k", urlopen=urlopen)
    assert client.chat("sys", "usr") == '{"ok": true}'
    body = calls[0]["body"]
    assert body["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}]
    assert body["temperature"] == 0.0
    assert body["response_format"] == {"type": "json_object"}


def test_chat_sends_no_reasoning_budget_by_default() -> None:
    """The reasoning budget is OFF by default: the CI gateway ignores the
    cap AND reshapes the response (the JSON answer lands in the reasoning
    channel with empty content — the stop-empty cascade), so a thinking
    call must not carry it unless explicitly configured. The opt-in path
    still sends it (the local litellm gateway honors it)."""
    urlopen, calls = make_fake_urlopen([FakeResponse({"choices": [{"message": {"content": "ok"}}]}) for _ in range(2)])
    client = AIClient(api_key="k", urlopen=urlopen, _sleep=lambda s: None, max_retries=0)
    client.chat("s", "u", thinking=True)
    assert "reasoning" not in calls[0]["body"]
    opted = AIClient(api_key="k", urlopen=urlopen, _sleep=lambda s: None, max_retries=0, reasoning_budget=6000)
    opted.chat("s", "u", thinking=True)
    assert calls[1]["body"]["reasoning"] == {"max_tokens": 6000}


def test_chat_retries_transient_errors_with_backoff() -> None:
    sleeps: list[float] = []
    urlopen, _ = make_fake_urlopen(
        [
            http_error(503),
            http_error(429),
            FakeResponse({"choices": [{"message": {"content": "ok"}}]}),
        ]
    )
    client = AIClient(api_key="k", urlopen=urlopen, max_retries=2, _sleep=sleeps.append)
    assert client.chat("s", "u") == "ok"
    assert sleeps == [2.0, 4.0]


def test_chat_gives_up_after_max_retries() -> None:
    urlopen, _ = make_fake_urlopen([http_error(503), http_error(503), http_error(503)])
    client = AIClient(api_key="k", urlopen=urlopen, max_retries=2, _sleep=lambda _s: None)
    with pytest.raises(AIClientError):
        client.chat("s", "u")


def test_chat_retries_without_reasoning_params_on_400() -> None:
    urlopen, calls = make_fake_urlopen([http_error(400), FakeResponse({"choices": [{"message": {"content": "ok"}}]})])
    client = AIClient(api_key="k", urlopen=urlopen, max_retries=0, _sleep=lambda _s: None)
    assert client.chat("s", "u", thinking=True) == "ok"
    retry = calls[1]["body"]
    assert "thinking" not in retry and "reasoning" not in retry  # both params dropped; retry budget untouched
    assert retry["temperature"] == 0.0  # the deterministic non-thinking path


def test_chat_rejects_malformed_response() -> None:
    urlopen, _ = make_fake_urlopen([FakeResponse({"unexpected": True})])
    client = AIClient(api_key="k", urlopen=urlopen)
    with pytest.raises(AIClientError):
        client.chat("s", "u")


def test_chat_rejects_null_choice_cleanly() -> None:
    # a provider returning "choices": [null] must raise the clean
    # AIClientError, not an AttributeError — a null choice is an empty
    # completion: retried to the budget, then the clean error
    urlopen, _ = make_fake_urlopen([FakeResponse({"choices": [None]}) for _ in range(3)])
    client = AIClient(api_key="k", urlopen=urlopen)
    with pytest.raises(AIClientError, match="empty response"):
        client.chat("s", "u")


def test_chat_retries_an_empty_completion(caplog: pytest.LogCaptureFixture) -> None:
    """A 200 with no content is a transient provider failure, not an answer
    — the client must retry it with the same backoff as a 5xx, never
    surface it. The retry logs the response's finish_reason so an
    output-budget-burned completion (length, zero content) is observable."""
    sleeps: list[float] = []
    good: dict[str, object] = {"choices": [{"message": {"content": '{"ok": true}'}}]}
    empty: dict[str, object] = {
        "choices": [{"message": {"content": "", "reasoning_content": "b" * 2000}, "finish_reason": "length"}]
    }
    urlopen, calls = make_fake_urlopen(
        [
            FakeResponse(empty),
            FakeResponse(empty),
            FakeResponse(good),
        ]
    )
    client = AIClient(api_key="k", urlopen=urlopen, _sleep=sleeps.append, max_retries=2)
    with caplog.at_level(logging.WARNING, logger="tools.ai_client"):
        assert client.chat("s", "u") == '{"ok": true}'
    assert len(calls) == 3, "the empty completions were returned instead of retried"
    assert sleeps == [2.0, 4.0]
    assert "finish_reason=length" in caplog.text
    assert "reasoning_len=2000" in caplog.text


def test_chat_gives_up_on_persistent_empty_completions() -> None:
    sleeps: list[float] = []
    urlopen, _ = make_fake_urlopen([FakeResponse({"choices": [{"message": {"content": ""}}]}) for _ in range(3)])
    client = AIClient(api_key="k", urlopen=urlopen, _sleep=sleeps.append, max_retries=2)
    with pytest.raises(AIClientError, match="empty response from API"):
        client.chat("s", "u")


def test_thinking_burn_retries_on_a_fresh_sample() -> None:
    """A thinking completion that stalls (finish_reason "length", zero
    content) is retried ONCE with the reasoning KEPT: a fresh temperature
    sample and nothing else — no budget change, no prompt rewrite — free
    of the retry budget (arXiv:2502.08235's sample-and-select; the
    measured CI failure: a tighter budget was ignored by the gateway and
    a conclude-now nudge made the model wrap up inside its thinking and
    emit no content)."""
    burned: dict[str, object] = {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}
    good: dict[str, object] = {"choices": [{"message": {"content": '{"ok": true}'}}]}
    urlopen, calls = make_fake_urlopen([FakeResponse(burned), FakeResponse(good)])
    client = AIClient(api_key="k", urlopen=urlopen, _sleep=lambda s: None, max_retries=0)
    assert client.chat("s", "u", thinking=True) == '{"ok": true}'
    assert len(calls) == 2
    assert calls[0]["body"]["thinking"] == {"type": "enabled"}
    retry = calls[1]["body"]
    assert retry["thinking"] == {"type": "enabled"}  # reasoning stays on
    assert "reasoning" not in retry  # no budget param by default — the CI gateway reshapes the response with it
    assert retry["temperature"] == 0.5  # a genuinely different sample
    assert retry["messages"] == calls[0]["body"]["messages"]  # the prompt is never rewritten


def test_stop_empty_recovers_the_reasoning_answer() -> None:
    """A stop-empty completion whose reasoning holds the structured answer
    IS the answer — the client recovers it instead of retrying (measured:
    deepseek-v4-flash via the CI gateway returns the verdict JSON in the
    reasoning channel with content=="" on some draws)."""
    verdict = '{"relevant": true, "contradiction": {"found": false, "detail": ""}}'
    stop_empty: dict[str, object] = {
        "choices": [{"message": {"content": "", "reasoning": verdict}, "finish_reason": "stop"}]
    }
    urlopen, _ = make_fake_urlopen([FakeResponse(stop_empty)])
    client = AIClient(api_key="k", urlopen=urlopen, _sleep=lambda s: None, max_retries=0)
    assert client.chat("s", "u", thinking=True) == verdict


def test_stop_empty_without_reasoning_still_retries() -> None:
    """A stop-empty with NO reasoning is a genuine failure — the retry
    path still applies (the reasoning-recovery is only for answers that
    landed in the thinking channel)."""
    urlopen, _ = make_fake_urlopen([FakeResponse({"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]})])
    client = AIClient(api_key="k", urlopen=urlopen, _sleep=lambda s: None, max_retries=0)
    with pytest.raises(AIClientError, match="empty response from API"):
        client.chat("s", "u", thinking=True)


def test_stop_empty_with_prose_reasoning_still_retries() -> None:
    """A stop-empty whose reasoning is deliberation prose (no parseable
    JSON) is a genuine failure — the recovery is gated on the reasoning
    holding the structured answer, so the retry path still applies
    (review-bot finding on PR #62)."""
    prose: dict[str, object] = {
        "choices": [
            {
                "message": {"content": "", "reasoning": "Let me weigh the evidence once more. The records are clear."},
                "finish_reason": "stop",
            }
        ]
    }
    urlopen, _ = make_fake_urlopen([FakeResponse(prose)])
    client = AIClient(api_key="k", urlopen=urlopen, _sleep=lambda s: None, max_retries=0)
    with pytest.raises(AIClientError, match="empty response from API"):
        client.chat("s", "u", thinking=True)


def test_stop_empty_recovery_is_thinking_only() -> None:
    """The recovery is gated on thinking-enabled calls — a non-thinking
    request's reasoning channel (a rare provider quirk) is not treated as
    the answer."""
    verdict = '{"ok": true}'
    stop_empty: dict[str, object] = {
        "choices": [{"message": {"content": "", "reasoning": verdict}, "finish_reason": "stop"}]
    }
    urlopen, _ = make_fake_urlopen([FakeResponse(stop_empty)])
    client = AIClient(api_key="k", urlopen=urlopen, _sleep=lambda s: None, max_retries=0)
    with pytest.raises(AIClientError, match="empty response from API"):
        client.chat("s", "u")


def test_json_object_takes_the_last_of_multiple_objects() -> None:
    """A reasoning preamble followed by the verdict is the shape the model
    emits — a slice spanning both failed with "Extra data": the LAST
    complete object wins."""
    assert json_object('{"type":"reasoning","text":"..."}\n{"verdict": "x"}') == {"verdict": "x"}
    assert json_object('{"a": 1}\n{"b": 2}') == {"b": 2}


def test_json_object_skips_a_malformed_brace() -> None:
    assert json_object('{"a": 1} {"broken": }\n{"b": 2}') == {"b": 2}


def test_json_object_tolerates_fences() -> None:
    assert json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert json_object('Here you go: {"a": 1} — done') == {"a": 1}


def test_json_object_rejects_missing_json() -> None:
    with pytest.raises(AIClientError):
        json_object("no json here")


def test_find_api_key_prefers_environment() -> None:
    assert find_api_key(_env={"OPENCODE_API_KEY": "env-key"}) == "env-key"


def test_find_api_key_ignores_the_loft_legacy_env(tmp_path: Path) -> None:
    """LOFT_AI_KEY is the retired secret name — a stale value must never
    defeat the gateway tokens."""
    with pytest.raises(AIClientError):
        find_api_key(_env={"LOFT_AI_KEY": "stale-token"}, _home=tmp_path)


def test_burn_rescue_fires_once_then_terminates() -> None:
    """The fresh-sample rescue is bounded to ONE attempt — a second
    length-burn is a persistent stall and must take the terminating
    backoff path, never loop unboundedly (review-bot finding on PR #62:
    the unbound branch would re-issue forever with no counter)."""
    burned: dict[str, object] = {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}
    good: dict[str, object] = {"choices": [{"message": {"content": '{"ok": true}'}}]}
    urlopen, calls = make_fake_urlopen([FakeResponse(burned), FakeResponse(burned), FakeResponse(good)])
    client = AIClient(api_key="k", urlopen=urlopen, _sleep=lambda s: None, max_retries=2)
    assert client.chat("s", "u", thinking=True) == '{"ok": true}'
    assert [c["body"]["temperature"] for c in calls] == [0.3, 0.5, 0.5]  # ONE fresh-sample retry, then backoff


def test_burn_rescue_fires_once_then_terminates_on_persistent_burns() -> None:
    """Two burns with no recovery exhaust the retry budget — the give-up
    contract holds even when the stall persists (never an infinite
    loop)."""
    burned: dict[str, object] = {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}
    urlopen, _ = make_fake_urlopen([FakeResponse(burned) for _ in range(3)])
    client = AIClient(api_key="k", urlopen=urlopen, _sleep=lambda s: None, max_retries=0)
    with pytest.raises(AIClientError, match="empty response from API"):
        client.chat("s", "u", thinking=True)


def test_find_api_key_prefers_openai_api_key(tmp_path: Path) -> None:
    """The gateway token's env name wins over every legacy source."""
    assert (
        find_api_key(
            _env={"OPENAI_API_KEY": "gw", "CLOUDFLARE_AIGATEWAY_TOKEN": "cf", "OPENCODE_API_KEY": "legacy"},
            _home=tmp_path,
        )
        == "gw"
    )


def test_find_api_key_reads_opencode_auth(tmp_path: Path) -> None:
    auth_dir = tmp_path / ".local" / "share" / "opencode"
    auth_dir.mkdir(parents=True)
    _ = (auth_dir / "auth.json").write_text(
        json.dumps({"opencode-go": {"type": "api", "key": "auth-key"}}), encoding="utf-8"
    )
    assert find_api_key(_env={}, _home=tmp_path) == "auth-key"


def test_find_api_key_raises_when_missing(tmp_path: Path) -> None:
    with pytest.raises(AIClientError):
        find_api_key(_env={}, _home=tmp_path)


def test_find_api_key_raises_on_corrupt_auth_file(tmp_path: Path) -> None:
    """A config file that exists but is corrupt is an operator error — it
    surfaces loudly, never silently treated as 'no key' (fail-fast)."""
    auth_dir = tmp_path / ".local" / "share" / "opencode"
    auth_dir.mkdir(parents=True)
    (auth_dir / "auth.json").write_text("this is not json", encoding="utf-8")
    with pytest.raises(AIClientError, match="auth file"):
        find_api_key(_env={}, _home=tmp_path)


def test_chat_null_message_is_a_clean_error() -> None:
    # a provider returning {"choices": [{"message": null}]} must raise the
    # clean AIClientError, not an AttributeError that escapes as a 500
    urlopen, _ = make_fake_urlopen([FakeResponse({"choices": [{"message": None}]}) for _ in range(3)])
    client = AIClient(api_key="k", urlopen=urlopen)
    with pytest.raises(AIClientError):
        client.chat("s", "u")
