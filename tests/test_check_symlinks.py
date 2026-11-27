"""The index guard: an absolute symlink is a local path that cannot travel.

An ignore pattern with a trailing slash matches a directory, not a symlink of the
same name, so a worktree's shared artefact is stageable by any `git add -A`. The
index is where a local path becomes shared, so the guard reads the index.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tools.check_symlinks import absolute_links, staged_symlinks

# A machine's own git config (hooks, `core.symlinks`, signing) must not decide a
# test: the repository under test is one this file made.
_HERMETIC = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, env=_HERMETIC)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@example.com"], check=True, env=_HERMETIC)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True, env=_HERMETIC)
    return tmp_path


def test_an_absolute_symlink_in_the_index_is_an_offender(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    (repo / "link").symlink_to("/somewhere/on/this/machine")
    subprocess.run(["git", "-C", str(repo), "add", "link"], check=True, env=_HERMETIC)
    monkeypatch.chdir(repo)
    assert [str(o) for o in absolute_links()] == ["link -> /somewhere/on/this/machine"]


def test_a_relative_symlink_is_fine(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    (repo / "target").write_text("x")
    (repo / "link").symlink_to("target")
    subprocess.run(["git", "-C", str(repo), "add", "target", "link"], check=True, env=_HERMETIC)
    monkeypatch.chdir(repo)
    assert absolute_links() == []


def test_a_regular_file_is_not_a_symlink(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    (repo / "plain").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "plain"], check=True, env=_HERMETIC)
    monkeypatch.chdir(repo)
    assert staged_symlinks() == []
