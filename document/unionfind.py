"""Union-find: the connected-components machinery shared by the detector and
the review-order sorter."""

from __future__ import annotations


class UnionFind:
    """Union-find over integer indices, with path halving.

    The detector's components and the review order's box-overlap graph both
    need connected components; the algorithm is one thing and lives here, not
    copied per consumer."""

    def __init__(self, size: int = 0) -> None:
        self._parent = list(range(size))

    @property
    def size(self) -> int:
        """How many indices the forest holds (also the next run's id)."""
        return len(self._parent)

    def ensure(self, size: int) -> None:
        """Grow the forest so `size` indices exist (the detector adds runs as
        it reads the page's rows; a fixed-size forest would need the count
        up front)."""
        if size > len(self._parent):
            self._parent.extend(range(len(self._parent), size))

    def find(self, index: int) -> int:
        """The root of `index`'s component, with the path halved on the way."""
        while self._parent[index] != index:
            self._parent[index] = self._parent[self._parent[index]]
            index = self._parent[index]
        return index

    def union(self, one: int, other: int) -> None:
        """Join `one`'s and `other`'s components."""
        root_one, root_other = self.find(one), self.find(other)
        if root_one != root_other:
            self._parent[root_other] = root_one
