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


def _two_pass_page(tmp_path: Path) -> Path:
    from PIL import Image

    image = tmp_path / "tall.png"
    Image.new("L", (2000, 5000), 255).save(image)
    return image


def _two_call_segment_urlopen(payloads: list[bytes]):
    seen: list[dict] = []
    state = {"n": 0}

    def urlopen(req, timeout: float = 0):
        seen.append(json.loads(req.data.decode("utf-8")))
        payload = payloads[min(state["n"], len(payloads) - 1)]
        state["n"] += 1

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self) -> bytes:
                return payload

        return _Resp()

    return seen, urlopen


def test_two_pass_threshold_routes_by_aspect(tmp_path: Path) -> None:
    """The two-pass read is for portrait sheets — the model's full-page
    box placement degrades down a tall page (the crop-grid finding);
    small cards read whole, so no tokens are spent re-asking (L10)."""
    from PIL import Image

    from tools.segment_page import page_needs_two_pass

    tall = tmp_path / "tall.png"
    Image.new("L", (2544, 4642), 255).save(tall)
    wide = tmp_path / "wide.png"
    Image.new("L", (1163, 789), 255).save(wide)
    square = tmp_path / "square.png"
    Image.new("L", (1000, 1000), 255).save(square)
    assert page_needs_two_pass(tall) is True
    assert page_needs_two_pass(wide) is False
    assert page_needs_two_pass(square) is False


def test_two_pass_stitches_halves_and_dedupes_the_band(tmp_path: Path) -> None:
    """Each half's boxes come back in the HALF's pixels and must land in
    the page frame; a line the overlap band read twice is kept once —
    by region overlap, or by equal text when the cut shifted the box."""
    from tools.segment_page import segment_page_two_pass

    # page 2000x5000: top half is y 0-2750, bottom half y 2250-5000,
    # each half 2000x2750
    top = _response(
        [
            {"text": "alpha", "orientation": 0, "box_2d": [100, 100, 400, 200]},
            {"text": "beta", "orientation": 0, "box_2d": [100, 940, 400, 980]},
        ]
    )
    bottom = _response(
        [
            # the band's line read again, box shifted — same words, tiny overlap
            {"text": "beta", "orientation": 0, "box_2d": [100, 160, 400, 240]},
            {"text": "gamma", "orientation": 0, "box_2d": [100, 500, 400, 600]},
        ]
    )
    seen, urlopen = _two_call_segment_urlopen([top, bottom])
    segments, _usage = segment_page_two_pass(_two_pass_page(tmp_path), urlopen=urlopen, api_key="test-key")

    assert [s["text"] for s in segments] == ["alpha", "beta", "gamma"]
    # alpha: the top half's pixels ARE page pixels
    assert segments[0]["box"] == [200.0, 275.0, 800.0, 550.0]
    # beta: kept from the TOP read, in page pixels
    assert segments[1]["box"] == [200.0, 2585.0, 800.0, 2695.0]
    # gamma: the bottom half's box shifted by the half's offset (2250)
    assert segments[2]["box"] == [200.0, 1375.0 + 2250.0, 800.0, 1650.0 + 2250.0]
    assert len(seen) == 2


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
