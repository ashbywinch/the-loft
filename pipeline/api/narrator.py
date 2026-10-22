"""The signed-in narrator of a capture request.

The verified session's account and the archive person its email maps to — the
name a contribution is attributed to. The capture API mints the narrator from
the session cookie, never from a client-claimed name; the app's request bodies
may carry a ``who``, and it is ignored.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Narrator:
    """The signed-in narrator — the account, and the person it maps to."""

    email: str
    name: str
    person: str | None = None
    who: str = ""
