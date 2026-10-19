"""The Google web OAuth client this app runs as.

The record ``google_auth_oauthlib``'s Flow reads: which client the browser
signs in as, that client's secret, and the callback Google redirects to — plus
Google's two fixed endpoints. The wire shape (``{"web": {...}}``) is this
class's dict; no caller assembles it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"


@dataclass(frozen=True)
class OAuthClient:
    """The web client the authorization-code flow runs as."""

    client_id: str
    client_secret: str
    redirect_uri: str

    def to_dict(self) -> dict[str, Any]:
        """The client config ``Flow.from_client_config`` reads."""
        return {
            "web": {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "auth_uri": AUTH_URI,
                "token_uri": TOKEN_URI,
                "redirect_uris": [self.redirect_uri],
            }
        }
