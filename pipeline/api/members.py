"""Who may read the archive: the family's accounts.

The list is configuration, not content: the repo is data-free and public, so
the addresses live in the shell environment (``THE_LOFT_FAMILY_MEMBERS``, a
comma-separated list), the same way every other credential does. They are the
household's own people — lifted from the tools that already know them, and
held here as a list rather than read live from another app's database: two
projects stay decoupled, and a change on one side is a deliberate edit on the
other (user, 2026-11-15).

Unset is NOBODY: an empty list is the safe reading of "not configured", so the
private layer never opens because an operator forgot a variable.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from pipeline.api.session_user import SessionUser


def family_members(_env: Mapping[str, str] | None = None) -> frozenset[str]:
    """The emails allowed to read the archive, casefolded (the archive matches
    people by casefolded email)."""
    env = os.environ if _env is None else _env
    listed = env.get("THE_LOFT_FAMILY_MEMBERS", "").split(",")
    return frozenset(email.strip().casefold() for email in listed if email.strip())


def is_member(user: SessionUser | None, members: frozenset[str] | None = None) -> bool:
    """Whether the signed-in account is family. No session is never a member —
    the routes answer their own 401 for that, with the message they each own.
    ``members`` is the seam the tests inject; None reads the configured list."""
    if user is None:
        return False
    return user.email in (family_members() if members is None else members)
