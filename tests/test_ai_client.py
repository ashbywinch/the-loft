"""Tests for the AI client: the retry/backoff contract, the thinking-param
fallback, JSON extraction, and key resolution. No network — the urlopen is
injected (books_to_anki test pattern)."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from http.client import HTTPMessage
from typing import Any

import pytest
from pytest import MonkeyPatch

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
    client = AIClient(api_key="k", base_url="http://fake", urlopen=urlopen)
    assert client.chat("sys", "usr") == '{"ok": true}'
    body = calls[0]["body"]
    assert body["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}]
    assert body["temperature"] == 0.0
    assert body["response_format"] == {"type": "json_object"}


def test_chat_retries_transient_errors_with_backoff() -> None:
    sleeps: list[float] = []
    urlopen, _ = make_fake_urlopen(
        [
            http_error(503),
            http_error(429),
            FakeResponse({"choices": [{"message": {"content": "ok"}}]}),
        ]
    )
    client = AIClient(api_key="k", base_url="http://fake", urlopen=urlopen, max_retries=2, _sleep=sleeps.append)
    assert client.chat("s", "u") == "ok"
    assert sleeps == [2.0, 4.0]


def test_chat_gives_up_after_max_retries() -> None:
    urlopen, _ = make_fake_urlopen([http_error(503), http_error(503), http_error(503)])
    client = AIClient(api_key="k", base_url="http://fake", urlopen=urlopen, max_retries=2, _sleep=lambda _s: None)
    with pytest.raises(AIClientError):
        client.chat("s", "u")


def test_chat_retries_without_thinking_param_on_400() -> None:
    urlopen, calls = make_fake_urlopen([http_error(400), FakeResponse({"choices": [{"message": {"content": "ok"}}]})])
    client = AIClient(api_key="k", base_url="http://fake", urlopen=urlopen, max_retries=0, _sleep=lambda _s: None)
    assert client.chat("s", "u") == "ok"
    assert "thinking" not in calls[1]["body"]  # the fallback must not consume the retry budget


def test_chat_rejects_malformed_response() -> None:
    urlopen, _ = make_fake_urlopen([FakeResponse({"unexpected": True})])
    client = AIClient(api_key="k", base_url="http://fake", urlopen=urlopen)
    with pytest.raises(AIClientError):
        client.chat("s", "u")


def test_chat_rejects_null_choice_cleanly() -> None:
    # a provider returning "choices": [null] must raise the clean
    # AIClientError, not an AttributeError (review, 2026-08-15)
    urlopen, _ = make_fake_urlopen([FakeResponse({"choices": [None]})])
    client = AIClient(api_key="k", base_url="http://fake", urlopen=urlopen)
    with pytest.raises(AIClientError, match="empty response"):
        client.chat("s", "u")


def test_json_object_tolerates_fences() -> None:
    assert json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert json_object('Here you go: {"a": 1} — done') == {"a": 1}


def test_json_object_rejects_missing_json() -> None:
    with pytest.raises(AIClientError):
        json_object("no json here")


def test_find_api_key_prefers_environment(monkeypatch: MonkeyPatch) -> None:
    # lucidlint: ignore monkeypatch the subject is the env seam — OPENAI_API_KEY is the key source
    monkeypatch.setenv("OPENAI_API_KEY", "gateway-key")
    assert find_api_key() == "gateway-key"


def test_find_api_key_raises_when_missing(monkeypatch: MonkeyPatch) -> None:
    # lucidlint: ignore monkeypatch the subject is the env seam — a missing key must fail loudly
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(AIClientError):
        find_api_key()


def test_chat_null_message_is_a_clean_error() -> None:
    # a provider returning {"choices": [{"message": null}]} must raise the
    # clean AIClientError, not an AttributeError that escapes as a 500
    # (2026-08-15 review: the message-capture change regressed this)
    urlopen, _ = make_fake_urlopen([FakeResponse({"choices": [{"message": None}]})])
    client = AIClient(api_key="k", base_url="http://fake", urlopen=urlopen)
    with pytest.raises(AIClientError):
        client.chat("s", "u")
