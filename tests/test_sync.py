"""Tests for the two-app sync contract: the confirmation shape, the
frontend's catch-up outbox, the draft payloads, and the shared
confirmation write path — all deterministic, no models, no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from tools.atomic import atomic_write
from tools.layout import Detection, build_layout, write_layout
from tools.registry import RegistryError
from tools.sync import (
    Outbox,
    demote_stale_jobs,
    draft_payloads,
    page_job_state,
    record_confirmation,
    reprocess_page_transcription,
    rotate_page,
    set_page_job,
    validate_confirmation,
)


def _confirmation(**overrides: object) -> dict[str, object]:
    return {
        "batch_id": "adopt-0001",
        "doc_index": 1,
        "pages": ["p1.jpg", "p2.jpg"],
        "text": "Chère Maman.",
        "status": "confirmed",
        "confirmed_at": "2026-08-14T00:00:00Z",
        **overrides,
    }


def test_validate_confirmation_accepts_the_shape() -> None:
    assert validate_confirmation(_confirmation())["status"] == "confirmed"


def test_validate_confirmation_rejects_bad_shapes() -> None:
    with pytest.raises(ValueError, match="missing fields"):
        validate_confirmation({"pages": []})
    with pytest.raises(ValueError, match="status"):
        validate_confirmation(_confirmation(status="maybe"))
    with pytest.raises(ValueError, match="pages"):
        validate_confirmation(_confirmation(pages=[]))


def test_validate_confirmation_rejects_non_integer_doc_index() -> None:
    # a float (1e309 -> OverflowError in the receiver's int()) or a bool
    # would 500 instead of 400 (review, 2026-08-15)
    with pytest.raises(ValueError, match="doc_index"):
        validate_confirmation(_confirmation(doc_index=1.5))
    with pytest.raises(ValueError, match="doc_index"):
        validate_confirmation(_confirmation(doc_index=1e309))
    with pytest.raises(ValueError, match="doc_index"):
        validate_confirmation(_confirmation(doc_index=True))
    with pytest.raises(ValueError, match="doc_index"):
        validate_confirmation(_confirmation(doc_index=0))
    with pytest.raises(ValueError, match="doc_index"):
        validate_confirmation(_confirmation(doc_index=-2))


def test_validate_confirmation_accepts_a_rejection_without_text() -> None:
    # record_confirmation treats text=None as the rejection marker — the
    # validator must not demand a string for it (review, 2026-08-15: a
    # rejection with text null got a 400 and was never recorded)
    payload = validate_confirmation(_confirmation(status="rejected", text=None))
    assert payload["status"] == "rejected"
    with pytest.raises(ValueError, match="text"):
        validate_confirmation(_confirmation(text=None))  # a CONFIRM needs the text


def test_outbox_catch_up_add_pending_mark_received(tmp_path: Path) -> None:
    outbox = Outbox(tmp_path / "outbox")
    item_id = outbox.add(_confirmation())
    pending = outbox.pending()
    assert [(i, p["status"]) for i, p in pending] == [(item_id, "confirmed")]
    outbox.mark_received([item_id])
    assert outbox.pending() == []
    assert list(tmp_path.glob("outbox/*.tmp")) == []  # atomic writes leave no temp siblings


def test_outbox_mark_received_rejects_traversal(tmp_path: Path) -> None:
    outbox = Outbox(tmp_path / "outbox")
    (tmp_path / "outbox").mkdir()
    victim = tmp_path / "victim.json"
    victim.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid outbox item id"):
        outbox.mark_received(["../../victim"])
    assert victim.exists()  # nothing outside the outbox was touched


def test_draft_payloads_serves_the_review_surface(tmp_path: Path) -> None:
    guess = tmp_path / "adopt-0001" / "ocr-guess"
    guess.mkdir(parents=True)
    (guess / "p1.txt").write_text("Chère Maman.", encoding="utf-8")
    (guess / "boundaries.json").write_text(
        json.dumps([{"pages": ["p1.jpg"], "greeting": "Chère Maman.", "signoff": None}]),
        encoding="utf-8",
    )
    drafts = draft_payloads("adopt-0001", tmp_path)
    assert drafts[0]["texts"]["p1.jpg"] == "Chère Maman."
    assert drafts[0]["greeting"] == "Chère Maman."


def test_draft_payloads_never_serves_a_bad_layout(tmp_path: Path) -> None:
    """Fail-fast (2026-08-17): a layout with a degenerate or out-of-image
    box is NOT served to the review surface — the page keeps its text but
    loses the layout, and a loud ``layout_errors`` marker names the
    violation. Wrong boxes must never reach the reviewer."""
    guess = tmp_path / "adopt-0001" / "ocr-guess"
    guess.mkdir(parents=True)
    (guess / "p1.txt").write_text("line one", encoding="utf-8")
    (guess / "p1.layout.json").write_text(
        json.dumps(
            {
                "page": "p1.jpg",
                "width": 100,
                "height": 100,
                "lines": [{"index": 0, "text": "line one", "box": [0, 0, 500, 10], "conf": 1.0, "words": []}],
                "unmatched": [],
            }
        ),
        encoding="utf-8",
    )
    (guess / "boundaries.json").write_text(
        json.dumps([{"pages": ["p1.jpg"], "greeting": None, "signoff": None}]),
        encoding="utf-8",
    )
    drafts = draft_payloads("adopt-0001", tmp_path)
    assert drafts[0]["layouts"] == {}  # the bad layout is not served
    assert "line one" in drafts[0]["texts"]["p1.jpg"]  # the text still shows
    assert drafts[0]["layout_errors"]["p1.jpg"], "the violation is named loudly"


def test_draft_payloads_carries_the_layout_when_the_pass_has_run(tmp_path: Path) -> None:
    """TECH-SPEC §16.16: the drafts payload gains the per-page layout (line
    boxes + per-word confidence) once the layout pass has written it —
    absent layouts stay absent, never fabricated."""
    guess = tmp_path / "adopt-0001" / "ocr-guess"
    guess.mkdir(parents=True)
    (guess / "p1.txt").write_text("line one\nline two", encoding="utf-8")
    (guess / "p1.layout.json").write_text(
        json.dumps(
            {
                "page": "p1.jpg",
                "width": 100,
                "height": 100,
                "lines": [{"index": 0, "text": "line one", "box": [0, 0, 50, 10], "conf": 1.0, "words": []}],
                "unmatched": [],
            }
        ),
        encoding="utf-8",
    )
    (guess / "boundaries.json").write_text(
        json.dumps([{"pages": ["p1.jpg"], "greeting": None, "signoff": None}]),
        encoding="utf-8",
    )
    drafts = draft_payloads("adopt-0001", tmp_path)
    assert drafts[0]["layouts"]["p1.jpg"]["lines"][0]["text"] == "line one"
    assert drafts[0]["layouts"]["p1.jpg"]["lines"][0]["box"] == [0, 0, 50, 10]
    # a page without a layout file contributes no entry
    assert set(drafts[0]["layouts"]) == {"p1.jpg"}
    # the covered orientations: a plain layout (no per-line orientation
    # fields) was read at the image's upright — [0]; absent layouts have
    # nothing covered (any rotate queues the old path)
    assert drafts[0]["orientations"] == {"p1.jpg": [0]}


def test_draft_payloads_reports_the_multi_orientations(tmp_path: Path) -> None:
    """VR15: the combined layout's per-line orientations are the covered
    set the review surface uses for the view-only rotate rule — the
    postcard's 0° message + 270° address block."""
    guess = tmp_path / "adopt-0001" / "ocr-guess"
    guess.mkdir(parents=True)
    (guess / "p1.txt").write_text("We are from beauford", encoding="utf-8")
    (guess / "p1.layout.json").write_text(
        json.dumps(
            {
                "page": "p1.jpg",
                "width": 100,
                "height": 100,
                "lines": [
                    {
                        "index": 0,
                        "text": "We are from beauford",
                        "box": [0, 0, 50, 10],
                        "conf": 1.0,
                        "orientation": 0,
                        "words": [],
                    },
                    {
                        "index": 1,
                        "text": "HARBOTTLE, MORPETH",
                        "box": [60, 0, 70, 100],
                        "conf": 1.0,
                        "orientation": 270,
                        "words": [],
                    },
                ],
                "unmatched": [],
            }
        ),
        encoding="utf-8",
    )
    (guess / "boundaries.json").write_text(
        json.dumps([{"pages": ["p1.jpg"], "greeting": None, "signoff": None}]),
        encoding="utf-8",
    )
    drafts = draft_payloads("adopt-0001", tmp_path)
    assert drafts[0]["orientations"] == {"p1.jpg": [0, 270]}


