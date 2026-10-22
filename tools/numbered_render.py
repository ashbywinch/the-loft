"""The numbered image and the chips placed on it.

`render_numbered` composes stages 1-3 and hands back the pair the caller
draws with and reports from: the rendered section and the chips it carries
(the unplaced ones among them, which the caller reports loudly).
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from tools.chip import Chip


@dataclass(frozen=True)
class NumberedRender:
    """A rendered numbered section and the chips on it."""

    image: Image.Image
    chips: list[Chip]
