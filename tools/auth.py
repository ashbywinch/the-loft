"""Google OAuth for the Loft — the identity seam (2026-08-06, user).

Ported from the houses repo's web/auth.py (the pattern the family already
runs): the authorization-code flow with PKCE via ``google_auth_oauthlib``,
the id_token verified by ``google.oauth2``, and a signed session cookie via
itsdangerous (30 days, survives restarts). The callback URL is the LAN
address the server prints — Google's OAuth client accepts the registered IP
callback (houses does the same). The person is resolved server-side from the
verified email against the archive's people records (Person.email) — the
identity lives in the DB, never in code (user, 2026-08-06).

Routes (mounted on the Server's handler):
  GET  /api/auth/login     -> {auth_url} (start the flow)
  GET  /api/auth/callback  -> session cookie + redirect to the app
  GET  /api/auth/me        -> {authenticated, email, name, picture, person}
  POST /api/auth/logout    -> clears the session cookie
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Any
from urllib.parse import quote

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from google.oauth2 import id_token as google_id_token
from google_auth_oauthlib.flow import Flow
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from tools.archive import Archive

logger = logging.getLogger(__name__)

SESSION_MAX_AGE = timedelta(days=30)

# The OAuth state token's entropy (32 bytes -> 43 url-safe chars) and the
# device-grant poll interval fallback (seconds) when Google omits it.
_STATE_TOKEN_BYTES = 32
_DEFAULT_DEVICE_POLL_INTERVAL = 5


class AuthState:
    """The in-flight login state — web OAuth states, device grants, and
    recently-minted sessions. Ephemeral by design: a restart invalidates
    in-flight logins (houses parity). The invariants (max ages, max
    entries, the sweep) live here, never in the callers."""

    STATE_MAX_AGE_SECONDS = 600
    STATE_MAX_ENTRIES = 100
    DEVICE_GRANT_MAX_AGE = 1800  # google's device codes live ~30 min
    SESSION_GRACE_SECONDS = 180

    def __init__(self) -> None:
        self.oauth_states: dict[str, dict[str, Any]] = {}
        self.device_grants: dict[str, dict[str, Any]] = {}
        self.recent_sessions: dict[str, dict[str, Any]] = {}

    def sweep_stale_states(self) -> None:
        """Drop the web OAuth states older than the max age."""
        now = time.time()
        stale = [k for k, v in self.oauth_states.items() if v.get("created_at", 0) < now - self.STATE_MAX_AGE_SECONDS]
        for k in stale:
            self.oauth_states.pop(k, None)


# The process's one in-flight login store — the auth functions read and
# mutate it, never a module global dict (ephemeral: a restart clears it).
_auth_state = AuthState()

COOKIE_NAME = "session"


def web_client_id() -> str:
    return os.environ.get("THE_LOFT_GOOGLE_WEB_CLIENT_ID", "").strip()


def web_client_secret() -> str:
    return os.environ.get("THE_LOFT_GOOGLE_WEB_CLIENT_SECRET", "").strip()


def session_secret(_env: Mapping[str, str] | None = None) -> str:
    env = os.environ if _env is None else _env
    return env.get("THE_LOFT_SESSION_SECRET", "").strip()


def public_url() -> str:
    """The callback base the Google client has registered — the LAN address
    the server prints by default (houses parity: an IP callback works)."""
    return os.environ.get("THE_LOFT_PUBLIC_URL", "http://localhost:8000").rstrip("/")


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(session_secret(), salt="loft-session")


def _client_config() -> dict[str, Any] | None:
    client_id = web_client_id()
    if not client_id or not web_client_secret():
        return None
    return {
        "web": {
            "client_id": client_id,
            "client_secret": web_client_secret(),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [f"{public_url()}/api/auth/callback"],
        }
    }


def _make_session_cookie(email: str, name: str, picture: str) -> str:
    return _serializer().dumps({"email": email, "name": name, "picture": picture})


def session_user_from_cookie(cookie: str | None) -> dict[str, Any] | None:
    """The verified session payload from the ``session`` cookie, or None.

    Accepts the raw Cookie header (``session=<payload>; …``) or the bare
    payload — the serializer must never see the name= prefix (2026-08-06)."""
    if not cookie:
        return None
    if f"{COOKIE_NAME}=" in cookie:
        for part in cookie.split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE_NAME:
                cookie = value
                break
    try:
        return _serializer().loads(cookie, max_age=int(SESSION_MAX_AGE.total_seconds()))
    except (BadSignature, SignatureExpired):
        return None


def login_url() -> dict[str, Any]:
    """Start the flow — {auth_url} for the browser, or an error detail."""
    config = _client_config()
    if config is None:
        return {"status": "error", "detail": "Google OAuth is not configured (THE_LOFT_GOOGLE_WEB_CLIENT_ID)"}
    _auth_state.sweep_stale_states()
    state = secrets.token_urlsafe(_STATE_TOKEN_BYTES)
    flow = Flow.from_client_config(
        config,
        scopes=[
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
        ],
    )
    flow.redirect_uri = f"{public_url()}/api/auth/callback"
    authorization_url, _ = flow.authorization_url(access_type="online", include_granted_scopes="false", state=state)
    code_verifier = str(getattr(flow, "code_verifier", "") or "")
    if not code_verifier:
        return {"status": "error", "detail": "PKCE code_verifier not generated"}
    if len(_auth_state.oauth_states) >= AuthState.STATE_MAX_ENTRIES:
        _auth_state.sweep_stale_states()
    if len(_auth_state.oauth_states) >= AuthState.STATE_MAX_ENTRIES:
        return {"status": "error", "detail": "Too many login attempts, try again"}
    _auth_state.oauth_states[state] = {"code_verifier": code_verifier, "created_at": time.time()}
    return {"status": "ok", "auth_url": authorization_url}


def exchange_code(code: str, state: str) -> dict[str, Any] | None:
    """Verify and consume the callback's code+state; returns the verified
    id_info ({email, name, picture, email_verified}) or None on any failure."""
    config = _client_config()
    if config is None:
        return None
    state_data = _auth_state.oauth_states.pop(state, None)
    if state_data is None:
        logger.warning("auth: unknown or replayed OAuth state")
        return None
    code_verifier = str(state_data.get("code_verifier", ""))
    flow = Flow.from_client_config(
        config,
        scopes=[
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
        ],
    )
    flow.redirect_uri = f"{public_url()}/api/auth/callback"
    flow.code_verifier = code_verifier
    try:
        flow.fetch_token(code=code)
        raw = getattr(flow.credentials, "id_token", "")  # the google-auth type misses the property
        if not raw:
            raise RuntimeError("no id_token on the exchanged credentials")
        id_info: dict[str, Any] = dict(id_token.verify_oauth2_token(raw, google_requests.Request(), web_client_id()))
    # lucidlint: ignore broad-except the auth boundary must never 500 (the noqa explains the why)
    except Exception as e:  # noqa: BLE001  # the callback must never 500
        logger.exception("auth: token exchange failed: %s", e)
        return None
    if not id_info.get("email_verified"):
        logger.warning("auth: unverified email for %s", id_info.get("email"))
        return None
    return id_info


def person_for_email(archive: Archive, email: str | None) -> str | None:
    """The archive person whose Person.email matches the verified account —
    casefolded, the identity lives in the DB (user, 2026-08-06)."""
    if not email:
        return None
    folded = email.casefold()
    people = archive.get_identity("people")
    for person in (people or {}).get("people", []):
        if str(person.get("email", "")).casefold() == folded:
            return person.get("id")
    return None


def me_payload(archive: Archive, session: dict[str, Any] | None) -> dict[str, Any]:
    """The /api/auth/me shape — the authenticated identity + the archive
    person the email maps to (null when the account isn't in the archive)."""
    if not session:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "email": session.get("email", ""),
        "name": session.get("name", ""),
        "picture": session.get("picture", ""),
        "person": person_for_email(archive, session.get("email")),
    }


