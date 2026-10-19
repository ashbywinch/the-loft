"""The standing knowledge the guess works from: the archive's people and places.

The guess stage gives the model the names the archive already holds — the family
people (their aliases too) and the places — as context for the reading. The two
name lists travel together (they are one context), so they are one record rather
than a pair of lists whose order a caller has to remember.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StandingKnowledge:
    """The archive's known names: the people (aliases included) and the places."""

    people: list[str] = field(default_factory=list)
    places: list[str] = field(default_factory=list)
