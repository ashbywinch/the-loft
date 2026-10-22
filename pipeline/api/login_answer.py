"""The /api/auth/login answer.

The browser's authorization URL to send the narrator to, or why the flow could
not start.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LoginAnswer:
    """The login route's answer."""

    status: str
    auth_url: str = ""
    detail: str = ""

    @classmethod
    def started(cls, auth_url: str) -> LoginAnswer:
        """The flow started — the URL the browser goes to."""
        return cls("ok", auth_url=auth_url)

    @classmethod
    def failed(cls, detail: str) -> LoginAnswer:
        """The flow could not start — why."""
        return cls("error", detail=detail)

    def to_dict(self) -> dict[str, Any]:
        """The answer as its wire record."""
        if self.status == "ok":
            return {"status": self.status, "auth_url": self.auth_url}
        return {"status": self.status, "detail": self.detail}
