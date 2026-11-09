"""The live database's path and build-id defaults, with the env injected."""

from __future__ import annotations

from pathlib import Path

from loft.live.build import app_version
from loft.live.paths import default_database_path


def test_the_database_path_honours_the_override() -> None:
    assert default_database_path({"LOFT_DB_PATH": "/tmp/loft.db"}) == Path("/tmp/loft.db")


def test_the_database_path_defaults_under_the_users_data() -> None:
    expected = Path.home() / ".local" / "share" / "the-loft" / "loft.db"
    assert default_database_path({}) == expected


def test_the_app_version_honours_the_override() -> None:
    assert app_version({"LOFT_APP_VERSION": "test-build"}) == "test-build"
