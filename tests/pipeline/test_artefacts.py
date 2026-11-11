"""The review surface's view image: one cached WebP per page, rebuilt when
the page changes."""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image

from pipeline.artefacts import BatchArtefacts


def _source(tmp_path: Path, colour: tuple[int, int, int] = (200, 180, 150)) -> Path:
    source = BatchArtefacts(tmp_path, "b").oriented("p1.jpg")
    source.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2600, 4000), colour).save(source, "JPEG")
    return source


def test_view_image_is_webp_at_the_page_dimensions(tmp_path: Path) -> None:
    batch = BatchArtefacts(tmp_path, "b")
    _source(tmp_path)
    view = batch.view_image("p1.jpg")
    assert view == batch.view("p1.jpg")
    assert view.suffix == ".webp"
    with Image.open(view) as image:
        assert image.size == (2600, 4000)
    first = view.stat().st_mtime_ns
    assert batch.view_image("p1.jpg") == view
    assert view.stat().st_mtime_ns == first  # cached, not re-rendered


def test_view_image_rebuilds_when_the_source_changes(tmp_path: Path) -> None:
    batch = BatchArtefacts(tmp_path, "b")
    source = _source(tmp_path)
    view = batch.view_image("p1.jpg")
    first = view.stat().st_mtime_ns
    _source(tmp_path, colour=(10, 20, 30))
    os.utime(source, ns=(first + 1_000_000, first + 1_000_000))
    rebuilt = batch.view_image("p1.jpg")
    assert rebuilt.stat().st_mtime_ns != first


def test_view_image_applies_exif_orientation(tmp_path: Path) -> None:
    batch = BatchArtefacts(tmp_path, "b")
    source = batch.oriented("phone.jpg")
    source.parent.mkdir(parents=True, exist_ok=True)
    exif = Image.Exif()
    exif[274] = 6  # rotate 90 CW on display
    Image.new("RGB", (400, 800), (200, 180, 150)).save(source, "JPEG", exif=exif)
    with Image.open(batch.view_image("phone.jpg")) as view:
        assert view.size == (800, 400)
