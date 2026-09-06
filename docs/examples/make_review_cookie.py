"""Print a valid Loft session cookie for the review surface.

Run from the loft repo root with the main venv's python after sourcing
`.env` (the script and the server must share THE_LOFT_SESSION_SECRET):

    . .env && .venv/bin/python docs/examples/make_review_cookie.py

The reviewed identity comes from LOFT_REVIEW_EMAIL (required) and
LOFT_REVIEW_NAME (optional) in the gitignored `.env`.
"""

import os
import sys
from dataclasses import asdict, dataclass

from itsdangerous import URLSafeTimedSerializer

sys.path.insert(0, ".")
from tools.auth import session_secret  # noqa: E402  (sys.path bootstrap must precede the import)


@dataclass
class SessionIdentity:
    """The payload the Loft server stores in the session cookie."""

    email: str
    name: str
    picture: str


def main() -> None:
    try:
        email = os.environ["LOFT_REVIEW_EMAIL"]
    except KeyError:
        sys.exit(
            "LOFT_REVIEW_EMAIL is required — set it in the loft repo's gitignored .env and source it before running."
        )
    identity = SessionIdentity(
        email=email,
        name=os.environ.get("LOFT_REVIEW_NAME", "Review"),
        picture="",
    )
    print(URLSafeTimedSerializer(session_secret(), salt="loft-session").dumps(asdict(identity)))


if __name__ == "__main__":
    main()
