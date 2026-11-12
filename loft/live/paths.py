"""Where the live database lives when no path is given.

The database lives on the laptop's internal disk, never the archive disk
(`docs/TECHSPEC/04-live-system.md` §17.11); `LOFT_DB_PATH` overrides it.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path


def default_database_path(env: Mapping[str, str] | None = None) -> Path:
    values = os.environ if env is None else env
    configured = values.get("LOFT_DB_PATH")
    if configured:
        return Path(configured)
    return Path.home() / ".local" / "share" / "the-loft" / "loft.db"
