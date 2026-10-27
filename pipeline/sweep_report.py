"""What one sweep of the worker did: the piles it registered, the batches it
ran, and the ones that failed.

One value for one pass, so the CLI prints it and a test asserts on it
without capturing output.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.adoption_result import AdoptionResult
from pipeline.batch_failure import BatchFailure


@dataclass(frozen=True)
class SweepReport:
    """One sweep's outcome: the scan area's piles, the queue's batches."""

    adoptions: tuple[AdoptionResult, ...] = ()
    processed: tuple[str, ...] = ()
    failed: tuple[BatchFailure, ...] = ()
