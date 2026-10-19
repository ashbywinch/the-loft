"""The /api/auth/device/poll request.

The device grant's state token — the opaque string Google's device flow handed
the headless tool at /device/start. The cookie rides the complete NAVIGATION,
never this response (the phone's network rejects fetch-carried cookies), so
the poll carries the token in its body instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DevicePollRequest:
    """The device poll's request: the grant's state token."""

    state: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> DevicePollRequest:
        """The poll a client states — an absent token is the empty one (the
        grant answers it as expired)."""
        return cls(state=str(raw.get("state", "")))
