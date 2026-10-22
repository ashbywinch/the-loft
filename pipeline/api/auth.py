"""Google OAuth for the Loft — the identity seam (user).

Ported from the houses repo's web/auth.py (the pattern the family already
runs): the authorization-code flow with PKCE via ``google_auth_oauthlib``,
the id_token verified by ``google.oauth2``, and a signed session cookie via
itsdangerous (30 days, survives restarts). The callback URL is the LAN
address the server prints — Google's OAuth client accepts the registered IP
callback (houses does the same). The person is resolved server-side from the
verified email against the archive's people records (Person.email) — the
identity lives in the DB, never in code (user).

Routes (mounted on the Server's handler):
  GET  /api/auth/login     -> {auth_url} (start the flow)
  GET  /api/auth/callback  -> session cookie + redirect to the app
  GET  /api/auth/me        -> {authenticated, email, name, picture, person}
  POST /api/auth/logout    -> clears the session cookie

Every record this seam moves — the client config, the session identity, the
in-flight login state, Google's device-grant answers, the route answers — is
a class in its own module next to this one; each owns its wire shape.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from datetime import timedelta
from urllib.parse import quote

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from google.oauth2 import id_token as google_id_token
from google_auth_oauthlib.flow import Flow
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from pipeline.api.device_code_request import DeviceCodeRequest
from pipeline.api.device_grant import DeviceGrant
from pipeline.api.device_poll_answer import DevicePollAnswer
from pipeline.api.device_start_answer import DeviceStartAnswer
from pipeline.api.device_token_request import DeviceTokenRequest
from pipeline.api.grant_answer import GrantAnswer
from pipeline.api.login_answer import LoginAnswer
from pipeline.api.me_answer import MeAnswer
from pipeline.api.minted_session import MintedSession
from pipeline.api.oauth_client import OAuthClient
from pipeline.api.oauth_request import OAuthRequest
from pipeline.api.session_user import SessionUser
from tools.archive import Archive

logger = logging.getLogger(__name__)

SESSION_MAX_AGE = timedelta(days=30)

# The OAuth state token's entropy (32 bytes -> 43 url-safe chars) and the web
# flow's scopes (the verified email and profile a session is minted from).
_STATE_TOKEN_BYTES = 32
_WEB_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]


class AuthState:
    """The in-flight login state — web OAuth states, device grants, and
    recently-minted sessions. Ephemeral by design: a restart invalidates
    in-flight logins (houses parity). Each record owns its own lifetime; the
    store owns the sweep and the cap on in-flight states."""

    STATE_MAX_ENTRIES = 100

    def __init__(self) -> None:
        self.oauth_states: dict[str, OAuthRequest] = {}
        self.device_grants: dict[str, DeviceGrant] = {}
        self.recent_sessions: dict[str, MintedSession] = {}

    def sweep_stale_states(self) -> None:
        """Drop the web OAuth states older than the max age."""
        now = time.time()
        stale = [k for k, v in self.oauth_states.items() if v.is_stale(now)]
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


def _client_config() -> OAuthClient | None:
    """The web client the browser flow signs in as — None while the app has
    no client configured (the login fails honestly)."""
    if not web_client_id() or not web_client_secret():
        return None
    return OAuthClient(
        client_id=web_client_id(),
        client_secret=web_client_secret(),
        redirect_uri=f"{public_url()}/api/auth/callback",
    )


def _make_session_cookie(user: SessionUser) -> str:
    """The signed session cookie carrying the verified identity."""
    return _serializer().dumps(user.to_dict())


def session_user_from_cookie(cookie: str | None) -> SessionUser | None:
    """The verified session identity from the ``session`` cookie, or None.

    Accepts the raw Cookie header (``session=<payload>; …``) or the bare
    payload — the serializer must never see the name= prefix."""
    if not cookie:
        return None
    if f"{COOKIE_NAME}=" in cookie:
        for part in cookie.split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE_NAME:
                cookie = value
                break
    try:
        payload = _serializer().loads(cookie, max_age=int(SESSION_MAX_AGE.total_seconds()))
    except (BadSignature, SignatureExpired):
        return None
    return SessionUser.from_dict(payload)


def login_url() -> LoginAnswer:
    """Start the flow — the authorization URL for the browser, or why the
    flow could not start."""
    config = _client_config()
    if config is None:
        return LoginAnswer.failed("Google OAuth is not configured (THE_LOFT_GOOGLE_WEB_CLIENT_ID)")
    _auth_state.sweep_stale_states()
    state = secrets.token_urlsafe(_STATE_TOKEN_BYTES)
    flow = Flow.from_client_config(config.to_dict(), scopes=_WEB_SCOPES)
    flow.redirect_uri = f"{public_url()}/api/auth/callback"
    authorization_url, _ = flow.authorization_url(access_type="online", include_granted_scopes="false", state=state)
    code_verifier = str(getattr(flow, "code_verifier", "") or "")
    if not code_verifier:
        return LoginAnswer.failed("PKCE code_verifier not generated")
    if len(_auth_state.oauth_states) >= AuthState.STATE_MAX_ENTRIES:
        _auth_state.sweep_stale_states()
    if len(_auth_state.oauth_states) >= AuthState.STATE_MAX_ENTRIES:
        return LoginAnswer.failed("Too many login attempts, try again")
    _auth_state.oauth_states[state] = OAuthRequest.started(code_verifier)
    return LoginAnswer.started(authorization_url)


def exchange_code(code: str, state: str) -> SessionUser | None:
    """Verify and consume the callback's code+state; the verified identity, or
    None on any failure (an unverified email is no identity)."""
    config = _client_config()
    if config is None:
        return None
    pending = _auth_state.oauth_states.pop(state, None)
    if pending is None:
        logger.warning("auth: unknown or replayed OAuth state")
        return None
    flow = Flow.from_client_config(config.to_dict(), scopes=_WEB_SCOPES)
    flow.redirect_uri = f"{public_url()}/api/auth/callback"
    flow.code_verifier = pending.code_verifier
    try:
        flow.fetch_token(code=code)
        raw = getattr(flow.credentials, "id_token", "")  # the google-auth type misses the property
        if not raw:
            raise RuntimeError("no id_token on the exchanged credentials")
        claims = dict(id_token.verify_oauth2_token(raw, google_requests.Request(), web_client_id()))
    # lucidlint: ignore broad-except the auth boundary must never 500 (the noqa explains the why)
    except Exception as e:  # noqa: BLE001  # the callback must never 500
        logger.exception("auth: token exchange failed: %s", e)
        return None
    if not claims.get("email_verified"):
        logger.warning("auth: unverified email for %s", claims.get("email"))
        return None
    return SessionUser.from_dict(claims)


def person_for_email(archive: Archive, email: str | None) -> str | None:
    """The archive person whose Person.email matches the verified account —
    casefolded, the identity lives in the DB (user)."""
    if not email:
        return None
    folded = email.casefold()
    people = archive.get_identity("people")
    for person in people.people if people else ():
        if (person.email or "").casefold() == folded:
            return person.id
    return None


def me_payload(archive: Archive, session: SessionUser | None) -> MeAnswer:
    """The /api/auth/me answer — the authenticated identity + the archive
    person the email maps to (null when the account isn't in the archive)."""
    if session is None:
        return MeAnswer.anonymous()
    return MeAnswer.signed_in(session, person_for_email(archive, session.email))


def callback_error_url(error: str) -> str:
    return f"{public_url()}/?auth_error={quote(error)}"


# -- the device flow (houses parity) ----------------------------------------------
# The browser flow's callback can't be a LAN IP (Google won't register one)
# and the phone can't reach this machine's localhost — so sign-in runs the
# OAuth device grant: a code shown to the narrator, approved at
# google.com/device, the id_token minting the session. No redirect URIs at
# all. The device client is houses' — one family client for the family apps.

_DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
_DEVICE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def device_client_id() -> str:
    return os.environ.get("THE_LOFT_GOOGLE_DEVICE_CLIENT_ID", "").strip()


def device_client_secret() -> str:
    return os.environ.get("THE_LOFT_GOOGLE_DEVICE_CLIENT_SECRET", "").strip()


def _device_grant_post(url: str, data: dict[str, str]) -> GrantAnswer:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return GrantAnswer.from_body(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Google's token endpoint answers "authorization_pending" with an
        # HTTP 428 — the body IS the meaningful payload
        return GrantAnswer.from_body(e.read().decode("utf-8"))
    # lucidlint: ignore broad-except the auth boundary wraps and re-raises (the noqa explains the why)
    except Exception as e:  # noqa: BLE001  # the endpoint reports the failure
        raise RuntimeError(f"device grant request failed: {e}") from e


def start_device_grant(
    _post: Callable[[str, dict[str, str]], GrantAnswer] | None = None,
) -> DeviceStartAnswer:
    """Begin the device grant — the state token, the user code the narrator
    approves at google.com/device, and the poll interval; or why the grant
    could not start. ``_post`` is the injectable Google HTTP seam for tests
    (DI, never monkeypatch)."""
    client_id = device_client_id()
    if not client_id:
        return DeviceStartAnswer.failed("the device OAuth client is not configured (THE_LOFT_GOOGLE_DEVICE_CLIENT_ID)")
    answer = (_post or _device_grant_post)(_DEVICE_CODE_URL, DeviceCodeRequest(client_id=client_id).to_form())
    if not answer.device_code or not answer.user_code:
        return DeviceStartAnswer.failed("Google did not start the device grant")
    state = secrets.token_urlsafe(_STATE_TOKEN_BYTES)
    _auth_state.device_grants[state] = DeviceGrant.started(answer.device_code)
    logger.info(
        "auth: device grant started (user_code %s, expires in %ss)",
        answer.user_code,
        answer.expires_in or "?",
    )
    return DeviceStartAnswer.started(
        state=state,
        user_code=answer.user_code,
        verification_url=answer.verification_url,
        interval=answer.interval,
    )


def minted_session(state: str) -> SessionUser | None:
    """The session minted for this state, while the grace window holds —
    the device-complete navigation's source (the phone's network can
    reject fetch responses, so the cookie lands on a page navigation
    instead, houses' proven mechanism)."""
    minted = _auth_state.recent_sessions.get(state)
    if minted is None or not minted.is_within_grace(time.time()):
        return None
    return minted.user


def poll_device_grant(
    state: str,
    _post: Callable[[str, dict[str, str]], GrantAnswer] | None = None,
    _verify: Callable[[str], SessionUser | None] | None = None,
) -> DevicePollAnswer:
    """Poll Google for the narrator's approval — pending until approved, then
    the minted session once the id_token verifies against the device client
    (a web-flow token must not be replayable). ``_post``/``_verify`` are the
    injectable Google seams for tests."""
    grant = _auth_state.device_grants.get(state)
    if grant is None:
        return _grant_grace_reissue(state)
    if grant.is_expired(time.time()):
        _auth_state.device_grants.pop(state, None)
        return DevicePollAnswer.failed("the device grant expired — start again")
    answer = (_post or _device_grant_post)(
        _DEVICE_TOKEN_URL,
        DeviceTokenRequest(
            client_id=device_client_id(),
            device_code=grant.device_code,
            client_secret=device_client_secret(),
        ).to_form(),
    )
    if answer.error:
        return _grant_error_response(state, answer)
    return _complete_grant(state, answer, _verify)


def _grant_grace_reissue(state: str) -> DevicePollAnswer:
    """A grant consumed by a mint whose response the phone lost — re-issue
    the session so a retry lands the cookie."""
    minted = _auth_state.recent_sessions.get(state)
    if minted is not None and minted.is_within_grace(time.time()):
        logger.info("auth: re-issuing the minted session (grace) for %s", minted.user.email)
        return DevicePollAnswer.minted(minted.user)
    return DevicePollAnswer.failed("no such device grant")


def _grant_error_response(state: str, answer: GrantAnswer) -> DevicePollAnswer:
    """The device grant's error outcomes — pending while Google waits,
    slow_down asks for a slower poll, access_denied/expired_token end the
    grant."""
    error = answer.error
    if error == "authorization_pending":
        return DevicePollAnswer.pending()
    if error in ("slow_down", "access_denied", "expired_token"):
        if error == "access_denied":
            _auth_state.device_grants.pop(state, None)
        if error == "slow_down":
            logger.info("auth: device grant pending (google: %s)", error)
            return DevicePollAnswer.pending(error)
        logger.info("auth: device grant error (google: %s)", error)
        return DevicePollAnswer.failed(error)
    _auth_state.device_grants.pop(state, None)
    logger.warning("auth: device grant error: %s", error)
    return DevicePollAnswer.failed(error)


def _complete_grant(
    state: str,
    answer: GrantAnswer,
    _verify: Callable[[str], SessionUser | None] | None,
) -> DevicePollAnswer:
    """The approved grant's finish: verify the id_token against the device
    client (a web-flow token must not be replayable) and mint the session."""
    if not answer.id_token:
        logger.warning("auth: device token response carried no id_token")
        return DevicePollAnswer.failed("no id_token in the device grant response")
    _auth_state.device_grants.pop(state, None)
    user = (_verify or verify_device_id_token)(answer.id_token)
    if user is None:
        logger.warning("auth: device id_token failed verification")
        return DevicePollAnswer.failed("the id_token did not verify")
    logger.info("auth: device grant approved by %s", user.email)
    _auth_state.recent_sessions[state] = MintedSession.minted(user)
    return DevicePollAnswer.minted(user)


def verify_device_id_token(token: str) -> SessionUser | None:
    """Verify a Google id_token bound to the DEVICE-flow client (houses
    parity: a browser-leakable web id_token must not mint a session here)."""
    client_id = device_client_id()
    if not client_id:
        return None
    try:
        claims = dict(google_id_token.verify_oauth2_token(token, google_requests.Request(), client_id))
    # lucidlint: ignore broad-except the auth boundary reports and returns None (the noqa explains the why)
    except Exception as e:  # noqa: BLE001  # the caller reports the failure
        logger.warning("auth: device id_token verification failed: %s", e)
        return None
    return SessionUser.from_dict(claims)
