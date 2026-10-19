"""The review's verdict on one proposed person.

The verdict is the archive's answer to a review disposition: the record as
it now stands (or the gone marker a delete leaves), whether the
disposition altered anything, and whether the person was still proposed
when the mutation took hold — both flags are set INSIDE the archive's
lock, in the mutation itself, so a concurrent duplicate decision cannot
misread them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from tools.gone_person import GonePerson

if TYPE_CHECKING:
    from tools.records import Person


@dataclass(frozen=True)
class Resolution:
    """The verdict on one proposed person: the record (None when a duplicate
    delete leaves nothing), whether the table changed, and whether the
    person was still proposed at mutation time."""

    person: Person | GonePerson | None = None
    changed: bool = False
    attested: bool = False