def _registered_batch(tmp_path: Path, registry: Path) -> None:
    registry.mkdir()
    (registry / "adopt-0001.json").write_text(
        json.dumps({"batch_id": "adopt-0001", "path": str(tmp_path), "status": "review", "boundaries": None}),
        encoding="utf-8",
    )


def test_record_confirmation_writes_and_updates_the_registry(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    _registered_batch(tmp_path, registry)
    document = {"pages": ["p1.jpg"]}

    record_confirmation("adopt-0001", 1, document, "Chère Maman.", work_dir=tmp_path, registry_dir=registry)
    record_confirmation("adopt-0001", 2, {"pages": ["p2.jpg"]}, None, work_dir=tmp_path, registry_dir=registry)

    record = json.loads((registry / "adopt-0001.json").read_text(encoding="utf-8"))
    assert record["boundaries"] == [
        {"pages": ["p1.jpg"], "status": "confirmed"},
        {"pages": ["p2.jpg"], "status": "rejected"},
    ]
    assert (tmp_path / "adopt-0001" / "ocr-confirmed" / "doc-01.txt").read_text(encoding="utf-8") == "Chère Maman."
    assert not (tmp_path / "adopt-0001" / "ocr-confirmed" / "doc-02.txt").exists()  # rejected leaves no text


def test_record_confirmation_replaces_by_pages(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    _registered_batch(tmp_path, registry)
    record_confirmation("adopt-0001", 1, {"pages": ["p1.jpg"]}, "v1", work_dir=tmp_path, registry_dir=registry)
    record_confirmation("adopt-0001", 1, {"pages": ["p1.jpg"]}, "v2", work_dir=tmp_path, registry_dir=registry)
    record = json.loads((registry / "adopt-0001.json").read_text(encoding="utf-8"))
    assert len(record["boundaries"]) == 1  # same pages → replaced, not duplicated


def test_record_confirmation_rejects_unknown_batch_without_writing(tmp_path: Path) -> None:
    # a confirmation for a batch the backend never adopted must neither
    # fabricate a record nor leave a review-output file — RegistryError -> 4xx
    registry = tmp_path / "registry"
    registry.mkdir()
    with pytest.raises(RegistryError):
        record_confirmation("adopt-9999", 1, {"pages": ["p1.jpg"]}, "text", work_dir=tmp_path, registry_dir=registry)
    assert not (tmp_path / "adopt-9999" / "ocr-confirmed").exists()  # nothing written for the unknown batch


def test_safe_page_name_allows_phone_duplicate_suffixes(tmp_path: Path) -> None:
    """Phone export duplicates arrive as "name~2.jpg" — the guard must not
    reject real scans (walk finding 1, 2026-08-16: the PhotoScan batch was
    unopenable). Traversal stays blocked."""
    from tools.sync import safe_page_name

    assert safe_page_name("1782635795946-5f7905a9~2.jpg")
    assert safe_page_name("plain-name.jpg")
    assert not safe_page_name("../etc/passwd")
    assert not safe_page_name("..")


def test_draft_payloads_rejects_unsafe_page_names(tmp_path: Path) -> None:
    # page names from boundaries.json become path segments — a separator or ".."
    # must fail closed (defense-in-depth; the pipeline writes only plain names)
    guess = tmp_path / "adopt-0001" / "ocr-guess"
    guess.mkdir(parents=True)
    (guess / "boundaries.json").write_text(json.dumps([{"pages": ["../etc/passwd"]}]), encoding="utf-8")
    with pytest.raises(ValueError):
        draft_payloads("adopt-0001", tmp_path)
    (guess / "boundaries.json").write_text(json.dumps([{"pages": [".."]}]), encoding="utf-8")
    with pytest.raises(ValueError):
        draft_payloads("adopt-0001", tmp_path)


def test_rotate_page_fixes_the_orientation(tmp_path: Path) -> None:
    """The reviewer's orientation fix (2026-08-16): rotate the page by
    quarter-turns CW and re-anchor the layout in place — the transcription
    and flags stay (the rotation is a rigid remap; the words are
    rotation-invariant)."""
    batch = tmp_path / "adopt-0001"
    (batch / "oriented").mkdir(parents=True)
    (batch / "ocr-guess").mkdir(parents=True)
    image = Image.new("RGB", (100, 200), "white")
    for x in range(0, 10):
        for y in range(0, 10):
            image.putpixel((x, y), (255, 0, 0))  # a red block at the top-left
    image.save(batch / "oriented" / "p1.jpg")
    layout = build_layout(
        "p1.jpg",
        100,
        200,
        "line one\nline two",
        [
            Detection(box=[0, 100, 50, 120], text="line one", score=0.9, words=[]),
            Detection(box=[0, 150, 50, 170], text="noise", score=0.5, words=[]),
        ],
    )
    write_layout(layout, batch / "ocr-guess" / "p1.layout.json")
    (batch / "ocr-guess" / "p1.selfreport.json").write_text(json.dumps([{"line": 1, "word": "one"}]), encoding="utf-8")

    rotate_page("adopt-0001", "p1.jpg", 1, tmp_path)

    rotated = Image.open(batch / "oriented" / "p1.jpg")
    assert rotated.size == (200, 100)  # 90° CW swaps the dims
    # the original top-left block lands at the top-right after CW 90
    # (JPEG is lossy — the check tolerates the compression)
    pixel = rotated.getpixel((194, 4))
    assert isinstance(pixel, tuple) and len(pixel) >= 3
    assert pixel[0] > 200 and pixel[1] < 60 and pixel[2] < 60
    new_layout = json.loads((batch / "ocr-guess" / "p1.layout.json").read_text(encoding="utf-8"))
    assert new_layout["width"] == 200
    assert new_layout["height"] == 100
    # the first line's box: [0, 100, 50, 120] -> [h-y1, x0, h-y0, x1]
    assert new_layout["lines"][0]["box"] == [80, 0, 100, 50]
    assert new_layout["lines"][0]["text"] == "line one"
    assert new_layout["rotation"] == 90  # the cumulative applied rotation
    # the selfreport flags survive the rotation
    assert new_layout["lines"][0]["words"][1]["conf"] == 0.0  # "one"


def test_rotate_page_is_idempotent_and_cumulative(tmp_path: Path) -> None:
    """The sync intents are the DESIRED cumulative rotation — a retried
    intent (the same quarters again) is a no-op, and two presses add up
    (2026-08-16: offline queues must not over-rotate on redelivery)."""
    batch = tmp_path / "adopt-0001"
    (batch / "oriented").mkdir(parents=True)
    (batch / "ocr-guess").mkdir(parents=True)
    Image.new("RGB", (100, 200), "white").save(batch / "oriented" / "p1.jpg")
    write_layout(
        build_layout(
            "p1.jpg",
            100,
            200,
            "line one",
            [Detection(box=[0, 100, 50, 120], text="line one", score=0.9, words=[])],
        ),
        batch / "ocr-guess" / "p1.layout.json",
    )

    rotate_page("adopt-0001", "p1.jpg", 2, tmp_path)  # the reviewer pressed twice
    layout_after = json.loads((batch / "ocr-guess" / "p1.layout.json").read_text(encoding="utf-8"))
    assert layout_after["rotation"] == 180
    assert Image.open(batch / "oriented" / "p1.jpg").size == (100, 200)  # 180° keeps the dims

    rotate_page("adopt-0001", "p1.jpg", 2, tmp_path)  # a retried intent: same desired
    layout_retried = json.loads((batch / "ocr-guess" / "p1.layout.json").read_text(encoding="utf-8"))
    assert layout_retried["rotation"] == 180  # no double rotation

    rotate_page("adopt-0001", "p1.jpg", 3, tmp_path)  # a further correction
    layout_final = json.loads((batch / "ocr-guess" / "p1.layout.json").read_text(encoding="utf-8"))
    assert layout_final["rotation"] == 270
    assert Image.open(batch / "oriented" / "p1.jpg").size == (200, 100)


def test_rotate_page_guards(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no such page"):
        rotate_page("adopt-0001", "nope.jpg", 1, tmp_path)
    with pytest.raises(ValueError, match="invalid batch"):
        rotate_page("../evil", "p1.jpg", 1, tmp_path)
    with pytest.raises(ValueError, match="invalid batch"):
        rotate_page("adopt-0001", "..%2Fetc", 1, tmp_path)


def test_reprocess_failure_marks_the_page(tmp_path: Path) -> None:
    """A failed re-read marks the page "failed" (fail-fast — the stale text
    stays visible with the warning, never a silent wrong answer)."""
    batch = tmp_path / "adopt-0001"
    (batch / "oriented").mkdir(parents=True)
    (batch / "ocr-guess").mkdir(parents=True)
    Image.new("RGB", (100, 200), "white").save(batch / "oriented" / "p1.jpg")
    write_layout(
        build_layout(
            "p1.jpg",
            100,
            200,
            "old text",
            [Detection(box=[0, 100, 50, 120], text="noise", score=0.4, words=[])],
        ),
        batch / "ocr-guess" / "p1.layout.json",
    )
    set_page_job("adopt-0001", "p1.jpg", "transcribing", tmp_path)

    def boom(image, **kw):
        raise RuntimeError("vision model unreachable")

    with pytest.raises(RuntimeError, match="unreachable"):
        reprocess_page_transcription("adopt-0001", "p1.jpg", tmp_path, transcribe=boom)
    assert page_job_state("adopt-0001", tmp_path) == {"p1.jpg": "failed"}


def test_set_page_job_clears_when_empty(tmp_path: Path) -> None:
    set_page_job("adopt-0001", "p1.jpg", "transcribing", tmp_path)
    set_page_job("adopt-0001", "p1.jpg", None, tmp_path)
    assert page_job_state("adopt-0001", tmp_path) == {}
    assert not (tmp_path / "adopt-0001" / "ocr-guess" / ".jobs.json").exists()


def test_demote_stale_jobs_marks_killed_transcriptions_failed(tmp_path: Path) -> None:
    """A server restart kills the reprocess threads — pages left
    "transcribing" demote to "failed" (their re-read never completed; the
    text is stale and the warning must show, 2026-08-16)."""
    set_page_job("adopt-0001", "p1.jpg", "transcribing", tmp_path)
    set_page_job("adopt-0001", "p2.jpg", "failed", tmp_path)
    demote_stale_jobs(tmp_path)
    state = page_job_state("adopt-0001", tmp_path)
    assert state == {"p1.jpg": "failed", "p2.jpg": "failed"}


def test_rotate_page_accepts_desired_zero_rotate_back(tmp_path: Path) -> None:
    """A reviewer rotating the wrong way back to the ORIGINAL orientation
    sends the desired 0 — the delta is the no-op check, not the desired
    (2026-08-16: the early return on quarters==0 ignored the rotate-back)."""
    batch = tmp_path / "adopt-0001"
    (batch / "oriented").mkdir(parents=True)
    (batch / "ocr-guess").mkdir(parents=True)
    Image.new("RGB", (100, 200), "white").save(batch / "oriented" / "p1.jpg")
    write_layout(
        build_layout(
            "p1.jpg",
            100,
            200,
            "line one",
            [Detection(box=[0, 100, 50, 120], text="line one", score=0.9, words=[])],
        ),
        batch / "ocr-guess" / "p1.layout.json",
    )
    assert rotate_page("adopt-0001", "p1.jpg", 1, tmp_path) is True  # rotated 90
    assert rotate_page("adopt-0001", "p1.jpg", 0, tmp_path) is True  # back to the original
    layout = json.loads((batch / "ocr-guess" / "p1.layout.json").read_text(encoding="utf-8"))
    assert layout["rotation"] == 0
    assert rotate_page("adopt-0001", "p1.jpg", 0, tmp_path) is False  # now a true no-op


def test_rotate_page_recovers_a_half_rotated_crash(tmp_path: Path) -> None:
    """A crash between the image swap and the layout write (the pair is not
    transactional — bot review 2026-08-16) leaves the image rotated with a
    stale layout. The journal's {from, rotation} lets the next rotate
    complete the layout BEFORE the delta, so the boxes never misalign."""
    import json as _json

    batch = tmp_path / "adopt-0001"
    (batch / "oriented").mkdir(parents=True)
    (batch / "ocr-guess").mkdir(parents=True)
    Image.new("RGB", (100, 200), "white").save(batch / "oriented" / "p1.jpg")
    write_layout(
        build_layout(
            "p1.jpg",
            100,
            200,
            "line one",
            [Detection(box=[0, 100, 50, 120], text="line one", score=0.9, words=[])],
        ),
        batch / "ocr-guess" / "p1.layout.json",
    )
    assert rotate_page("adopt-0001", "p1.jpg", 1, tmp_path) is True  # 90
    # simulate the crash: the image is swapped (rotated), the layout is
    # stale (the OLD dims and rotation), and the journal records the intent
    layout = _json.loads((batch / "ocr-guess" / "p1.layout.json").read_text(encoding="utf-8"))
    layout["width"] = 100
    layout["height"] = 200
    layout["rotation"] = 0
    write_layout(layout, batch / "ocr-guess" / "p1.layout.json")
    atomic_write(
        batch / "oriented" / "p1.rotate.json",
        '{"from": 0, "rotation": 90}\n',
    )
    # the next intent to the SAME desired rotation is a no-op — the
    # recovery already brought the layout to 90 (the image's actual state)
    assert rotate_page("adopt-0001", "p1.jpg", 1, tmp_path) is False
    layout = _json.loads((batch / "ocr-guess" / "p1.layout.json").read_text(encoding="utf-8"))
    assert layout["rotation"] == 90
    assert not (batch / "oriented" / "p1.rotate.json").exists()  # the journal is cleaned


def test_rotate_page_discards_a_premature_journal(tmp_path: Path) -> None:
    """A crash BEFORE the image swap leaves the journal written with the
    image and layout still consistent — the next rotate discards it and
    proceeds from the layout's real state."""
    import json as _json

    batch = tmp_path / "adopt-0001"
    (batch / "oriented").mkdir(parents=True)
    (batch / "ocr-guess").mkdir(parents=True)
    Image.new("RGB", (100, 200), "white").save(batch / "oriented" / "p1.jpg")
    write_layout(
        build_layout(
            "p1.jpg",
            100,
            200,
            "line one",
            [Detection(box=[0, 100, 50, 120], text="line one", score=0.9, words=[])],
        ),
        batch / "ocr-guess" / "p1.layout.json",
    )
    # the premature journal: the intent never reached the image
    atomic_write(batch / "oriented" / "p1.rotate.json", '{"from": 0, "rotation": 90}\n')
    assert rotate_page("adopt-0001", "p1.jpg", 1, tmp_path) is True  # the normal rotate proceeds
    layout = _json.loads((batch / "ocr-guess" / "p1.layout.json").read_text(encoding="utf-8"))
    assert layout["rotation"] == 90
    assert not (batch / "oriented" / "p1.rotate.json").exists()
