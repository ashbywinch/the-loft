"""How two row engines' boxes differ over one band of the page: the extra boxes
the second engine makes that the first does not, then the second's own count.

The band a zoom shows is chosen where the two engines part company most, so every
candidate band is compared by this pair. It is ordered by the extra count first
and the second engine's own count second — the tie-break, because the busier band
is the better place to look — exactly as the bare pair it replaces was.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class BoxDifference:
    """One band's box counts, as the comparison reads them: the boxes the second
    engine makes there that the first does not, then the second's own count."""

    extra: int
    boxes: int
