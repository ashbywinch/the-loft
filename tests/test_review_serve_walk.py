"""The review surface's serve-walk (2026-08-26): every stored layout in
the real work directory, walked through the exact load+validate path
the server uses — the structural half of the assurance the user asked
for ("how will we ensure this actually happens?"). Runs under
`make verify` (the archive marker). It cannot judge ALIGNMENT — that is
tools/walk_review.py's contact sheets + a vision pass — but it makes
stale provenance, empty text, and boxless lines loud on every verify
instead of silent on disk."""

from __future__ import annotations

import json

import pytest

from tools.layout import validate_layout
from tools.loft_paths import WORK_DIR


@pytest.mark.archive
@pytest.mark.skipif(not WORK_DIR.is_dir(), reason="work disk not mounted")
def test_every_stored_layout_is_clean_or_loudly_refused() -> None:
    """No layout on disk may be structurally dirty: each file either
    validates clean or its page has no business serving boxes. The first
    version of this walk found page-01's stale old-pipeline layout —
    valid-looking JSON that had been shielded from every pipeline fix by
    the clean-skip."""
    dirty: list[str] = []
    stale: list[str] = []
    for batch_dir in sorted(WORK_DIR.iterdir()):
        guess_dir = batch_dir / "ocr-guess"
        if not guess_dir.is_dir():
            continue
        for layout_path in sorted(guess_dir.glob("*.layout.json")):
            try:
                layout = json.loads(layout_path.read_text(encoding="utf-8"))
            except Exception as exc:
                dirty.append(f"{batch_dir.name}/{layout_path.name}: unparseable ({exc})")
                continue
            violations = validate_layout(layout)
            if violations:
                dirty.append(f"{batch_dir.name}/{layout_path.name}: {violations[0][:70]}")
            lines = layout.get("lines") or []
            if any(not ln.get("box_source") for ln in lines):
                # pre-ink-column provenance: written by code that predates
                # the current gates; it must be re-derived, not trusted
                stale.append(f"{batch_dir.name}/{layout_path.name}")
    assert not dirty, f"structurally dirty layouts on disk: {dirty}"
    assert not stale, (
        f"layouts without ink provenance (old-pipeline output — delete and "
        f"re-run eval_batch so today's gates judge them): {stale}"
    )


@pytest.mark.archive
@pytest.mark.skipif(not WORK_DIR.is_dir(), reason="work disk not mounted")
def test_serve_walk_boxes_carry_ink_and_single_lines() -> None:
    """The image-aware gates at batch level (2026-08-26): every boxed
    line must sit on ink (Gate D) and enclose ONE text band (the
    projection gate). These are the cheap checks that make most vision
    audits unnecessary — they catch offset bugs and multi-line boxes
    deterministically. Pages whose stored layout fails here are exactly
    the ones walk_review's sheets would show as wrong."""
    from PIL import Image

    from tools.box import has_ink, text_line_count

    offenders: list[str] = []
    checked = 0
    for batch_dir in sorted(WORK_DIR.iterdir()):
        guess_dir = batch_dir / "ocr-guess"
        oriented_dir = batch_dir / "oriented"
        if not guess_dir.is_dir() or not oriented_dir.is_dir():
            continue
        for layout_path in sorted(guess_dir.glob("*.layout.json")):
            layout = json.loads(layout_path.read_text(encoding="utf-8"))
            if validate_layout(layout):
                continue  # already covered by the structural walk
            page = layout_path.name.replace(".layout.json", "")
            image_path = oriented_dir / f"{page}.jpg"
            if not image_path.is_file():
                continue
            with Image.open(image_path) as im:
                im.load()
                for ln in layout.get("lines", []):
                    box = ln.get("box")
                    if not box or not (ln.get("text") or "").strip():
                        continue
                    checked += 1
                    where = f"{batch_dir.name}/{page}#{ln.get('index')}"
                    if not has_ink(box, im):
                        offenders.append(f"{where}: no ink under the box")
                    elif text_line_count(box, im) > 1:
                        offenders.append(f"{where}: box spans multiple lines")
    assert checked > 0, "no boxed lines found — the walk checked nothing"
    assert not offenders, f"image-aware gate failures: {offenders[:12]} ({len(offenders)} total)"
