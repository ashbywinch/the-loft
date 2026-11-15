"""Who may read the archive: the same people the Houses app knows.

The household keeps its people in ONE place — the Houses app's database. They
are this archive's family too, so the archive reads that list rather than
keeping a second one; adding someone to Houses is adding them here (user,
2026-11-15).

Only the people who carry an email can sign in (a child with no account is a
person, not a user), and the list is casefolded because the archive matches
people by casefolded email.

An unreadable database is NOBODY, never everybody: a missing or locked file
must not open the private layer.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from loft.live.houses import HousesDatabase, HousesDatabaseError


def houses_db_path(_env: Mapping[str, str] | None = None) -> Path:
    """The Houses database this archive reads its family from.

    The archive's own variable wins; else Houses' own setting, so one
    machine's configuration does not have to be written twice; else the
    checkout beside this one, which is where the two apps sit on the
    household's machine."""
    env = os.environ if _env is None else _env
    stated = env.get("THE_LOFT_HOUSES_DB") or env.get("HOUSES_SQLITE_PATH") or "~/Documents/code/houses/data/houses.db"
    return Path(stated).expanduser()


def family_members(db: Path | None = None) -> frozenset[str]:
    """The family's emails, casefolded — empty when the database cannot be
    read, which refuses everybody rather than admitting everybody."""
    path = houses_db_path() if db is None else db
    try:
        people = HousesDatabase(path).persons()
    except HousesDatabaseError:
        return frozenset()
    emails = (str(person.get("email") or "").strip().casefold() for person in people)
    return frozenset(email for email in emails if email)
