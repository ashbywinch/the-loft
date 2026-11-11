"""The build id written to `events.app_version` and `schema_migrations`."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path


class Repo:
    """The checkout this package lives in — the root every path is built from."""

    ROOT = Path(__file__).resolve().parents[2]


def app_version(env: Mapping[str, str] | None = None) -> str:
    """The configured build id, else the short git sha, else `dev`."""
    values = os.environ if env is None else env
    configured = values.get("LOFT_APP_VERSION")
    if configured:
        return configured
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Repo.ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "dev"
    return result.stdout.strip() or "dev"
