"""tools/vlm.py — the vision-model seam: the context the transcription
reads with, and the self-report flag pass (2026-08-15, user-approved: the
transcription model's own doubt is the flag source)."""

from __future__ import annotations

import json

import pytest

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
