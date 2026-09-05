"""The reading order — how the review pane's lines are displayed.

The block-aware order (2026-08-20, user's requirement): the lines cluster
into physical blocks (lines sharing ink), the blocks read top-to-bottom,
and within each block the TRANSCRIPTION order is preserved — each block
reads WHOLE with one rotation, never the row-by-row interleave of
overlapping blocks (the postcard's 0° top and 90° message bounced per
line under the old reading-start sort).
"""

from __future__ import annotations

from typing import Any

from tools.box import overlap


class Block:
    """A physical text block: the lines whose boxes share ink. Reads whole
    — the transcription order inside, never interleaved with another
    block's lines."""

    def __init__(self, lines: list[dict[str, Any]]) -> None:
        self.lines = lines

    @property
    def top(self) -> float:
        """The topmost box's y — the block's position for the top-to-bottom
        block order."""
        return min((line["box"][1] for line in self.lines if line.get("box")), default=0.0)

    def in_transcription_order(self) -> list[dict[str, Any]]:
        """The block's lines in the transcription order (the line's input
        position — each line's ``index`` is the review's edit key)."""
        return sorted(self.lines, key=lambda line: line.get("index", 0))

    @classmethod
    def cluster(cls, lines: list[dict[str, Any]]) -> list[Block]:
        """The connected components of the box-overlap graph — lines
        sharing any ink form one block. Boxless lines are singletons."""
        parent = list(range(len(lines)))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for i in range(len(lines)):
            a = lines[i].get("box")
            if not a:
                continue
            for j in range(i + 1, len(lines)):
                b = lines[j].get("box")
                if b and overlap(a, b) > 0:
                    union(i, j)
        members: dict[int, list[dict[str, Any]]] = {}
        for i in range(len(lines)):
            members.setdefault(find(i), []).append(lines[i])
        return [cls(m) for m in members.values()]


def order_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The block-aware reading order: the boxed lines cluster into blocks,
    the blocks read top-to-bottom, each whole in the transcription order;
    the boxless lines keep their input relative order."""
    boxed = [line for line in lines if _is_boxed(line)]
    rest = [line for line in lines if not _is_boxed(line)]
    blocks = sorted(Block.cluster(boxed), key=lambda block: block.top)
    return [line for block in blocks for line in block.in_transcription_order()] + rest


def _is_boxed(line: dict[str, Any]) -> bool:
    box = line.get("box")
    return isinstance(box, list) and len(box) == 4 and box[2] > box[0] and box[3] > box[1]
