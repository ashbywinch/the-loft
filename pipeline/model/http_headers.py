"""The headers one API request carries: the credential, the media types,
the client's name, and whether a gateway may answer from its cache.

The headers are the request's wire record, so the class owns the dict: a
header that matters — the bearer token, the no-cache demand — is a named
field a reviewer can find instead of a string key buried in a call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

USER_AGENT = "opencode/1.14.20"  # Cloudflare in front of the API rejects the urllib default UA


@dataclass(frozen=True)
class HttpHeaders:
    """One request's headers; a field left unset stays off the wire."""

    authorization: str | None = None
    content_type: str | None = None
    accept: str | None = None
    user_agent: str | None = None
    # A gateway in front of the model may cache completions, and a
    # measurement served from that cache is not a measurement: a cached
    # reply "answers" in 0.3s where the real call takes minutes, with
    # byte-identical tokens.
    skip_gateway_cache: bool = False

    def to_dict(self) -> dict[str, Any]:
        """The headers as the request sends them."""
        out: dict[str, Any] = {}
        if self.accept is not None:
            out["Accept"] = self.accept
        if self.content_type is not None:
            out["Content-Type"] = self.content_type
        if self.authorization is not None:
            out["Authorization"] = self.authorization
        if self.user_agent is not None:
            out["User-Agent"] = self.user_agent
        if self.skip_gateway_cache:
            out["cf-aig-skip-cache"] = "true"
        return out
