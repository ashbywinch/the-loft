"""The SANE source each scan mode reads from.

The FF-680W's single sheet-fed ADF handles letters and photos alike, so both
modes read the ADF duplex source; a device that exposes a photo-specific
source gives that mode its own value here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModeSources:
    """The SANE source each scan mode reads from."""

    _ADF_SOURCE = "ADF Duplex"  # the FF-680W's source — one ADF for letters and photos

    docs: str = _ADF_SOURCE
    photos: str = _ADF_SOURCE

    def for_mode(self, mode: str) -> str:
        """The source the named mode scans from."""
        match mode:
            case "docs":
                return self.docs
            case "photos":
                return self.photos
            case _:
                raise KeyError(mode)
