"""The /api/auth/me answer.

The signed-in identity plus the archive person its email maps to (null when the
account is not in the archive), or the bare anonymous answer — nobody signed
in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pipeline.api.session_user import SessionUser


@dataclass(frozen=True)
class MeAnswer:
    """The /me route's answer: the identity, or nothing."""

    user: SessionUser | None = None
    person: str | None = None

    @property
    def authenticated(self) -> bool:
        """Whether a session identity rode the request."""
        return self.user is not None

    @classmethod
    def anonymous(cls) -> MeAnswer:
        """No session — the answer states only that."""
        return cls()

    @classmethod
    def signed_in(cls, user: SessionUser, person: str | None) -> MeAnswer:
        """A session — the identity and the archive person it maps to."""
        return cls(user, person)

    def to_dict(self) -> dict[str, Any]:
        """The answer as its wire record."""
        user = self.user
        if user is None:
            return {"authenticated": False}
        return {"authenticated": True, **user.to_dict(), "person": self.person}
