"""Orientation: the page turned upright by the vision model's answer.

The old arbiter read every page four times with tesseract and kept the read with
the most strong words. The VLM names the rotation now, one call per page."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from pipeline.model.vlm import VlmError
from pipeline.orient import PageOrientation


def _page(tmp_path: Path, size: tuple[int, int] = (60, 40)) -> Path:
    image = Image.new("RGB", size, (255, 255, 255))
    path = tmp_path / "p.jpg"
    image.save(path, quality=90)
    return path


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _answer(content: str) -> bytes:
    import json

    return json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}).encode()


def test_the_rotation_is_the_models_answer(tmp_path: Path) -> None:
    page = _page(tmp_path)
    assert PageOrientation.rotation(page, urlopen=lambda *a, **k: _Response(_answer('{"rotate": 90}'))) == 90


def test_an_unusable_answer_is_refused(tmp_path: Path) -> None:
    page = _page(tmp_path)
    with pytest.raises(VlmError):
        PageOrientation.rotation(page, urlopen=lambda *a, **k: _Response(_answer('{"rotate": 45}')))
    with pytest.raises(VlmError):
        PageOrientation.rotation(page, urlopen=lambda *a, **k: _Response(_answer("upright, I think")))


def test_orient_pages_turns_each_page_and_keeps_its_name(tmp_path: Path) -> None:
    page = _page(tmp_path)
    out = tmp_path / "oriented"
    written = PageOrientation.pages([page], out, rotation=lambda _p: 90)
    assert [p.name for p in written] == ["p.jpg"]
    with Image.open(written[0]) as turned:
        # a 60x40 page rotated 90 degrees is 40x60
        assert (turned.width, turned.height) == (40, 60)


def test_an_upright_page_is_copied_not_turned(tmp_path: Path) -> None:
    page = _page(tmp_path)
    written = PageOrientation.pages([page], tmp_path / "oriented", rotation=lambda _p: 0)
    with Image.open(written[0]) as same:
        assert (same.width, same.height) == (60, 40)
