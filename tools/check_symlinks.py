"""Refuse a staged symlink that points at an absolute path.

An absolute symlink is a local convenience and nothing else: it names one
machine's directory, cannot resolve in CI or in another checkout, and is always
the by-product of wiring a shared artefact into a worktree (``ln -s
…/lucidlint-dist``, ``ln -s …/.venv``). It leaks into the index when a commit
sweeps the working tree with ``git add -A`` — measured 2026-11-26: a
``lucidlint-dist`` symlink was committed inside an unrelated change and the PII
scan then tried to read the symlink as a file.

The ignore file is the first line of defence and was wrong (``lucidlint-dist/``
matches a directory, not a symlink of that name). This is the second: the index
is where the mistake becomes shared, so it is where it is caught.

    python3 tools/check_symlinks.py       # exit 1 and list the offenders
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class AbsoluteLink:
    """One staged symlink that names an absolute target."""

    path: str
    target: str

    def __str__(self) -> str:
        return f"{self.path} -> {self.target}"


def staged_symlinks() -> list[tuple[str, str]]:
    """Every staged symlink, as (path, blob sha), read from the index."""
    symlink_mode = "120000"  # git's index mode for a symlink
    listed = subprocess.run(["git", "ls-files", "-s", "-z"], capture_output=True, text=True, check=True).stdout
    links: list[tuple[str, str]] = []
    for entry in listed.split("\0"):
        if not entry:
            continue
        # "<mode> <sha> <stage>\t<path>"
        meta, _, path = entry.partition("\t")
        fields = meta.split()
        if len(fields) >= 2 and fields[0] == symlink_mode:
            links.append((path, fields[1]))
    return links


def _blob_texts(shas: list[str]) -> dict[str, str]:
    """The contents of several blobs in one call, keyed by sha.

    ``git cat-file --batch`` answers ``<sha> <type> <size>``, then the object's
    bytes, then a newline — so the size is the only thing needed to walk it.
    """
    if not shas:
        return {}
    out = subprocess.run(
        ["git", "cat-file", "--batch"],
        input="\n".join(shas) + "\n",
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    texts: dict[str, str] = {}
    cursor = 0
    while cursor < len(out):
        header_end = out.find("\n", cursor)
        if header_end == -1:
            break
        fields = out[cursor:header_end].split()
        cursor = header_end + 1
        if len(fields) < 3:  # "<sha> missing" — nothing to read
            continue
        sha, size = fields[0], int(fields[2])
        texts[sha] = out[cursor : cursor + size]
        cursor += size + 1
    return texts


def absolute_links() -> list[AbsoluteLink]:
    """The staged symlinks whose target is absolute — the ones that cannot travel."""
    links = staged_symlinks()
    targets = _blob_texts([sha for _, sha in links])
    offenders: list[AbsoluteLink] = []
    for path, sha in links:
        target = targets.get(sha, "")
        if target.startswith("/") or (len(target) > 1 and target[1] == ":"):
            offenders.append(AbsoluteLink(path, target))
    return offenders


def main() -> int:
    offenders = absolute_links()
    if not offenders:
        return 0
    print("staged symlinks with absolute targets — they cannot resolve outside this machine:")
    for offender in offenders:
        print(f"  {offender}")
    print("Remove them from the index (git rm --cached <path>) and ignore the path instead.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
