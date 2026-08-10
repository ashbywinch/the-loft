"""The identity seam (2026-08-06): the Google session cookie round-trips,
the archive's email mapping resolves the narrator, and the login endpoint
fails honestly when the OAuth client isn't configured."""

from __future__ import annotations

from typing import Any, cast

import pytest

from tools import auth
from tools.archive import Archive
from tools.store import MemoryStore


@pytest.fixture(autouse=True)
def secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THE_LOFT_SESSION_SECRET", "test-secret")


def test_session_cookie_round_trips() -> None:
    cookie = auth._make_session_cookie("alex@example.com", "Alex Hale", "pic")
    session = auth.session_user_from_cookie(f"session={cookie}; other=1")
    assert session == {"email": "alex@example.com", "name": "Alex Hale", "picture": "pic"}


def test_session_cookie_rejects_tampering() -> None:
    cookie = auth._make_session_cookie("alex@example.com", "Alex Hale", "")
    tampered = cookie[:-4] + ("AAAA" if cookie[-4:] != "AAAA" else "BBBB")
    assert auth.session_user_from_cookie(tampered) is None
    assert auth.session_user_from_cookie(None) is None


def test_person_for_email_maps_from_the_archive() -> None:
    archive = Archive(MemoryStore())
    archive.save_identity(
        "people",
        {"people": [{"id": "p-alex", "name": "Alex Hale", "email": "Alex.Hale@Example.com"}], "relationships": []},
    )
    assert auth.person_for_email(archive, "alex.hale@example.com") == "p-alex"
    assert auth.person_for_email(archive, "nobody@example.com") is None
    assert auth.person_for_email(archive, None) is None


def test_login_fails_honestly_without_a_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THE_LOFT_GOOGLE_WEB_CLIENT_ID", raising=False)
    monkeypatch.delenv("THE_LOFT_GOOGLE_WEB_CLIENT_SECRET", raising=False)
    result = auth.login_url()
    assert result["status"] == "error"
    assert "not configured" in result["detail"]


def test_me_payload_uses_the_archive_person(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THE_LOFT_GOOGLE_WEB_CLIENT_ID", "client")
    monkeypatch.setenv("THE_LOFT_GOOGLE_WEB_CLIENT_SECRET", "secret")
    archive = Archive(MemoryStore())
    archive.save_identity(
        "people",
        {"people": [{"id": "p-alex", "name": "Alex Hale", "email": "alex@example.com"}], "relationships": []},
    )
    cookie = f"{auth.COOKIE_NAME}={auth._make_session_cookie('alex@example.com', 'A', '')}"
    session = auth.session_user_from_cookie(cookie)
    assert session is not None
    assert auth.me_payload(archive, session)["person"] == "p-alex"
    assert auth.me_payload(archive, None) == {"authenticated": False}


def test_device_grant_unconfigured_fails_honestly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THE_LOFT_GOOGLE_DEVICE_CLIENT_ID", raising=False)
    result = auth.start_device_grant()
    assert result["status"] == "error"
    assert "not configured" in result["detail"]
    assert auth.poll_device_grant("no-such-state")["status"] == "error"


def test_device_grant_round_trip_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the device client configured, start records a grant and poll
    reports pending until Google approves (the token endpoint is Google's —
    a real approval is an end-to-end manual step; the state machinery and
    the id_token binding are what the server owns)."""
    monkeypatch.setenv("THE_LOFT_GOOGLE_DEVICE_CLIENT_ID", "device-client")
    monkeypatch.setenv("THE_LOFT_GOOGLE_DEVICE_CLIENT_SECRET", "device-secret")
    monkeypatch.setattr(
        auth,
        "_device_grant_post",
        lambda url, data: (
            {"device_code": "dc-1", "user_code": "ABCD-EFGH", "interval": "5"}
            if "device/code" in url
            else {"error": "authorization_pending"}
        ),
    )
    started = auth.start_device_grant()
    assert started["status"] == "ok"
    assert started["user_code"] == "ABCD-EFGH"
    pending = auth.poll_device_grant(started["state"])
    assert pending["status"] == "pending"
    # the grant is consumed after a successful token exchange
    auth._device_grants[started["state"]] = {"device_code": "dc-1", "created_at": __import__("time").time()}
    auth._device_grant_post = cast(Any, lambda url, data: {"id_token": "jwt"})

    def _fake_verify(token: str) -> dict[str, Any] | None:
        if token != "jwt":
            return None
        return {"email": "alex.hale@example.com", "email_verified": True}

    auth.verify_device_id_token = cast(Any, _fake_verify)
    ok = auth.poll_device_grant(started["state"])
    assert ok["status"] == "ok"
    assert ok["id_info"]["email"] == "alex.hale@example.com"
    # the grace window: a lost poll response (the phone's network) must be
    # able to re-issue the minted session — then it expires (2026-08-06)
    again = auth.poll_device_grant(started["state"])
    assert again["status"] == "ok" and again["id_info"]["email"] == "alex.hale@example.com"
    auth._recent_sessions[started["state"]]["_minted_at"] -= auth._SESSION_GRACE_SECONDS + 1
    assert auth.poll_device_grant(started["state"])["status"] == "error"  # grace expired


def test_minted_session_grace_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """The complete endpoint's source: the minted session, while the grace
    holds — then gone (2026-08-06)."""
    monkeypatch.setenv("THE_LOFT_GOOGLE_DEVICE_CLIENT_ID", "device-client")
    monkeypatch.setenv("THE_LOFT_GOOGLE_DEVICE_CLIENT_SECRET", "device-secret")
    monkeypatch.setattr(
        auth,
        "_device_grant_post",
        lambda url, data: (
            {"device_code": "dc-1", "user_code": "ABCD-EFGH", "interval": "5"}
            if "device/code" in url
            else {"id_token": "jwt"}
        ),
    )

    def _fake_verify(token: str) -> dict[str, Any] | None:
        return {"email": "alex.hale@example.com", "email_verified": True} if token == "jwt" else None

    auth.verify_device_id_token = cast(Any, _fake_verify)
    started = auth.start_device_grant()
    ok = auth.poll_device_grant(started["state"])
    assert ok["status"] == "ok"
    minted = auth.minted_session(started["state"])
    assert minted is not None and minted["email"] == "alex.hale@example.com"
    auth._recent_sessions[started["state"]]["_minted_at"] -= auth._SESSION_GRACE_SECONDS + 1
    assert auth.minted_session(started["state"]) is None
    assert auth.minted_session("no-such-state") is None
