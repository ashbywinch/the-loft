"""The device grant in flight.

Google's device code for one state token, and when the narrator started the
flow. In process memory only — a restart invalidates it. Google's device codes
live ~30 minutes, so the grant expires.
"""

from __future__ import annotations

import time


class DeviceGrant:
    """A device grant awaiting the narrator's approval at google.com/device."""

    MAX_AGE_SECONDS = 1800  # google's device codes live ~30 min

    def __init__(self, device_code: str, created_at: float) -> None:
        self.device_code = device_code
        self.created_at = created_at

    @classmethod
    def started(cls, device_code: str) -> DeviceGrant:
        """A grant starting now."""
        return cls(device_code, time.time())

    def is_expired(self, now: float) -> bool:
        """Past Google's window — the grant can no longer be polled."""
        return now - self.created_at > self.MAX_AGE_SECONDS
