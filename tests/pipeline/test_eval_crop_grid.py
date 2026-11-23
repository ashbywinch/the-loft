"""The crop-grid run's rotated re-read: a failure is a value on the result,
never a silent fallback — the crop's lines are the upright read's, and the
run's report says which crop's re-read did not land, and why.

No model calls: the client is the VLM seam's own `urlopen` injection (DI, never
a monkeypatch) — the upright read lands, the rotated re-read raises.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image

from pipeline.evals.eval_crop_grid import DEFAULT_VISION_OPTIONS, ReadFailure, read_crop, run
from pipeline.evals.eval_geometry import CropReading
from pipeline.layout import Layout
from pipeline.layout_line import LayoutLine
from pipeline.model.ai_client import AIClient
from pipeline.model.config import ModelConfig
from pipeline.model.vlm import VlmError, VlmOptions
from pipeline.store import PipelineStore

# a vertical crop reading: the box is taller than wide (a postcard's message),
# which is what sends the crop to the rotated re-read
VERTICAL = json.dumps({"lines": [{"text": "the postcard's message", "box": [400, 100, 600, 900]}]})


class _Response:
    """The urlopen context-manager shim: one chat-completions body."""

    def __init__(self, content: str) -> None:
        self._body = json.dumps(
            {
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 11},
            }
        ).encode()

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _upright_then(answer: Any, *, dead: bool = True) -> tuple[list[int], Any]:
    """A fake client for one crop: the first call (the upright read) answers
    with the vertical reading, the second (the rotated re-read) either raises
    or answers with *answer* — the only second call a crop ever makes."""
    calls: list[int] = []

    def urlopen(request: Any, timeout: float | None = None) -> _Response:
        calls.append(1)
        if len(calls) == 1:
            return _Response(VERTICAL)
        if dead:
            raise VlmError("the rotated read died")
        return _Response(answer)

    return calls, urlopen


def _options(urlopen: Any) -> VlmOptions:
    return VlmOptions(api_key="test-key", urlopen=urlopen)


def test_the_default_options_are_the_vision_models_gateway_read() -> None:
    """The module's default names the VALUE — the vision model's options at the
    client's gateway endpoint and key — not the crop pipeline step using it."""
    assert DEFAULT_VISION_OPTIONS.model == ModelConfig.VISION_MODEL
    assert DEFAULT_VISION_OPTIONS.endpoint == AIClient.DEFAULT_BASE_URL


def test_a_failed_rotated_re_read_is_surfaced_and_keeps_the_upright_read(tmp_path: Path) -> None:
    """The re-read dies: the crop still reads (the upright lines), and the
    result carries the failure — a caller can tell the page was read
    upright-only and why, instead of the exception vanishing."""
    page = tmp_path / "page.png"
    Image.new("RGB", (100, 100), "white").save(page)
    calls, urlopen = _upright_then(VERTICAL)

    read = read_crop(CropReading(0.0, 0.0, 100.0, 100.0, []), page, tmp_path, 0, _options(urlopen))

    assert len(calls) == 2  # the upright read, then the rotated re-read
    assert read is not None
    assert [line.text for line in read.lines] == ["the postcard's message"]
    assert read.lines[0].orientation == 0  # the upright read's line
    assert read.failure == ReadFailure("call", "VlmError: the rotated read died")


def test_a_rotated_re_read_with_no_usable_lines_is_surfaced_too(tmp_path: Path) -> None:
    """A re-read that answers but measures nothing is the same fallback — the
    upright read stands in, and the result says so rather than reporting a
    rotation that never happened. The answer cost its tokens, so the read's
    cost counts both calls."""
    page = tmp_path / "page.png"
    Image.new("RGB", (100, 100), "white").save(page)
    calls, urlopen = _upright_then(json.dumps({"lines": []}), dead=False)

    read = read_crop(CropReading(0.0, 0.0, 100.0, 100.0, []), page, tmp_path, 0, _options(urlopen))

    assert len(calls) == 2
    assert read is not None
    assert [line.text for line in read.lines] == ["the postcard's message"]
    assert read.failure == ReadFailure("answer", "the rotated read gave no usable lines")
    assert read.tokens == 22  # both calls' tokens — the answer cost them


def test_a_landed_rotated_re_read_replaces_the_upright_read(tmp_path: Path) -> None:
    """The re-read that lands is not a failure: its horizontal reading is the
    crop's, the box is remapped into the crop frame, and both calls' tokens are
    the read's cost."""
    page = tmp_path / "page.png"
    Image.new("RGB", (100, 100), "white").save(page)
    horizontal = json.dumps({"lines": [{"text": "the postcard's message", "box": [100, 400, 900, 600]}]})
    calls, urlopen = _upright_then(horizontal, dead=False)

    read = read_crop(CropReading(0.0, 0.0, 100.0, 100.0, []), page, tmp_path, 0, _options(urlopen))

    assert len(calls) == 2
    assert read is not None
    assert read.failure is None
    assert [line.text for line in read.lines] == ["the postcard's message"]
    assert read.lines[0].orientation == 90  # vertical on the page, read horizontally
    assert read.tokens == 22  # both calls' tokens


def test_the_run_reports_the_failed_re_read(tmp_path: Path) -> None:
    """The end-to-end ledger: the upright read's line reaches the layout, no
    crop failed, and the report names the crop whose rotated re-read did."""
    work_dir = tmp_path / "work"
    oriented = work_dir / "batch-1" / "oriented"
    oriented.mkdir(parents=True)
    Image.new("RGB", (1000, 1000), "white").save(oriented / "p1.jpg")
    layout = Layout(
        page="p1.jpg",
        width=1000,
        height=1000,
        lines=[LayoutLine(index=0, text="a line", box=[100.0, 100.0, 900.0, 200.0], conf=0.99, words=[])],
        unmatched=[],
    )
    PipelineStore(work_dir).write("batch-1/ocr-guess/p1.layout.json", json.dumps(layout.to_dict()))
    calls, urlopen = _upright_then(VERTICAL)

    report = run("batch-1", "p1", work_dir, cols=1, rows=1, options=_options(urlopen))

    assert len(calls) == 2
    assert report.failed_crops == 0
    assert report.re_read_failures == ["crop 0: call: VlmError: the rotated read died"]
    assert report.lines == 1
    assert report.boxless == 0
    assert report.tokens == 11  # the upright read's own — the dead call cost nothing
