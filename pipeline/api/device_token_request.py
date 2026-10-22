"""The request that polls a device grant.

Google's token endpoint takes the asking client, the device code and the device
grant type — and the client secret when the client has one. Form-encoded, so
this record's wire is a form map.
"""

from __future__ import annotations

from dataclasses import dataclass

GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"


@dataclass(frozen=True)
class DeviceTokenRequest:
    """The token poll for one device grant."""

    client_id: str
    device_code: str
    client_secret: str = ""

    def to_form(self) -> dict[str, str]:
        """The form Google's token endpoint reads — the secret only when the
        client has one."""
        form = {"client_id": self.client_id, "device_code": self.device_code, "grant_type": GRANT_TYPE}
        if self.client_secret:
            form["client_secret"] = self.client_secret
        return form
