"""The /api/auth/me answer.

The signed-in identity plus the archive person its email maps to (null when the
account is not in the archive), and whether that account is family — or the
bare anonymous answer, nobody signed in.
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
    is_family: bool = False

    @property
    def authenticated(self) -> bool:
        """Whether a session identity rode the request."""
        return self.user is not None

    @classmethod
    def anonymous(cls) -> MeAnswer:
        """No session — the answer states only that."""
        return cls()

    @classmethod
    def signed_in(cls, user: SessionUser, person: str | None, is_family: bool) -> MeAnswer:
        """A session — the identity, the archive person it maps to, and whether
        the account is family (a signed-in stranger is not)."""
        return cls(user, person, is_family)

    def to_dict(self) -> dict[str, Any]:
        """The answer as its wire record."""
        user = self.user
        if user is None:
            return {"authenticated": False}
        return {"authenticated": True, **user.to_dict(), "person": self.person, "is_family": self.is_family}
