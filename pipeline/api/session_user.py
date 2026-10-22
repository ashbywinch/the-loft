"""The signed-in narrator's identity.

The verified Google account as the session cookie carries it: the email the
archive's people are matched by (casefolded once, here — the DB match is
case-insensitive), the display name, and the picture. The wire shape (the
cookie's signed payload) is this class's dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SessionUser:
    """The verified account a session belongs to."""

    email: str
    name: str = ""
    picture: str = ""

    def __post_init__(self) -> None:
        # the archive matches people by casefolded email — normalise once,
        # here, never at each caller
        object.__setattr__(self, "email", self.email.casefold())

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SessionUser:
        """The identity a wire record states — the cookie's payload, or a
        verified Google id_token's claims (the same three keys)."""
        return cls(
            email=str(raw.get("email", "")),
            name=str(raw.get("name", "")),
            picture=str(raw.get("picture", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """The identity as its wire record — the cookie's signed payload."""
        return {"email": self.email, "name": self.name, "picture": self.picture}
