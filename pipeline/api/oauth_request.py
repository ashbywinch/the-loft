"""The web OAuth flow's in-flight authorization request.

One state token's record: the PKCE verifier the callback's code exchange needs,
and when the flow started. In process memory only — a restart invalidates
in-flight logins (houses parity).
"""

from __future__ import annotations

import time


class OAuthRequest:
    """An authorization request awaiting Google's callback."""

    MAX_AGE_SECONDS = 600

    def __init__(self, code_verifier: str, created_at: float) -> None:
        self.code_verifier = code_verifier
        self.created_at = created_at

    @classmethod
    def started(cls, code_verifier: str) -> OAuthRequest:
        """A request starting now."""
        return cls(code_verifier, time.time())

    def is_stale(self, now: float) -> bool:
        """Older than the max age — the sweep drops it."""
        return self.created_at < now - self.MAX_AGE_SECONDS
