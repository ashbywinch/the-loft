"""A store path split at its last suffix: the stem and the suffix.

The versioning chain inserts ``-N`` between the two halves, so they travel as
one named record rather than as a bare ``(stem, ext)`` tuple.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PathSuffix:
    """A store path's stem and suffix (``page-02.layout.json`` splits into
    ``page-02.layout`` and ``.json``)."""

    stem: str
    suffix: str

    @classmethod
    def split(cls, path: str) -> PathSuffix:
        """Split at the LAST suffix; a path with no suffix has an empty one."""
        dot = path.rfind(".")
        if dot == -1:
            return cls(path, "")
        return cls(path[:dot], path[dot:])

    def with_version(self, version: int) -> str:
        """The path with the version number inserted before its suffix."""
        return f"{self.stem}-{version}{self.suffix}"
