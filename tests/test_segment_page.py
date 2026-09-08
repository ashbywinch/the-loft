"""The §16.17 single-pass segment stage's contract (tools/segment_page.py):
one multimodal call returns every text segment with verbatim text, its
orientation, and a pixel box — parsed, normalized, and validated
fail-fast. The urlopen seam is injected (DI, never monkeypatch); the
image is a real tiny PNG so the normalization has true dimensions."""

# lucidlint: ignore-file fakefs fixtures are real tiny PNGs driving PIL's real decoder — the file's stated contract
# lucidlint: ignore-file record-shape the fixtures mirror the model's wire payloads and the stage's group dicts

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw

from tools.gates import validate_layout
from tools.layout_detect import gate_findings
from tools.segment_page import (
    GROUPED_VERIFY_ROUNDS,
    SegmentPageError,
    build_grouped_verify_prompt,
    converge_grouped_layout,
    group_segments,
    measure_group_boxes,
    segment_page,
    verify_grouped_segments,
)
from tools.strip_measure import Extent, Strip

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
            {"text": "alpha", "orientation": 0, "box_px": [200, 275, 800, 550]},
            {"text": "beta", "orientation": 0, "box_px": [200, 2585, 800, 2695]},
        ]
    )
    bottom = _response(
        [
            {"text": "beta", "orientation": 0, "box_px": [200, 440, 600, 660]},
            {"text": "gamma", "orientation": 0, "box_px": [200, 1375, 800, 1650]},
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


def _segments() -> list[dict]:
    """Three reported segments on the 2000x1000 test image."""
    return [
        {"text": "POST CARD.", "orientation": 0, "box": [200.0, 100.0, 800.0, 200.0]},
        {"text": "Cathcart St", "orientation": 0, "box": [1200.0, 300.0, 1800.0, 400.0]},
        {"text": "£4-0s.", "orientation": 0, "box": [1500.0, 90.0, 1750.0, 140.0]},
    ]


def _verify_response(corrections: list[dict], not_present: list[int]) -> bytes:
    body = {
        "choices": [
            {
                "message": {"content": json.dumps({"corrections": corrections, "not_present": not_present})},
                "finish_reason": "stop",
            }
        ]
    }
    return json.dumps(body).encode()


def test_verify_prompt_is_deterministic_and_names_the_segments() -> None:
    from tools.segment_page import build_verify_prompt

    prompt = build_verify_prompt(_segments(), 2000, 1000)
    assert prompt == build_verify_prompt(_segments(), 2000, 1000)
    assert "The page is 2000x1000 px" in prompt
    assert "index 0" in prompt and "£4-0s." in prompt


def test_verify_applies_corrections_and_drops_not_present(tmp_path: Path) -> None:
    from tools.segment_page import verify_segments

    seen, urlopen = _captured_requests(_verify_response([{"index": 1, "box_px": [500, 250, 600, 300]}], [2]))
    segments, usage = verify_segments(_image(tmp_path), _segments(), urlopen=urlopen, api_key="test-key")

    assert [s["text"] for s in segments] == ["POST CARD.", "Cathcart St"]
    # the correction lands in page pixels (grid-read), marked as verified
    assert segments[1]["box"] == [500.0, 250.0, 600.0, 300.0]
    assert segments[1]["box_source"] == "verified"
    # the untouched segment keeps its box and source
    assert segments[0]["box"] == [200.0, 100.0, 800.0, 200.0]
    assert "box_source" not in segments[0]
    # the reported segments ride the user message
    assert "£4-0s." in seen[0]["messages"][1]["content"][1]["text"]
    assert usage.get("total_tokens", 0) >= 0


def test_verify_rejects_an_out_of_range_index(tmp_path: Path) -> None:
    from tools.segment_page import SegmentPageError, verify_segments

    urlopen = _urlopen_returning(_verify_response([{"index": 9, "box_px": [1, 2, 3, 4]}], []))
    with pytest.raises(SegmentPageError, match="index 9"):
        verify_segments(_image(tmp_path), _segments(), urlopen=urlopen, api_key="test-key")


def test_verify_rejects_a_double_answer(tmp_path: Path) -> None:
    from tools.segment_page import SegmentPageError, verify_segments

    urlopen = _urlopen_returning(_verify_response([{"index": 1, "box_px": [1, 2, 3, 4]}], [1]))
    with pytest.raises(SegmentPageError, match="index 1"):
        verify_segments(_image(tmp_path), _segments(), urlopen=urlopen, api_key="test-key")


def test_verify_rejects_a_malformed_box(tmp_path: Path) -> None:
    from tools.segment_page import SegmentPageError, verify_segments

    urlopen = _urlopen_returning(_verify_response([{"index": 1, "box_px": [1, 2]}], []))
    with pytest.raises(SegmentPageError, match="not \\[x0, y0, x1, y1\\]"):
        verify_segments(_image(tmp_path), _segments(), urlopen=urlopen, api_key="test-key")


def test_verify_with_no_segments_makes_no_call(tmp_path: Path) -> None:
    from tools.segment_page import verify_segments

    seen, urlopen = _captured_requests(_verify_response([], []))
    segments, _usage = verify_segments(_image(tmp_path), [], urlopen=urlopen, api_key="test-key")
    assert segments == []
    assert seen == []


# --- The grouping read (strip-grouping-plan slice 2): the measured
# strips are drawn numbered on the page; the model GROUPS the numbered
# pieces into segments and transcribes each group verbatim.


def _strips(count: int) -> list[Strip]:
    """count flat bands in reading order — the measured input."""
    return [
        Strip(number=i, extent=Extent(x0=100.0, y0=100.0 + 40 * i, x1=700.0, y1=104.0 + 40 * i)) for i in range(count)
    ]


# lucidlint: ignore record-shape the grouped contract payload's line entries — the established segment shape
def _grouping_response(lines: list[dict[str, Any]], empty: list[int]) -> bytes:
    # lucidlint: ignore record-shape the OpenAI chat wire shape — same literal as the file's existing _response helper
    body = {
        # lucidlint: ignore record-shape the chat wire shape's fixed message keys
        # lucidlint: ignore record-shape the grouped contract's own wire payload
        "choices": [{"message": {"content": json.dumps({"lines": lines, "empty": empty})}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    return json.dumps(body).encode()


class _Payload:
    """One canned response body served on read — shared by the
    sequence helper so the inline _Resp class stays defined once."""

    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> _Payload:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self.body


def _urlopen_sequence(payloads: list[bytes]):
    seen: list[dict] = []
    calls = {"n": 0}

    def urlopen(req, timeout: float = 0):
        seen.append(json.loads(req.data.decode("utf-8")))
        body = payloads[calls["n"]]
        calls["n"] += 1
        return _Payload(body)

    return seen, urlopen


def test_group_segments_partitions_pieces_into_lines(tmp_path: Path) -> None:
    """The grouping contract: pieces partition into lines with verbatim
    text and reading rotation; the read rides the ANNOTATED page and the
    user message names the batch's pieces."""
    seen, urlopen = _captured_requests(
        _grouping_response(
            [
                {"pieces": [0, 1], "text": "line one verbatim", "orientation": 0},
                {"pieces": [2], "text": "margin note", "orientation": 90},
            ],
            [3],
        )
    )
    groups, dropped, usage = group_segments(_image(tmp_path), _strips(4), tmp_path, urlopen=urlopen, api_key="test-key")

    assert groups == [
        {"pieces": [0, 1], "text": "line one verbatim", "orientation": 0},
        {"pieces": [2], "text": "margin note", "orientation": 90},
    ]
    assert dropped == set()
    assert usage["total_tokens"] == 15  # one grouping call's usage, carried through
    system = seen[0]["messages"][0]["content"]
    assert "MEASURED rectangles" in system and '"empty"' in system
    user = seen[0]["messages"][1]["content"]
    assert user[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "pieces 0..3" in user[1]["text"]


def test_group_segments_refuses_an_unknown_piece(tmp_path: Path) -> None:
    urlopen = _urlopen_returning(_grouping_response([{"pieces": [9], "text": "x", "orientation": 0}], []))
    with pytest.raises(SegmentPageError, match="piece 9"):
        group_segments(_image(tmp_path), _strips(4), tmp_path, urlopen=urlopen, api_key="test-key")


def test_group_segments_refuses_a_piece_claimed_twice(tmp_path: Path) -> None:
    response = _grouping_response(
        [
            {"pieces": [0, 1], "text": "one", "orientation": 0},
            {"pieces": [1, 2], "text": "two", "orientation": 0},
        ],
        [],
    )
    urlopen = _urlopen_returning(response)
    with pytest.raises(SegmentPageError, match="more than one place"):
        group_segments(_image(tmp_path), _strips(4), tmp_path, urlopen=urlopen, api_key="test-key")


def test_group_segments_refuses_an_orientation_outside_the_set(tmp_path: Path) -> None:
    urlopen = _urlopen_returning(_grouping_response([{"pieces": [0], "text": "x", "orientation": 45}], []))
    with pytest.raises(SegmentPageError, match="orientation 45"):
        group_segments(_image(tmp_path), _strips(4), tmp_path, urlopen=urlopen, api_key="test-key")


def test_group_segments_reasks_for_unaccounted_pieces(tmp_path: Path) -> None:
    """A batch with unaccounted pieces gets its ONE re-ask — the
    follow-up names the missing pieces; the complete second answer
    serves clean."""
    payloads = [
        _grouping_response([{"pieces": [0, 1], "text": "one", "orientation": 0}], []),
        _grouping_response(
            [
                {"pieces": [0, 1], "text": "one", "orientation": 0},
                {"pieces": [2], "text": "two", "orientation": 0},
            ],
            [3],
        ),
    ]
    seen, urlopen = _urlopen_sequence(payloads)

    groups, dropped, _usage = group_segments(
        _image(tmp_path), _strips(4), tmp_path, urlopen=urlopen, api_key="test-key"
    )

    assert len(seen) == 2
    assert "2, 3]" in seen[1]["messages"][1]["content"][1]["text"]
    assert [g["text"] for g in groups] == ["one", "two"]
    assert dropped == set()


def test_group_segments_drops_loudly_after_the_reask_fails(tmp_path: Path) -> None:
    """Still unaccounted after the ONE re-ask: the page serves without
    them and the dropped pieces come back named (the ruling, 2026-09-08:
    the user judges from the served pages)."""
    payloads = [
        _grouping_response([{"pieces": [0], "text": "one", "orientation": 0}], []),
        _grouping_response([{"pieces": [0], "text": "one", "orientation": 0}], [1]),
    ]
    seen, urlopen = _urlopen_sequence(payloads)

    groups, dropped, _usage = group_segments(
        _image(tmp_path), _strips(4), tmp_path, urlopen=urlopen, api_key="test-key"
    )

    assert [g["text"] for g in groups] == ["one"]
    assert dropped == {2, 3}


def test_group_segments_batch_ceiling(tmp_path: Path) -> None:
    """More than GROUP_BATCH_PIECES strips: one call per <=50-piece
    batch, each user message naming its own range."""
    payloads = [
        _grouping_response([], list(range(50))),
        _grouping_response([], [50, 51]),
    ]
    seen, urlopen = _urlopen_sequence(payloads)

    groups, dropped, _usage = group_segments(
        _image(tmp_path), _strips(52), tmp_path, urlopen=urlopen, api_key="test-key"
    )

    assert groups == []
    assert dropped == set()
    assert len(seen) == 2
    assert "pieces 0..49" in seen[0]["messages"][1]["content"][1]["text"]
    assert "pieces 50..51" in seen[1]["messages"][1]["content"][1]["text"]


def test_group_segments_empty_text_group_means_no_writing(tmp_path: Path) -> None:
    """An empty-text group IS the model's no-writing verdict: its
    pieces join the empties instead of failing the coverage contract."""
    urlopen = _urlopen_returning(_grouping_response([{"pieces": [0, 1], "text": "", "orientation": 0}], [2, 3]))

    groups, dropped, _usage = group_segments(
        _image(tmp_path), _strips(4), tmp_path, urlopen=urlopen, api_key="test-key"
    )

    assert groups == []
    assert dropped == set()


def test_group_segments_with_no_strips_refuses(tmp_path: Path) -> None:
    seen, urlopen = _captured_requests(_grouping_response([], []))
    with pytest.raises(SegmentPageError, match="no strips"):
        group_segments(_image(tmp_path), [], tmp_path, urlopen=urlopen, api_key="test-key")
    assert seen == []


# --- Slice 3: each group's box is the ink projection of its band —
# never the union of the model's listed pieces.


def test_measure_group_boxes_projects_the_ink(tmp_path: Path) -> None:
    """The group's box is the INK inside its pieces' band: ink outside
    the band never leaks in, and the model's under-listed pieces cannot
    shrink the box (the band measurement is immune)."""
    page = tmp_path / "page.png"
    img = Image.new("L", (1000, 500), 255)
    ImageDraw.Draw(img).rectangle((200, 100, 800, 140), fill=0)  # the line's ink
    ImageDraw.Draw(img).rectangle((200, 300, 800, 340), fill=0)  # another line below the band
    img.save(page)
    strips = [Strip(number=0, extent=Extent(x0=100.0, y0=95.0, x1=900.0, y1=145.0))]
    groups = [{"pieces": [0], "text": "the line verbatim", "orientation": 0}]

    segments = measure_group_boxes(page, groups, strips)

    assert segments[0]["box"] == [200.0, 100.0, 801.0, 141.0]  # PIL rectangles are endpoint-inclusive
    assert segments[0]["orientation"] == 0
    assert segments[0]["text"] == "the line verbatim"


def test_measure_group_boxes_serves_a_rotated_group(tmp_path: Path) -> None:
    """The same projection serves a quarter-turn group: the vertical
    message's ink fixes a tall-narrow box (the Godolphin acceptance's
    geometry)."""
    page = tmp_path / "page.png"
    img = Image.new("L", (500, 1000), 255)
    ImageDraw.Draw(img).rectangle((100, 200, 140, 800), fill=0)
    img.save(page)
    strips = [Strip(number=0, extent=Extent(x0=90.0, y0=150.0, x1=150.0, y1=850.0, orientation=270))]
    groups = [{"pieces": [0], "text": "side message", "orientation": 270}]

    segments = measure_group_boxes(page, groups, strips)

    assert segments[0]["box"] == [100.0, 200.0, 141.0, 801.0]  # PIL rectangles are endpoint-inclusive
    assert segments[0]["orientation"] == 270


def test_measure_group_boxes_keeps_the_band_when_blank(tmp_path: Path) -> None:
    """A band with no ink comes back as the measured band — the gates
    judge it downstream, never a silent guess."""
    page = tmp_path / "page.png"
    Image.new("L", (1000, 500), 255).save(page)
    strips = [Strip(number=0, extent=Extent(x0=100.0, y0=95.0, x1=900.0, y1=145.0))]
    groups = [{"pieces": [0], "text": "ghost line", "orientation": 0}]

    segments = measure_group_boxes(page, groups, strips)

    assert segments[0]["box"] == [100.0, 95.0, 900.0, 145.0]


def test_the_grouped_layout_passes_the_gates(tmp_path: Path) -> None:
    """The plan's acceptance, pinned: a grouped page's layout passes
    validate_layout with 0 violations — every line's box measured from
    its own band's ink (the spike's 0-violation result, on synthetic
    ground — the real letter's text never enters the repo)."""
    page = tmp_path / "page.png"
    img = Image.new("L", (1000, 500), 255)
    draw = ImageDraw.Draw(img)
    draw.rectangle((100, 50, 700, 90), fill=0)  # line 1's ink
    draw.rectangle((100, 150, 600, 190), fill=0)  # line 2's ink
    img.save(page)
    strips = [
        Strip(number=0, extent=Extent(x0=90.0, y0=40.0, x1=800.0, y1=100.0)),
        Strip(number=1, extent=Extent(x0=90.0, y0=140.0, x1=800.0, y1=200.0)),
    ]
    groups = [
        {"pieces": [0], "text": "the first line of writing", "orientation": 0},
        {"pieces": [1], "text": "the second line of writing", "orientation": 0},
    ]

    segments = measure_group_boxes(page, groups, strips)
    # lucidlint: ignore record-shape the stored layout shape the gates and the review surface read
    layout = {"page": "page.png", "width": 1000, "height": 500, "lines": segments, "unmatched": []}

    assert validate_layout(layout) == []


# --- Slice 4: the bounded findings loop — gates → findings → one
# verification round, twice; still violated, the page refuses honestly.


_LONG_TEXT = "word " * 40  # 200 chars — wildly out of sync with a small band
_SHORT_TEXT = "a short line of writing"


def _loop_page(tmp_path: Path) -> Path:
    """Three ink bands the loop's synthetic violations live on."""
    page = tmp_path / "page.png"
    img = Image.new("L", (1000, 500), 255)
    draw = ImageDraw.Draw(img)
    for top in (50, 150, 250):
        draw.rectangle((100, top, 300, top + 40), fill=0)
    img.save(page)
    return page


def _loop_strips() -> list[Strip]:
    return [
        Strip(number=0, extent=Extent(x0=95.0, y0=45.0, x1=310.0, y1=95.0)),
        Strip(number=1, extent=Extent(x0=95.0, y0=145.0, x1=310.0, y1=195.0)),
        Strip(number=2, extent=Extent(x0=95.0, y0=245.0, x1=310.0, y1=295.0)),
    ]


def _loop_groups() -> list[dict[str, Any]]:
    return [
        {"pieces": [0], "text": _LONG_TEXT + " one", "orientation": 0},
        {"pieces": [1], "text": _LONG_TEXT + " two", "orientation": 0},
        {"pieces": [2], "text": _LONG_TEXT + " three", "orientation": 0},
    ]


def _grouped_verify_response(corrections: list[dict], not_present: list[int]) -> bytes:
    body = {
        "choices": [
            {
                "message": {"content": json.dumps({"corrections": corrections, "not_present": not_present})},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    return json.dumps(body).encode()


def test_build_grouped_verify_prompt_is_deterministic() -> None:
    segments = [
        {"label": "line", "text": "one line", "orientation": 0, "box": [1.0, 1.0, 2.0, 2.0], "pieces": [0]},
        {"label": "line", "text": "two line", "orientation": 0, "box": [1.0, 3.0, 2.0, 4.0], "pieces": [1]},
    ]
    errors = {1: "the checker measured: length"}

    first = build_grouped_verify_prompt(segments, errors)
    second = build_grouped_verify_prompt(segments, errors)

    assert first == second
    assert "CHECK FAILED: the checker measured: length" in first
    assert "index 1" in first and "pieces [1]" in first


def test_verify_grouped_segments_corrects_and_drops(tmp_path: Path) -> None:
    """The round returns corrections keyed by index and not-present
    indexes; a correction carries pieces + words, never a box."""
    seen, urlopen = _captured_requests(
        _grouped_verify_response([{"index": 1, "pieces": [1], "text": "fixed", "orientation": 0}], [2])
    )
    page = _loop_page(tmp_path)
    segments = measure_group_boxes(page, _loop_groups(), _loop_strips())

    corrections, dropped, usage = verify_grouped_segments(
        page, _loop_strips(), segments, tmp_path, findings={1: "CHECK FAILED: x"}, urlopen=urlopen, api_key="test-key"
    )

    assert corrections == {1: {"pieces": [1], "text": "fixed", "orientation": 0}}
    assert dropped == {2}
    assert usage["total_tokens"] == 15
    assert "CHECK FAILED: x" in seen[0]["messages"][1]["content"][1]["text"]
    assert seen[0]["messages"][1]["content"][0]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_verify_grouped_segments_refuses_unknown_pieces(tmp_path: Path) -> None:
    urlopen = _urlopen_returning(
        _grouped_verify_response([{"index": 0, "pieces": [99], "text": "x", "orientation": 0}], [])
    )
    page = _loop_page(tmp_path)
    segments = measure_group_boxes(page, _loop_groups(), _loop_strips())

    with pytest.raises(SegmentPageError, match="unknown piece 99"):
        verify_grouped_segments(
            page, _loop_strips(), segments, tmp_path, findings={0: "f"}, urlopen=urlopen, api_key="test-key"
        )


def test_converge_grouped_layout_converges_three_to_zero(tmp_path: Path) -> None:
    """The spike's trajectory, pinned: three gate violations, the first
    verification round fixes two, the second fixes the last — within
    the bound the page serves with every gate clean."""
    page = _loop_page(tmp_path)
    groups = _loop_groups()
    segments = measure_group_boxes(page, groups, _loop_strips())
    payloads = [
        _grouped_verify_response(
            [
                {"index": 0, "pieces": [0], "text": _SHORT_TEXT + " one", "orientation": 0},
                {"index": 1, "pieces": [1], "text": _SHORT_TEXT + " two", "orientation": 0},
            ],
            [],
        ),
        _grouped_verify_response([{"index": 2, "pieces": [2], "text": _SHORT_TEXT + " three", "orientation": 0}], []),
    ]
    seen, urlopen = _urlopen_sequence(payloads)

    final, usage = converge_grouped_layout(
        page,
        _loop_strips(),
        groups,
        segments,
        tmp_path,
        findings_fn=gate_findings,
        urlopen=urlopen,
        api_key="test-key",
    )

    assert len(seen) == GROUPED_VERIFY_ROUNDS  # the bound held: two rounds
    assert usage["total_tokens"] == 30
    # lucidlint: ignore record-shape the stored layout shape the gates and the review surface read
    layout = {
        "page": "page.png",
        "width": 1000,
        "height": 500,
        "lines": [{"index": i, **s} for i, s in enumerate(final)],
        "unmatched": [],
    }
    assert validate_layout(layout) == []


def test_converge_grouped_layout_refuses_when_it_never_converges(tmp_path: Path) -> None:
    """Still violated after the bound: the page refuses honestly, the
    surviving violations named in the error."""
    page = _loop_page(tmp_path)
    groups = _loop_groups()
    segments = measure_group_boxes(page, groups, _loop_strips())
    payloads = [_grouped_verify_response([], [])] * GROUPED_VERIFY_ROUNDS  # the model never fixes anything
    seen, urlopen = _urlopen_sequence(payloads)

    with pytest.raises(SegmentPageError, match="still fails the gates"):
        converge_grouped_layout(
            page,
            _loop_strips(),
            groups,
            segments,
            tmp_path,
            findings_fn=gate_findings,
            urlopen=urlopen,
            api_key="test-key",
        )

    assert len(seen) == GROUPED_VERIFY_ROUNDS  # bounded: no endless re-asking
