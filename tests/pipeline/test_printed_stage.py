import json
from pathlib import Path

from PIL import Image

from pipeline.chain import BatchRun
from pipeline.model.token_usage import TokenUsage
from pipeline.model.vlm_answer import VlmAnswer


def _seed(tmp_path: Path) -> BatchRun:
    work = tmp_path / "work"
    registry = tmp_path / "registry"
    pile = tmp_path / "pile"
    registry.mkdir()
    pile.mkdir()
    Image.new("RGB", (10, 12), "white").save(pile / "p1.jpg")  # the grouping measures a real page
    (registry / "b1.json").write_text(
        json.dumps(
            {
                "batch_id": "b1",
                "path": str(pile),
                "label": "printed",
                "status": "pending",
                "arrived_at": "2026-11-02T10:00:00+00:00",
                "pages": {"p1.jpg": "hash-1"},
                "fingerprint": ["hash-1"],
            }
        )
    )
    return BatchRun("b1", work_dir=work, registry_dir=registry)


def _one_document(_system: str, _user: str) -> str:
    """The boundary call's answer for a one-page pile."""
    import json

    return json.dumps(
        {"pages": [{"page": "p1.jpg", "text": "PRINTED PAGE", "starts_document": True, "ends_document": True}]}
    )


def test_the_process_pass_routes_a_printed_page_by_its_category(tmp_path: Path) -> None:
    """The medium is the CLASSIFIER's category (classify.json): a page it calls
    printed is transcribed by the ordinary process pass — no manual command, no
    rows."""
    import json

    run = _seed(tmp_path)
    guess = run.work_dir / "b1"
    guess.mkdir(parents=True, exist_ok=True)
    (guess / "classify.json").write_text(json.dumps({"p1.jpg": {"kind": "printed", "confidences": {"printed": 0.99}}}))
    calls: list[Path] = []

    def fake(image: Path) -> tuple[str, VlmAnswer]:
        calls.append(image)
        return "PRINTED PAGE", VlmAnswer("raw", TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2))

    run.process(client=_one_document, _printed=fake)
    assert len(calls) == 1
    assert (run.work_dir / "b1" / "ocr-guess" / "p1.txt").read_text() == "PRINTED PAGE\n"
    after = json.loads((run.registry_dir / "b1.json").read_text())
    assert after["status"] == "review"
    assert (run.work_dir / "b1" / "ocr-guess" / "p1.txt").read_text() == "PRINTED PAGE\n"
    after = json.loads((run.registry_dir / "b1.json").read_text())
    assert after["status"] == "review"
    assert after["boundaries"][0]["pages"] == ["p1.jpg"]


def test_a_printed_page_is_transcribed_directly_and_the_marker_makes_it_idempotent(tmp_path: Path) -> None:
    run = _seed(tmp_path)
    calls: list[Path] = []

    def fake(image: Path) -> tuple[str, VlmAnswer]:
        calls.append(image)
        return "POST CARD\nPrinted in Great Britain", VlmAnswer(
            "raw", TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        )

    run.printed_pages(_transcribe=fake)
    assert len(calls) == 1
    text = (run.work_dir / "b1" / "ocr-guess" / "p1.txt").read_text()
    assert text == "POST CARD\nPrinted in Great Britain\n"
    boundary = json.loads((run.work_dir / "b1" / "ocr-guess" / "boundaries.json").read_text())
    assert boundary[0]["pages"] == ["p1.jpg"]
    marker = json.loads((run.work_dir / "b1" / "ocr-guess" / "p1.printed.json").read_text())
    assert marker["page"] == "p1.jpg" and marker["chars"] > 0
    record = json.loads((run.registry_dir / "b1.json").read_text())
    assert record["status"] == "review"

    # a re-run pays for no page already read
    run.printed_pages(_transcribe=fake)
    assert len(calls) == 1


def test_the_row_pipeline_skips_a_page_already_read_directly(tmp_path: Path) -> None:
    """An old classify record names the page "text" (the row route), but the
    printed marker proves the page was read directly: the row pipeline is not
    applied again — the marker is the page's stage-5 completion."""
    import json

    from pipeline.chain import Classification

    run = _seed(tmp_path)
    guess_dir = run.work_dir / "b1" / "ocr-guess"
    guess_dir.mkdir(parents=True, exist_ok=True)
    (guess_dir / "p1.printed.json").write_text(json.dumps({"page": "p1.jpg", "chars": 10}))
    classify = {
        "p1.jpg": {"kind": "text", "confidences": {"text": 0.99}},
        "p2.jpg": {"kind": "handwriting", "confidences": {"handwriting": 0.9}},
    }
    rows = run.rows_pages(Classification(classify, ["p1.jpg", "p2.jpg"], []))
    assert rows == ["p2.jpg"]
