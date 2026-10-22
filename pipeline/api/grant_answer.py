"""Google's answer to a device-grant request.

The /device/code start answers the device code and the user code to show; the
token poll answers the id_token once the narrator approves, or an error while
Google waits (authorization_pending, slow_down, access_denied, expired_token).
The body is JSON, or form-encoded on error — the wire shape is this class's.
"""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass
from typing import Any

DEFAULT_POLL_INTERVAL = 5
DEFAULT_VERIFICATION_URL = "https://www.google.com/device"


@dataclass(frozen=True)
class GrantAnswer:
    """Google's answer to a device-grant request — the start's fields, the
    poll's id_token, or an error."""

    device_code: str = ""
    user_code: str = ""
    verification_url: str = DEFAULT_VERIFICATION_URL
    interval: int = DEFAULT_POLL_INTERVAL
    expires_in: str = ""
    id_token: str = ""
    error: str = ""

    @classmethod
    def from_body(cls, body: str) -> GrantAnswer:
        """The answer in an HTTP body — JSON, or form-encoded on error
        (Google's 428 body is ``error=authorization_pending&…``)."""
        try:
            parsed = json.loads(body)
        except ValueError:
            # the form-encoded error body IS the payload — not a parse failure
            return cls.from_dict(dict(urllib.parse.parse_qsl(body)))
        return cls.from_dict(parsed)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> GrantAnswer:
        """The answer's fields with Google's fallbacks: the poll interval
        clamped to at least a second, and the device verification URL."""
        return cls(
            device_code=str(raw.get("device_code", "")),
            user_code=str(raw.get("user_code", "")),
            verification_url=str(raw.get("verification_url", DEFAULT_VERIFICATION_URL)),
            interval=max(1, int(raw.get("interval", DEFAULT_POLL_INTERVAL))),
            expires_in=str(raw.get("expires_in", "")),
            id_token=str(raw.get("id_token", "")),
            error=str(raw.get("error", "")),
        )
