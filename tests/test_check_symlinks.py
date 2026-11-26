"""The index guard: an absolute symlink is a local path that cannot travel.

Measured 2026-11-26: a worktree's `lucidlint-dist` symlink was swept into an
unrelated commit by `git add -A`; the PII scan then tried to read it as a file.
The ignore pattern was the first defence and was wrong (`dir/` matches a
directory, not a symlink of that name), so the index gets a guard of its own.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tools.check_symlinks import absolute_links, staged_symlinks


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    return tmp_path


def test_an_absolute_symlink_in_the_index_is_an_offender(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    (repo / "link").symlink_to("/somewhere/on/this/machine")
    subprocess.run(["git", "-C", str(repo), "add", "link"], check=True)
    monkeypatch.chdir(repo)
    assert [str(o) for o in absolute_links()] == ["link -> /somewhere/on/this/machine"]


def test_a_relative_symlink_is_fine(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    (repo / "target").write_text("x")
    (repo / "link").symlink_to("target")
    subprocess.run(["git", "-C", str(repo), "add", "target", "link"], check=True)
    monkeypatch.chdir(repo)
    assert absolute_links() == []


def test_a_regular_file_is_not_a_symlink(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    (repo / "plain").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "plain"], check=True)
    monkeypatch.chdir(repo)
    assert staged_symlinks() == []