def callback_error_url(error: str) -> str:
    return f"{public_url()}/?auth_error={quote(error)}"


# -- the device flow (houses parity, 2026-08-06) ----------------------------
# The browser flow's callback can't be a LAN IP (Google won't register one)
# and the phone can't reach this machine's localhost — so sign-in runs the
# OAuth device grant: a code shown to the narrator, approved at
# google.com/device, the id_token minting the session. No redirect URIs at
# all. The device client is houses' — one family client for the family apps.

_DEVICE_SCOPES = "openid email profile"
_DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
_DEVICE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def device_client_id() -> str:
    return os.environ.get("THE_LOFT_GOOGLE_DEVICE_CLIENT_ID", "").strip()


def device_client_secret() -> str:
    return os.environ.get("THE_LOFT_GOOGLE_DEVICE_CLIENT_SECRET", "").strip()


def _device_grant_post(url: str, data: dict[str, str]) -> dict[str, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return _parse_grant_response(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Google's token endpoint answers "authorization_pending" with an
        # HTTP 428 — the body IS the meaningful payload (2026-08-06)
        return _parse_grant_response(e.read().decode("utf-8"))
    # lucidlint: ignore broad-except the auth boundary wraps and re-raises (the noqa explains the why)
    except Exception as e:  # noqa: BLE001  # the endpoint reports the failure
        raise RuntimeError(f"device grant request failed: {e}") from e


def _parse_grant_response(payload: str) -> dict[str, Any]:
    """Google's device/code and token endpoints answer JSON, or form-encoded
    on error — the 428 body is `error=authorization_pending&...`."""
    try:
        return json.loads(payload)
    except ValueError:
        return dict(urllib.parse.parse_qsl(payload))


def start_device_grant(
    _post: Callable[[str, dict[str, str]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Begin the device grant — {state, user_code, verification_url,
    interval} for the narrator to approve, or an error detail. ``_post`` is
    the injectable Google HTTP seam for tests (DI, never monkeypatch)."""
    client_id = device_client_id()
    if not client_id:
        return {
            "status": "error",
            "detail": "the device OAuth client is not configured (THE_LOFT_GOOGLE_DEVICE_CLIENT_ID)",
        }
    info = (_post or _device_grant_post)(
        _DEVICE_CODE_URL,
        {"client_id": client_id, "scope": _DEVICE_SCOPES},
    )
    device_code = str(info.get("device_code", ""))
    user_code = str(info.get("user_code", ""))
    if not device_code or not user_code:
        return {"status": "error", "detail": "Google did not start the device grant"}
    state = secrets.token_urlsafe(_STATE_TOKEN_BYTES)
    _auth_state.device_grants[state] = {"device_code": device_code, "created_at": time.time()}
    logger.info("auth: device grant started (user_code %s, expires in %ss)", user_code, info.get("expires_in", "?"))
    return {
        "status": "ok",
        "state": state,
        "user_code": user_code,
        "verification_url": info.get("verification_url", "https://www.google.com/device"),
        "interval": max(1, int(info.get("interval", _DEFAULT_DEVICE_POLL_INTERVAL))),
    }


def minted_session(state: str) -> dict[str, Any] | None:
    """The session minted for this state, while the grace window holds —
    the device-complete navigation's source (2026-08-06: the phone's
    network can reject fetch responses, so the cookie lands on a page
    navigation instead, houses' proven mechanism)."""
    recent = _auth_state.recent_sessions.get(state)
    if not recent or time.time() - recent.get("_minted_at", 0) >= AuthState.SESSION_GRACE_SECONDS:
        return None
    return {k: v for k, v in recent.items() if k != "_minted_at"}


def poll_device_grant(
    state: str,
    _post: Callable[[str, dict[str, str]], dict[str, Any]] | None = None,
    _verify: Callable[[str], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Poll Google for the narrator's approval — {status: "pending"} until
    approved, then {status: "ok", id_info} after the id_token verifies
    against the device client (a web-flow token must not be replayable).
    ``_post``/``_verify`` are the injectable Google seams for tests."""
    grant = _auth_state.device_grants.get(state)
    if not grant:
        return _grant_grace_reissue(state)
    if time.time() - grant.get("created_at", 0) > AuthState.DEVICE_GRANT_MAX_AGE:
        _auth_state.device_grants.pop(state, None)
        return {"status": "error", "detail": "the device grant expired — start again"}
    token_data: dict[str, str] = {
        "client_id": device_client_id(),
        "device_code": str(grant["device_code"]),
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }
    if device_client_secret():
        token_data["client_secret"] = device_client_secret()
    result = (_post or _device_grant_post)(_DEVICE_TOKEN_URL, token_data)
    if result.get("error"):
        return _grant_error_response(state, result)
    return _complete_grant(state, result, _verify)


def _grant_grace_reissue(state: str) -> dict[str, Any]:
    """A grant consumed by a mint whose response the phone lost — re-issue
    the session so a retry lands the cookie (2026-08-06)."""
    recent = _auth_state.recent_sessions.get(state)
    if recent and time.time() - recent.get("_minted_at", 0) < AuthState.SESSION_GRACE_SECONDS:
        logger.info("auth: re-issuing the minted session (grace) for %s", recent.get("email"))
        return {"status": "ok", "id_info": {k: v for k, v in recent.items() if k != "_minted_at"}}
    return {"status": "error", "detail": "no such device grant"}


def _grant_error_response(state: str, result: dict[str, Any]) -> dict[str, Any]:
    """The device grant's error outcomes — pending while Google waits,
    slow_down asks for a slower poll, access_denied/expired_token end the
    grant."""
    if result["error"] == "authorization_pending":
        return {"status": "pending"}
    if result["error"] in ("slow_down", "access_denied", "expired_token"):
        if result["error"] == "access_denied":
            _auth_state.device_grants.pop(state, None)
        outcome = "pending" if result["error"] == "slow_down" else "error"
        logger.info("auth: device grant %s (google: %s)", outcome, result["error"])
        return {"status": outcome, "detail": result["error"]}
    _auth_state.device_grants.pop(state, None)
    logger.warning("auth: device grant error: %s", result["error"])
    return {"status": "error", "detail": result["error"]}


def _complete_grant(
    state: str,
    result: dict[str, Any],
    _verify: Callable[[str], dict[str, Any] | None] | None,
) -> dict[str, Any]:
    """The approved grant's finish: verify the id_token against the device
    client (a web-flow token must not be replayable) and mint the session."""
    id_token_value = str(result.get("id_token", ""))
    if not id_token_value:
        logger.warning("auth: device token response carried no id_token")
        return {"status": "error", "detail": "no id_token in the device grant response"}
    _auth_state.device_grants.pop(state, None)
    id_info = (_verify or verify_device_id_token)(id_token_value)
    if id_info is None:
        logger.warning("auth: device id_token failed verification")
        return {"status": "error", "detail": "the id_token did not verify"}
    logger.info("auth: device grant approved by %s", id_info.get("email"))
    _auth_state.recent_sessions[state] = {**id_info, "_minted_at": time.time()}
    return {"status": "ok", "id_info": id_info}


def verify_device_id_token(token: str) -> dict[str, Any] | None:
    """Verify a Google id_token bound to the DEVICE-flow client (houses
    parity: a browser-leakable web id_token must not mint a session here)."""
    client_id = device_client_id()
    if not client_id:
        return None
    try:
        return dict(google_id_token.verify_oauth2_token(token, google_requests.Request(), client_id))
    # lucidlint: ignore broad-except the auth boundary reports and returns None (the noqa explains the why)
    except Exception as e:  # noqa: BLE001  # the caller reports the failure
        logger.warning("auth: device id_token verification failed: %s", e)
        return None
