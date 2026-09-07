"""The §16.17 single-pass segment stage's contract (tools/segment_page.py):
one multimodal call returns every text segment with verbatim text, its
orientation, and a pixel box — parsed, normalized, and validated
fail-fast. The urlopen seam is injected (DI, never monkeypatch); the
image is a real tiny PNG so the normalization has true dimensions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.segment_page import SegmentPageError, segment_page

_WIDTH, _HEIGHT = 2000, 1000


def _image(tmp_path: Path) -> Path:
    from PIL import Image

    image = tmp_path / "page.png"
    Image.new("L", (_WIDTH, _HEIGHT), 255).save(image)
    return image


def _response(segments: list[dict]) -> bytes:
    body = {"choices": [{"message": {"content": json.dumps({"segments": segments})}, "finish_reason": "stop"}]}
    return json.dumps(body).encode()


def _urlopen_returning(payload: bytes):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self) -> bytes:
            return payload

    def urlopen(req, timeout: float = 0):
        assert req.get_header("Authorization").startswith("Bearer ")
        return _Resp()

    return urlopen


def _captured_requests(payload: bytes):
    seen: list[dict] = []

    def urlopen(req, timeout: float = 0):
        seen.append(json.loads(req.data.decode("utf-8")))

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self) -> bytes:
                return payload

        return _Resp()

    return seen, urlopen


def test_segments_parse_normalize_and_carry_orientation(tmp_path: Path) -> None:
    """A valid response: the text verbatim, the box normalized 0-1000 →
    ORIGINAL-IMAGE PIXELS, the orientation carried through."""
    segments = [
        {"label": "header", "text": "POST CARD.", "orientation": 0, "box_2d": [100, 50, 900, 150]},
        {"label": "note", "text": "sideways message", "orientation": 90, "box_2d": [20, 200, 120, 800]},
    ]
    seen, urlopen = _captured_requests(_response(segments))
    got, usage = segment_page(_image(tmp_path), urlopen=urlopen, api_key="test-key")

    assert [s["text"] for s in got] == ["POST CARD.", "sideways message"]
    assert [s["orientation"] for s in got] == [0, 90]
    # 100/1000 × 2000px = 200px; 50/1000 × 1000px = 50px — the axes scale
    # by their OWN dimension
    assert got[0]["box"] == [200.0, 50.0, 1800.0, 150.0]
    assert got[1]["box"] == [40.0, 200.0, 240.0, 800.0]
    # the image rode the request as a base64 data URL, and the segment
    # prompt asked for the box_2d contract
    user_content = seen[0]["messages"][1]["content"]
    assert user_content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "box_2d" in seen[0]["messages"][0]["content"]


def test_fenced_json_is_stripped(tmp_path: Path) -> None:
    image = _image(tmp_path)
    fenced = (
        "```json\n"
        '{"segments": [{"label": "header", "text": "POST CARD.", "orientation": 0, "box_2d": [10, 10, 90, 90]}]}'
        "\n```"
    )
    payload = json.dumps({"choices": [{"message": {"content": fenced}, "finish_reason": "stop"}]}).encode()
    got, _usage = segment_page(image, urlopen=_urlopen_returning(payload), api_key="test-key")
    assert got[0]["text"] == "POST CARD."


def test_boxes_clamp_to_the_image(tmp_path: Path) -> None:
    """A box poking past the image edge clamps to the border — the
    layout writer refuses out-of-image boxes downstream."""
    segments = [{"label": "header", "text": "POST CARD.", "orientation": 0, "box_2d": [-5, -5, 1005, 1005]}]
    got, _ = segment_page(_image(tmp_path), urlopen=_urlopen_returning(_response(segments)), api_key="test-key")
    assert got[0]["box"] == [0.0, 0.0, 2000.0, 1000.0]


def test_garbage_response_fails_loud(tmp_path: Path) -> None:
    """A response with no segments array raises — fail fast, never skip
    (the fail-fast standard; a silently-skipped segmentation would green
    a pipeline that never ran)."""
    payload = json.dumps({"choices": [{"message": {"content": "I see a postcard."}, "finish_reason": "stop"}]}).encode()
    with pytest.raises(SegmentPageError, match="no JSON"):
        segment_page(_image(tmp_path), urlopen=_urlopen_returning(payload), api_key="test-key")


def test_segment_without_text_fails_loud(tmp_path: Path) -> None:
    segments = [{"label": "header", "text": "", "orientation": 0, "box_2d": [10, 10, 90, 90]}]
    with pytest.raises(SegmentPageError, match="no text"):
        segment_page(_image(tmp_path), urlopen=_urlopen_returning(_response(segments)), api_key="test-key")


def test_unknown_orientation_fails_loud(tmp_path: Path) -> None:
    segments = [{"label": "header", "text": "POST CARD.", "orientation": 45, "box_2d": [10, 10, 90, 90]}]
    with pytest.raises(SegmentPageError, match="0/90/180/270"):
        segment_page(_image(tmp_path), urlopen=_urlopen_returning(_response(segments)), api_key="test-key")


def test_malformed_box_fails_loud(tmp_path: Path) -> None:
    segments = [{"label": "header", "text": "POST CARD.", "orientation": 0, "box_2d": [10, 10]}]
    with pytest.raises(SegmentPageError, match="not \\[x0, y0, x1, y1\\]"):
        segment_page(_image(tmp_path), urlopen=_urlopen_returning(_response(segments)), api_key="test-key")


def _failures() -> list[dict]:
    return [
        {
            "index": 16,
            "text": "£4-0s.",
            "px": [767.6, 94.7, 895.5, 149.9],
            "box_2d": [660.0, 120.0, 770.0, 190.0],
        }
    ]


def _repair_response(relocated: list[dict], not_present: list[int]) -> bytes:
    body = {
        "choices": [
            {
                "message": {"content": json.dumps({"relocated": relocated, "not_present": not_present})},
                "finish_reason": "stop",
            }
        ]
    }
    return json.dumps(body).encode()


def test_repair_prompt_is_deterministic_and_scoped_to_the_failures() -> None:
    """The second pass's prompt is generated from the recorded failure
    facts: the same failure yields the same bytes (deterministic), and
    only the failed lines are named — tokens are not spent re-asking
    about the segments that were already correct (2026-09-07, user)."""
    from tools.segment_page import build_repair_prompt

    prompt = build_repair_prompt(_failures(), 1163, 789)
    assert prompt == build_repair_prompt(_failures(), 1163, 789)
    assert "£4-0s." in prompt
    assert "index 16" in prompt
    assert "[768, 95, 896, 150]" in prompt  # the rejected box, in pixels
    other = build_repair_prompt(
        [{"index": 3, "text": "different line", "px": [0.0, 0.0, 10.0, 10.0], "box_2d": [0.0, 0.0, 1.0, 1.0]}],
        1163,
        789,
    )
    assert "£4-0s." not in other


def test_relocate_segments_normalizes_and_maps_by_index(tmp_path: Path) -> None:
    from tools.segment_page import relocate_segments

    seen, urlopen = _captured_requests(_repair_response([{"index": 16, "box_2d": [500, 250, 600, 300]}], []))
    result = relocate_segments(_image(tmp_path), _failures(), urlopen=urlopen, api_key="test-key")
    # normalized 0-1000 → pixels on the 2000x1000 test image
    assert result["relocated"] == {16: [1000.0, 250.0, 1200.0, 300.0]}
    assert result["not_present"] == []
    # the failure facts ride the user message, not the system prompt
    user_text = seen[0]["messages"][1]["content"][1]["text"]
    assert "£4-0s." in user_text


def test_relocate_segments_fails_loud_on_an_unanswered_index(tmp_path: Path) -> None:
    from tools.segment_page import SegmentPageError, relocate_segments

    urlopen = _urlopen_returning(_repair_response([], []))
    with pytest.raises(SegmentPageError, match="index 16"):
        relocate_segments(_image(tmp_path), _failures(), urlopen=urlopen, api_key="test-key")


def test_relocate_segments_fails_loud_on_a_double_answer(tmp_path: Path) -> None:
    from tools.segment_page import SegmentPageError, relocate_segments

    urlopen = _urlopen_returning(_repair_response([{"index": 16, "box_2d": [1, 2, 3, 4]}], [16]))
    with pytest.raises(SegmentPageError, match="index 16"):
        relocate_segments(_image(tmp_path), _failures(), urlopen=urlopen, api_key="test-key")


def test_relocate_segments_fails_loud_on_a_malformed_box(tmp_path: Path) -> None:
    from tools.segment_page import SegmentPageError, relocate_segments

    urlopen = _urlopen_returning(_repair_response([{"index": 16, "box_2d": [1, 2]}], []))
    with pytest.raises(SegmentPageError, match="not \\[x0, y0, x1, y1\\]"):
        relocate_segments(_image(tmp_path), _failures(), urlopen=urlopen, api_key="test-key")
