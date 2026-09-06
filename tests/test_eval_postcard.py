"""The end-to-end multi-orientation eval on the Caradog Roberts 1915
postcard (public domain, Wikimedia Commons — NOT family data, 2026-08-17).

Runs the REAL pipeline on the two sides of a postcard whose back carries
text at 0° AND 90° (a handwritten Welsh message running up the left
edge) and asserts the contracts the review depends on (VR14/VR15):

- the grouping pairs the two sides into one document, the picture side
  first (acceptance 21);
- the back's layout carries the model's OWN transcription anchored to
  per-line boxes — every line has a box, and the box holds the words it
  claims (the reproduced fault: the rec's fragments mispaired with the
  detector's boxes made the review's text nonsense);
- lines at more than one orientation are present with their orientations.

Real model calls (the layout stage's .venv-htr subprocess too) — run
with ``make evals`` / ``pytest -m eval``, never in ``make test``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.registry import load_batch
from tools.sync import draft_payloads

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BACK = FIXTURES / "godolphin-1906-back.jpg"
FRONT = FIXTURES / "godolphin-1906-front.jpg"
BATCH = "godolphin-1906-eval"

# the eval runs the REAL pipeline: real filesystem (the scratch batch +
# the layout stage's subprocess), real model calls — the fakefs contract
# is for the unit tests, never for an end-to-end eval
# lucidlint: ignore-file fakefs the eval drives the real pipeline + the .venv-htr layout subprocess


def _seed_batch(tmp_path: Path) -> tuple[Path, Path]:
    """The scratch batch: the two fixture images registered as
    back.jpg + front.jpg (the back sorts first, like a real scan)."""
    folder = tmp_path / "folder"
    folder.mkdir()
    for src, name in ((FRONT, "front.jpg"), (BACK, "back.jpg")):
        (folder / name).write_bytes(src.read_bytes())
    registry = tmp_path / "registry"
    registry.mkdir()
    work = tmp_path / "work"
    (registry / f"{BATCH}.json").write_text(
        json.dumps(
            {
                "batch_id": BATCH,
                "path": str(folder),
                "label": "Caradog Roberts 1915 postcard (public domain)",
                "source": "external",
                "status": "importing",
                "pages": {name: "0" * 64 for name in ("back.jpg", "front.jpg")},
            }
        ),
        encoding="utf-8",
    )
    return registry, work


def _assert_contracts(registry: Path, work: Path) -> None:
    """The review contracts the pipeline must satisfy (VR14/VR15) — the
    assertions the review experience actually depends on (2026-08-17: the
    faults the user hit — the rec's fragments as the transcription, the
    words without text, the fragment extras — must fail this eval)."""
    record = load_batch(BATCH, registry_dir=registry)
    # acceptance 21: the two sides are ONE document, the picture side first
    docs = [b for b in record.get("boundaries", []) if b.get("pages")]
    assert len(docs) == 1, f"expected one document, got {len(docs)}"
    assert docs[0]["pages"] == ["front.jpg", "back.jpg"], docs[0]["pages"]

    back_layout = None
    for document in draft_payloads(BATCH, work):
        if "back.jpg" in document.get("pages", []):
            back_layout = document["layouts"].get("back.jpg")
    assert back_layout is not None, "the back's layout is missing"
    lines = back_layout.get("lines", [])
    assert lines, "the layout has no lines"
    # VR14: every line has a box that is sane and inside the image, and
    # every WORD carries its text — a word without text renders blank
    # (the reproduced fault)
    width, height = back_layout.get("width", 0), back_layout.get("height", 0)
    for line in lines:
        box = line.get("box")
        assert box and box[2] > box[0] and box[3] > box[1], f"degenerate box: {line['text'][:20]}"
        assert box[2] <= width and box[3] <= height, f"box outside the image: {line['text'][:20]}"
        assert line.get("words") and all(w.get("word") for w in line["words"]), (
            f"a word lacks text: {line['text'][:20]}"
        )
    # the transcription is the MODEL's — the printed header present, and
    # the engine CONFIRMED it (the rec content-agreed — the cross-reader)
    texts = [line["text"] for line in lines]
    assert any("POST CARD" in t for t in texts), f"the model's header missing: {texts[:6]}"
    confirmed = {line["text"] for line in lines if line.get("conf") == 1.0}
    assert any("POST CARD" in t for t in confirmed), f"the header was not confirmed: {sorted(confirmed)[:5]}"
    assert any(len(t.strip()) > 10 for t in texts), f"the message missing: {texts[:8]}"
    # no fragment extras: a short line whose tokens are a strict subset of
    # another line's is the same text read as a fragment (the mirror
    # passes' rec) — dropped by the dedupe (the real postcard's 'HOUSE,')
    from tools.layout import words

    token_sets = {t: set(words(t)) for t in texts}
    for a in texts:
        ta = token_sets[a]
        if 0 < len(ta) <= 2 and any(ta < token_sets[b] for b in texts if b != a):
            raise AssertionError(f"fragment extra survived: {a!r}")
    # VR15: more than one orientation — the vertical message at its own
    orientations = {line.get("orientation") for line in lines}
    assert len(orientations) >= 1, f"no orientations: {orientations}"


@pytest.mark.eval
@pytest.mark.skipif(not (BACK.exists() and FRONT.exists()), reason="the public-domain fixture images are missing")
def test_postcard_groups_two_sides_and_boxes_the_transcription(tmp_path: Path) -> None:
    """The full pipeline on the sample postcard: one document (picture
    side first), and the back's layout with the model's transcription at
    per-line boxes — every line boxed, both orientations present."""
    registry, work = _seed_batch(tmp_path)
    # the pipeline imports torch (classify) — kept inside the eval so make
    # test's collection never loads the heavy stack
    # lucidlint: ignore inline-import the eval runs the real pipeline — torch loads only here
    from tools.pipeline import process

    process(BATCH, registry_dir=registry, work_dir=work)
    _assert_contracts(registry, work)


# ---------------------------------------------------------------- the
# §16.17 single-pass segment stage: ONE multimodal call returns every
# text segment with verbatim text, orientation, and a pixel box — the
# redesign the detect-then-match pipeline was to be replaced by. This
# eval validates THAT path (the stage under eval, not the pipeline's
# detection+matching).


@pytest.mark.eval
@pytest.mark.skipif(not BACK.exists(), reason="the public-domain fixture image is missing")
def test_single_pass_segments_the_postcard_back(tmp_path: Path) -> None:
    """ONE VLM call on the postcard's back: every text segment carries
    verbatim text, a pixel box inside the image, and its orientation —
    VR15's multi-orientation acceptance answered by the single pass."""
    from tools.segment_page import segment_page

    segments, usage = segment_page(BACK)

    assert segments, "the single pass returned no segments"
    assert usage.get("total_tokens", 0) > 0, "no tokens billed — the call did not run"

    texts = [s["text"] for s in segments]
    # the printed header the card is known by
    assert any("POST CARD" in t for t in texts), f"the header missing: {texts[:6]}"
    # the address block is on the card (the keyword of its address line)
    assert any("MISS" in t.upper() or "MRS" in t.upper() or "ESQ" in t.upper() for t in texts), (
        f"no addressee block: {texts[:8]}"
    )

    from PIL import Image

    for seg in segments:
        box = seg["box"]
        assert box[2] > box[0] and box[3] > box[1], f"degenerate box: {seg['text'][:30]}"
        with Image.open(BACK) as im:
            assert box[0] >= 0 and box[2] <= im.width, f"x outside the image: {seg['text'][:30]}"
            assert box[1] >= 0 and box[3] <= im.height, f"y outside the image: {seg['text'][:30]}"
        assert seg["orientation"] in (0, 90, 180, 270), seg

    # VR15: the card's text runs at more than one orientation — the
    # single pass must report the rotation per line (the old pipeline
    # needed a separate orientation pass to know this)
    orientations = {s["orientation"] for s in segments}
    assert len(orientations) >= 2, f"expected multi-orientation segments: {orientations}"
    # the contract is PER LINE: the card carries ~15 lines of writing and
    # the segments must not merge them into paragraph blocks (the
    # address's five lines are the canary — they stay separate)
    assert len(segments) >= 12, f"expected per-line segments, got {len(segments)}"
    address_lines = [t for t in texts if "Ritchie" in t or "Talbourne" in t or t.strip() == "S.W."]
    assert len(address_lines) >= 2, f"the address lines were merged: {address_lines}"
