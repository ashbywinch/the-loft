"""How strong a reading is: more letters beat fewer, ties by confidence.

The dedupe keeps the BEST reading of a physical region across the
orientation passes (2026-08-17: the postcard's vertical strips were read at
0°, 90° AND 270° — 'MHOTH' vs 'HARBOTTLE, MORPETH' share a box at IoU 0.97;
only the richer survives), so "richer" is a domain comparison, not a
throwaway pair: it is ordered lexicographically, exactly as the two-field
tuple it replaces was.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Richness:
    """A reading's strength — its letter count, then its confidence."""

    letters: int
    conf: float
