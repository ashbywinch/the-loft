"""The request that starts a device grant.

Google's /device/code endpoint takes the asking client and the scopes it wants,
form-encoded — so this record's wire is a form map.
"""

from __future__ import annotations

from dataclasses import dataclass

DEVICE_SCOPES = "openid email profile"


@dataclass(frozen=True)
class DeviceCodeRequest:
    """The /device/code request: which client asks, and for what."""

    client_id: str
    scope: str = DEVICE_SCOPES

    def to_form(self) -> dict[str, str]:
        """The form Google's /device/code endpoint reads."""
        return {"client_id": self.client_id, "scope": self.scope}
