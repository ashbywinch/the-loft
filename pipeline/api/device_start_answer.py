"""The /api/auth/device/start answer.

The state token, the user code the narrator approves at google.com/device and
the poll interval, or why the grant could not start.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DeviceStartAnswer:
    """The device-start route's answer."""

    status: str
    state: str = ""
    user_code: str = ""
    verification_url: str = ""
    interval: int = 0
    detail: str = ""

    @classmethod
    def started(cls, state: str, user_code: str, verification_url: str, interval: int) -> DeviceStartAnswer:
        """The grant started — what the narrator must approve."""
        return cls(
            "ok",
            state=state,
            user_code=user_code,
            verification_url=verification_url,
            interval=interval,
        )

    @classmethod
    def failed(cls, detail: str) -> DeviceStartAnswer:
        """The grant could not start — why."""
        return cls("error", detail=detail)

    def to_dict(self) -> dict[str, Any]:
        """The answer as its wire record."""
        if self.status == "ok":
            return {
                "status": self.status,
                "state": self.state,
                "user_code": self.user_code,
                "verification_url": self.verification_url,
                "interval": self.interval,
            }
        return {"status": self.status, "detail": self.detail}
