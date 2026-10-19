"""The /api/auth/device/poll answer.

Pending while Google waits (slow_down asks for a slower poll), the minted
session once the id_token verifies against the device client, or why the grant
ended.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pipeline.api.session_user import SessionUser


@dataclass(frozen=True)
class DevicePollAnswer:
    """The device-poll route's answer."""

    status: str
    user: SessionUser | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status == "ok" and self.user is None:
            raise ValueError("the approved grant's answer carries the session")

    @classmethod
    def pending(cls, detail: str = "") -> DevicePollAnswer:
        """Google is still waiting — ``detail`` names a slower-poll request."""
        return cls("pending", detail=detail)

    @classmethod
    def minted(cls, user: SessionUser) -> DevicePollAnswer:
        """Approved — the session the state token minted."""
        return cls("ok", user=user)

    @classmethod
    def failed(cls, detail: str) -> DevicePollAnswer:
        """The grant ended — why."""
        return cls("error", detail=detail)

    def to_dict(self) -> dict[str, Any]:
        """The answer as its wire record — the session rides ``id_info``."""
        user = self.user
        if user is not None:
            return {"status": self.status, "id_info": user.to_dict()}
        if self.detail:
            return {"status": self.status, "detail": self.detail}
        return {"status": self.status}
