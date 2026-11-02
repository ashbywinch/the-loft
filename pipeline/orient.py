"""Orientation: turning a page's text upright.

Scans arrive rotated — a sheet fed sideways, a postcard photographed across the
table. The page is turned before anything is read, and the turning is the
vision model's answer: one small call per page, thinking off, naming the
clockwise rotation that puts the text upright.

(The earlier arbiter read each page four times with tesseract and kept the read
with the most strong words. The VLM is the only reader now, so it answers the
orientation too: a second OCR engine existed only for this and the density
route, and both are gone.)
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image

from pipeline.model.config import VISION_MODEL
from pipeline.model.vlm import VlmError, extract_json, transcribe_image_vlm

ROTATIONS = (0, 90, 180, 270)

_PROMPT = (
    "This is a scanned document page. Which CLOCKWISE rotation makes its text stand "
    'upright? Reply with JSON only: {"rotate": 0|90|180|270}. 0 means it is already '
    "upright (a photo of a page lying flat counts as upright). If the page carries "
    "text in more than one direction, answer for the dominant block."
)


def page_rotation(image: Path, *, model: str = VISION_MODEL, urlopen: Any = None) -> int:
    """The clockwise rotation (0/90/180/270) that makes the page's text upright."""
    answer = transcribe_image_vlm(
        image,
        model=model,
        system="You orient scanned document pages.",
        user_text=_PROMPT,
        max_tokens=500,
        urlopen=urlopen,
    )
    data = extract_json(answer.answer)
    if not isinstance(data, dict) or "rotate" not in data:
        raise VlmError(f"no rotation in the model's answer: {answer.answer[:120]!r}")
    rotate = int(data["rotate"])
    if rotate not in ROTATIONS:
        raise VlmError(f"unusable rotation: {answer.answer[:120]!r}")
    return rotate


def orient_pages(
    pages: list[Path],
    out_dir: Path,
    *,
    rotation: Callable[[Path], int] | None = None,
) -> list[Path]:
    """Write each page into ``out_dir`` with its text upright, and return the
    written paths, in the input order.

    ``rotation`` is the test seam (a callable page → degrees); the default asks
    the vision model. An unanswerable page is an error, never a guess: a wrong
    rotation is worse than a stopped pass."""
    ask = rotation if rotation is not None else page_rotation
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for page in pages:
        degrees = ask(page)
        with Image.open(page) as image:
            turned = image.rotate(-degrees, expand=True) if degrees else image.copy()
        target = out_dir / page.name
        turned.save(target, quality=92)
        written.append(target)
    return written
