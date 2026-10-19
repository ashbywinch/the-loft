"""The retry budget: how long to wait before the next attempt, and how
many attempts have been made.

The pair travels together through a retry loop and carries its own rule —
sleep one interval, double it, count the attempt — so the rule lives on the
record instead of in a two-value return no call site can name.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Backoff:
    """One retry budget: the delay before the next attempt and the attempts
    made so far."""

    delay: float
    attempt: int

    def advance(self, sleep: Callable[[float], None]) -> Backoff:
        """Sleep this interval and return the budget for the next attempt:
        the delay doubles, the attempt count advances."""
        sleep(self.delay)
        return Backoff(self.delay * 2, self.attempt + 1)
