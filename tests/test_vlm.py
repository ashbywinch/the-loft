"""tools/vlm.py — the vision-model seam: the context the transcription
reads with, and the self-report flag pass (2026-08-15, user-approved: the
transcription model's own doubt is the flag source)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

import tools.vlm as vlm
from tools.vlm import VlmError, _extract_json, selfreport_words, transcription_system_with_context


class TestTranscriptionSystemWithContext:
    def test_base_verbatim_discipline(self) -> None:
        system = transcription_system_with_context()
        assert "verbatim" in system
        assert "nothing added, nothing removed" in system

    def test_context_rides_the_prompt(self) -> None:
        system = transcription_system_with_context(
            people=["Alex Hale"], places=["Kensington Gore"], label="First pile", previous_page="Chère Maman."
        )
        assert "Alex Hale" in system
        assert "Kensington Gore" in system
        assert "First pile" in system
        assert "Chère Maman." in system

    def test_no_optional_parts(self) -> None:
        # an empty places list still names it explicitly ("none") so the
        # model knows the absence is deliberate
        system = transcription_system_with_context(people=["Alex"], places=[], label=None)
        assert "Known places: none" in system


class TestExtractJson:
    def test_plain(self) -> None:
        assert _extract_json('{"unsure": [{"line": 1, "word": "x"}]}') == {"unsure": [{"line": 1, "word": "x"}]}

    def test_code_fence(self) -> None:
        # the probe's model wrapped its answer in a fence — tolerate it
        assert _extract_json('```json\n{"unsure": []}\n```') == {"unsure": []}

    def test_trailing_prose(self) -> None:
        assert _extract_json('Here you go:\n{"unsure": []}\nHope that helps') == {"unsure": []}

    def test_garbage_raises(self) -> None:
        with pytest.raises(VlmError):
            _extract_json("I could not read the page at all")


class TestSelfreportWords:
    def test_validates_and_returns_the_unsure_list(self) -> None:
        def fake(image, *, system, user_text):
            assert "line one\n2| line two" in user_text  # the guess is numbered for citing
            assert "known family people" in system.lower() or "known people" in system.lower()
            return json.dumps({"unsure": [{"line": 2, "word": "doubtful"}, {"line": 1, "word": "one"}]}), {}

        result = selfreport_words(
            __import__("pathlib").Path("p.jpg"),
            "line one\nline two",
            people=["Alex"],
            transcribe=fake,
        )
        assert result == [{"line": 2, "word": "doubtful"}, {"line": 1, "word": "one"}]

    def test_junk_entries_dropped(self) -> None:
        def fake(image, *, system, user_text):
            return json.dumps(
                {"unsure": [{"line": "x", "word": "bad"}, {"line": 3, "word": ""}, {"word": "no-line"}]}
            ), {}

        result = selfreport_words(__import__("pathlib").Path("p.jpg"), "one\ntwo\nthree", transcribe=fake)
        assert result == []


class TestParseTranscriptionResponse:
    def test_json_with_boxes(self) -> None:
        from tools.vlm import parse_transcription_response

        text = json.dumps(
            {
                "lines": [
                    {"text": "piano-practising facilities. At the", "box": [219, 496, 760, 526]},
                    {"text": "moment it looks awfully complicated,", "box": [234, 513, 733, 543]},
                ]
            }
        )
        plain, boxes = parse_transcription_response(text)
        assert plain == "piano-practising facilities. At the\nmoment it looks awfully complicated,"
        assert boxes == {0: [219.0, 496.0, 760.0, 526.0], 1: [234.0, 513.0, 733.0, 543.0]}

    def test_fence_and_prose_tolerated(self) -> None:
        from tools.vlm import parse_transcription_response

        text = '```json\n{"lines": [{"text": "line one", "box": [1, 2, 3, 4]}]}\n```\nHope that helps'
        plain, boxes = parse_transcription_response(text)
        assert plain == "line one"
        assert boxes == {0: [1.0, 2.0, 3.0, 4.0]}

    def test_plain_text_falls_back(self) -> None:
        from tools.vlm import parse_transcription_response

        plain, boxes = parse_transcription_response("Chère Maman.\nline two")
        assert plain == "Chère Maman.\nline two"
        assert boxes is None  # no geometry — the detector association fills it

    def test_blank_lines_skipped_keep_indexes_aligned(self) -> None:
        from tools.vlm import parse_transcription_response

        text = json.dumps(
            {
                "lines": [
                    {"text": "first", "box": [0, 0, 10, 10]},
                    {"text": "", "box": [0, 0, 10, 10]},  # blank — the .txt split skips it too
                    {"text": "third", "box": [20, 20, 30, 30]},
                ]
            }
        )
        plain, boxes = parse_transcription_response(text)
        assert plain == "first\nthird"
        assert boxes == {0: [0.0, 0.0, 10.0, 10.0], 1: [20.0, 20.0, 30.0, 30.0]}

    def test_missing_or_bad_boxes_dropped_geometry(self) -> None:
        from tools.vlm import parse_transcription_response

        text = json.dumps({"lines": [{"text": "no box"}, {"text": "bad box", "box": "x"}]})
        plain, boxes = parse_transcription_response(text)
        assert plain == "no box\nbad box"
        assert boxes is None

    def test_garbage_is_plain_text(self) -> None:
        from tools.vlm import parse_transcription_response

        plain, boxes = parse_transcription_response("I could not read the page")
        assert plain == "I could not read the page"
        assert boxes is None

    def test_collapsed_bottom_boxes_dropped(self) -> None:
        from tools.vlm import parse_transcription_response

        text = json.dumps(
            {
                "lines": [
                    {"text": "normal line", "box": [10, 10, 900, 100]},  # height 90
                    {"text": "another", "box": [10, 110, 900, 200]},  # height 90
                    {"text": "bottom collapsed", "box": [10, 998, 900, 1000]},  # the 2px sliver
                ]
            }
        )
        plain, boxes = parse_transcription_response(text)
        assert plain == "normal line\nanother\nbottom collapsed"
        # the sliver is < a third of the median height — dropped, the line
        # falls back to the detector's association
        assert boxes == {0: [10.0, 10.0, 900.0, 100.0], 1: [10.0, 110.0, 900.0, 200.0]}


class TestTranscriptionProblem:
    """Why a transcription response cannot build a layout — the retry
    ladder's decision (2026-08-25: page-02 emitted the same raw-JSON
    prefix in two separate runs; empty content and truncated JSON are
    both the reasoning budget eating the completion)."""

    def test_plain_text_has_no_problem(self) -> None:
        from tools.vlm import transcription_problem

        assert transcription_problem("Dear Mum,\nI hope you are well.") is None

    def test_blank_is_a_problem(self) -> None:
        from tools.vlm import transcription_problem

        assert transcription_problem("") is not None
        assert transcription_problem("   \n  ") is not None

    def test_json_in_the_requested_structure_is_fine(self) -> None:
        from tools.vlm import transcription_problem

        text = '{"lines": [{"text": "line one", "box": [0, 0, 1000, 100]}]}'
        assert transcription_problem(text) is None

    def test_unparseable_json_echo_is_a_problem(self) -> None:
        # the observed refusal: '{"lines": [{"text": ' as the whole first
        # line — the model wrote the format instead of transcribing
        from tools.vlm import transcription_problem

        assert transcription_problem('{"lines": [{"text": "unterminated') is not None

    def test_json_without_the_lines_structure_is_a_problem(self) -> None:
        from tools.vlm import transcription_problem

        assert transcription_problem('{"error": "cannot read"}') is not None


class TestPlainTranscriptionFormat:
    """The no-boxes prompt variant (2026-08-25): the ink-column pipeline
    measures geometry from the rec's ink; asking this pipeline's model
    for JSON boxes costs tokens (the budget the reasoning eats) and hands
    it a structure to fail mid-echoing."""

    def test_plain_variant_requests_plain_text(self) -> None:
        from tools.vlm import transcription_system_with_context

        system = transcription_system_with_context(request_boxes=False)
        assert "plain text" in system
        assert '"lines"' not in system
        assert "NORMALIZED" not in system

    def test_plain_variant_keeps_the_reading_discipline(self) -> None:
        from tools.vlm import transcription_system_with_context

        system = transcription_system_with_context(request_boxes=False, people=["Alex Hale"], label="First pile")
        assert "verbatim" in system
        assert "~~word~~" in system  # strike markers are content
        assert "Alex Hale" in system  # context still rides along

    def test_default_still_requests_boxes(self) -> None:
        from tools.vlm import VLM_SYSTEM, transcription_system_with_context

        # every existing caller keeps today's behaviour
        assert '"lines"' in VLM_SYSTEM
        assert '"lines"' in transcription_system_with_context()


class TestTranscribeWithFallbacks:
    """The escalation ladder: each variant is one transcribe_image_vlm
    call spec; the first usable response wins; reasons print to stderr;
    an all-unusable run returns the LAST response (the gates refuse it)
    while an all-error run re-raises."""

    def test_first_usable_response_wins(self, monkeypatch) -> None:
        from tools.vlm import transcribe_with_fallbacks

        responses = [("good text", {"total_tokens": 10}), ("never reached", {"total_tokens": 99})]
        calls: list[dict] = []

        def fake(image, **kwargs):
            calls.append(kwargs)
            return responses.pop(0)

        text, usage = transcribe_with_fallbacks(Path("x.png"), [{"model": "a"}, {"model": "b"}], transcribe=fake)
        assert text == "good text"
        assert usage["total_tokens"] == 10
        assert len(calls) == 1

    def test_unusable_response_falls_through_to_the_next_variant(self, monkeypatch) -> None:
        from tools.vlm import transcribe_with_fallbacks

        responses = [('{"lines": [{"text": "unterminated', {"total_tokens": 10}), ("good text", {"total_tokens": 20})]
        calls: list[dict] = []

        def fake(image, **kwargs):
            calls.append(kwargs)
            return responses.pop(0)

        text, usage = transcribe_with_fallbacks(Path("x.png"), [{"model": "a"}, {"model": "a"}], transcribe=fake)
        assert text == "good text"
        assert len(calls) == 2

    def test_call_error_falls_through_to_the_next_variant(self, monkeypatch) -> None:
        from tools.vlm import transcribe_with_fallbacks

        calls: list[dict] = []

        def fake(image, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise RuntimeError("vision model returned empty content")
            return "recovered", {"total_tokens": 5}

        text, _usage = transcribe_with_fallbacks(Path("x.png"), [{"model": "a"}, {"model": "a"}], transcribe=fake)
        assert text == "recovered"

    def test_all_attempts_error_reraises_the_last(self) -> None:
        from tools.vlm import transcribe_with_fallbacks

        def fake(image, **kwargs):
            raise RuntimeError("timeout")

        with pytest.raises(RuntimeError):
            transcribe_with_fallbacks(Path("x.png"), [{"model": "a"}, {"model": "b"}], transcribe=fake)

    def test_all_unusable_returns_the_last_response_for_the_gates(self, monkeypatch) -> None:
        from tools.vlm import transcribe_with_fallbacks

        blob = '{"lines": [{"text": "unterminated'
        responses = [(blob, {"total_tokens": 10}), (blob, {"total_tokens": 20})]
        calls: list[dict] = []

        def fake(image, **kwargs):
            calls.append(kwargs)
            return responses.pop(0)

        text, usage = transcribe_with_fallbacks(Path("x.png"), [{"model": "a"}, {"model": "b"}], transcribe=fake)
        assert text == blob
        assert usage["total_tokens"] == 30  # honest cost: both attempts

    def test_each_attempt_reason_is_logged(self, monkeypatch, capsys) -> None:
        from tools.vlm import transcribe_with_fallbacks

        responses = [("", {"total_tokens": 1}), ("good", {"total_tokens": 2})]
        calls: list[dict] = []

        def fake(image, **kwargs):
            calls.append(kwargs)
            return responses.pop(0)

        transcribe_with_fallbacks(Path("page.png"), [{"model": "a"}, {"model": "a"}], transcribe=fake)
        err = capsys.readouterr().err
        assert "attempt 1/2" in err
        assert "page.png" in err


class _BytesResponse:
    """The urlopen context-manager shim returning fixed bytes (DI, 2026-08-30)."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _BytesResponse:
        return self

    def __exit__(self, *a: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


class TestThinkingDisabled:
    """The transcription is an extraction task, not a judgment — thinking
    is disabled and a model that rejects the param gets one retry without
    it (the AIClient house pattern; 2026-08-30: the CI's postcard eval
    burned 64K tokens of reasoning with zero content)."""

    @staticmethod
    def _png(tmp_path: Path) -> Path:
        p = tmp_path / "p.png"
        p.write_bytes(b"\x89PNG fake bytes")
        return p

    @staticmethod
    def _ok_body(content: str = "transcribed line") -> dict:
        return {
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"completion_tokens": 7},
        }

    def test_payload_disables_thinking(self, tmp_path: Path) -> None:
        captured: dict = {}

        body = json.dumps(TestThinkingDisabled._ok_body()).encode()

        def fake_urlopen(request, timeout=None):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return _BytesResponse(body)

        vlm.transcribe_image_vlm(
            self._png(tmp_path), model="dynamic/image", base_url="http://x/v1", api_key="k", urlopen=fake_urlopen
        )
        assert captured["payload"]["thinking"] == {"type": "disabled"}

    def test_model_rejecting_the_param_gets_one_retry_without(self, tmp_path: Path) -> None:
        calls: list[dict] = []
        import urllib.error

        body = json.dumps(TestThinkingDisabled._ok_body()).encode()

        def fake_urlopen(request, timeout=None):
            payload = json.loads(request.data.decode("utf-8"))
            calls.append(payload)
            if "thinking" in payload:
                raise urllib.error.HTTPError(
                    request.full_url, 400, "bad", {}, io.BytesIO(b'{"error": "unknown field thinking"}')
                )
            return _BytesResponse(body)

        text, _usage = vlm.transcribe_image_vlm(
            self._png(tmp_path), model="dynamic/image", base_url="http://x/v1", api_key="k", urlopen=fake_urlopen
        )
        assert text == "transcribed line"
        assert "thinking" in calls[0]
        assert "thinking" not in calls[1]
