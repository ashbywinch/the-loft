"""The session minted for a device grant, held for the grace window.

The device flow's cookie rides a page navigation, and the phone's network can
reject the fetch that reported the mint — so the minted session is kept briefly
and re-issued on the retry (houses' proven mechanism). In process memory only.
"""

from __future__ import annotations

import time

from pipeline.api.session_user import SessionUser


class MintedSession:
    """A session minted for a state token, kept while the grace window holds."""

    GRACE_SECONDS = 180

    def __init__(self, user: SessionUser, minted_at: float) -> None:
        self.user = user
        self.minted_at = minted_at

    @classmethod
    def minted(cls, user: SessionUser) -> MintedSession:
        """A session minted now."""
        return cls(user, time.time())

    def is_within_grace(self, now: float) -> bool:
        """Still re-issuable — the mint whose response the phone lost."""
        return now - self.minted_at < self.GRACE_SECONDS
