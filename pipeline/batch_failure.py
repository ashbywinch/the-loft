"""One batch the worker could not process, and why.

The worker's queue keeps going after a failure (a broken pile must never
hold the ones behind it), so the failure is a value the sweep reports and
the operator reads — never a swallowed exception.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BatchFailure:
    """A batch that failed its machine pass: the batch, and the reason line."""

    batch_id: str
    reason: str
