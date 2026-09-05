"""Batch ink-column runner: every page through the ink-column pipeline.
The VLM panel reads are parallelised across pages (independent HTTP);
the local rec stays sequential (memory-bound).

Runs under .venv-htr (which has PaddleOCR AND the VLM dependencies).

Usage: PYTHONPATH=. .venv-htr/bin/python tools/eval_batch.py <batch_id> ...
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import monotonic
from typing import Any

from PIL import Image

# The rec engine's imports stay INLINE (in _make_engine/_detect_pieces):
# tools.layout_detect pulls in paddleocr which lives only in .venv-htr;
# a module-top import would make this file unimportable (untestable) in
# the main venv.
from tools.box import (
    has_ink,
    orientation_from_aspect,  # noqa: E402
    text_line_count,
)
from tools.gates import glyph_extent_violation, validate_layout
from tools.ink import cluster_rows, match_labels, offset_box, split_by_bands, transcription_line_count_plausible, union
from tools.layout import load_layout_store, write_layout_store  # noqa: E402
from tools.loft_paths import WORK_DIR  # noqa: E402
from tools.pipeline_store import PipelineStore  # noqa: E402
from tools.text import flag_line_words, selfreport_words_by_line
from tools.vlm import (  # noqa: E402
    parse_transcription_response,
    selfreport_words,
    transcribe_image_vlm,
    transcribe_with_fallbacks,
    transcription_problem,
    transcription_system_with_context,
)
from tools.vlm_cache import (
    load_cached_read,
    load_selfreport,
    store_read,
    store_selfreport,
)  # noqa: E402

# The trial's runner-up (docs/plans/model-trial-report.md §4): same
# family as glm-4.6v, different failure profile — the ladder's last rung.
FALLBACK_MODEL = "z-ai/glm-4.5v"


def layout_is_current(layout: dict[str, Any]) -> bool:
    """Was this layout written by the current ink machinery? The
    clean-skip must only protect layouts today's gates can vouch for:
    page-01/08/11 served stale old-pipeline geometry for days because
    their files validated structurally clean (2026-08-26)."""
    lines = layout.get("lines") or []
    return bool(lines) and all(ln.get("box_source") == "ink" for ln in lines)


def prep_panel(image_path: Path, layout: dict[str, Any] | None, tmp: Path, page: str) -> dict[str, Any] | None:
    """Crop the page's content region; no layout → the full page."""
    if layout is None:
        with Image.open(image_path) as im:
            w, h = im.size
        panel_path = tmp / f"{page}.png"
        Image.open(image_path).save(panel_path)
        return {"path": str(panel_path), "x0": 0, "y0": 0, "w": w, "h": h}
    boxed = [ln["box"] for ln in layout.get("lines", []) if ln.get("box")]
    unmatched = [u["box"] for u in layout.get("unmatched", []) if u.get("box")]
    all_boxes = boxed + unmatched
    if not all_boxes:
        return None
    xs = [v for b in all_boxes for v in (b[0], b[2])]
    ys = [v for b in all_boxes for v in (b[1], b[3])]
    bx0, by0 = min(xs), min(ys)
    bw, bh = max(xs) - bx0, max(ys) - by0
    if bw <= 0 or bh <= 0:
        return None
    panel_path = tmp / f"{page}.png"
    with Image.open(image_path) as im:
        im.crop((int(bx0), int(by0), int(bx0 + bw), int(by0 + bh))).save(panel_path)
    return {"path": str(panel_path), "x0": bx0, "y0": by0, "w": bw, "h": bh}


def _detect_pieces(engine: Any, panel_path: Path) -> list[list[float]]:
    """The rec's detection pieces (the REAL ink)."""
    # lucidlint: ignore inline-import the .venv-htr seam — paddleocr lives only in .venv-htr
    from tools.layout_detect import detect_page

    raw = detect_page(engine, panel_path)
    return [[float(v) for v in d["box"]] for d in raw["detections"] if d["box"]]


def normalized_bands(
    lines: list[str], boxes: dict[int, list[float]] | None, frame_h: float
) -> list[tuple[float, float, str]]:
    """The model's normalized 0-1000 line bands in the frame's PIXELS —
    the scale match_labels's y-overlap compares against (the measured
    unions are panel pixels; the first batch run hardcoded 1600 here and
    every other panel height silently shifted its overlaps)."""
    bands: list[tuple[float, float, str]] = []
    for i, b in sorted((boxes or {}).items()):
        if i < len(lines):
            bands.append(((b[1] / 1000) * frame_h, (b[3] / 1000) * frame_h, lines[i]))
    return bands


def _self_report_for(panel: Path, full_text: str) -> list[dict]:
    """The model's doubt flags for one panel's transcription — cached
    like the reads (the flags are a pure function of the read). Runs in
    Phase 2, where the panel still exists."""
    cached = load_selfreport(panel, full_text)
    if cached is not None:
        return cached

    def _sr_call(image, *, system, user_text=None, **kw):
        # the 64000 default hangs this model on a page image (the trial
        # report's budget finding); the doubt list is small
        return transcribe_image_vlm(image, system=system, user_text=user_text, max_tokens=8000, **kw)

    report = selfreport_words(panel, full_text, transcribe=_sr_call)
    store_selfreport(panel, full_text, report)
    if report:
        print(f"  self-report: {len(report)} entries: {report}", file=sys.stderr)
    return report


def _vlm_read(
    panel_path: str, panel_h: int, row_count: int, conn: tuple[str, str, str | None]
) -> tuple[list[str], list[tuple[float, float, str]], int]:
    model, base_url, api_key = conn
    """One panel's VLM read — the text + the normalized bands. The
    escalation ladder (2026-08-25): first the boxed JSON read, then a
    plain-text re-read (no format to fail mid-echoing; a fraction of the
    tokens), then the plain-text read on the fallback model (glm-4.5v,
    the trial's runner-up with a different failure profile). A response
    must also plausibly cover the measured rows — the birth certificate's
    collapse folded 26 rows into one line."""

    def usable(text: str) -> bool:
        if transcription_problem(text) is not None:
            return False
        plain, _boxes = parse_transcription_response(text)
        return transcription_line_count_plausible(len([ln for ln in plain.split("\n") if ln.strip()]), row_count)

    # The read cache (2026-08-26): keyed on the PANEL BYTES + primary
    # model + budget — any ladder variant's successful read is a valid
    # transcription of that panel, so gate/assembly iterations over
    # unchanged pages cost zero tokens. LOFT_VLM_CACHE=0 bypasses.
    cache_spec = {"model": model, "max_tokens": 8000}
    cached = load_cached_read(Path(panel_path), cache_spec)
    tokens = 0
    if cached is not None:
        # zero NEW tokens: the spend happened in an earlier run
        text, _stored_tokens = cached
        print(f"  vlm {Path(panel_path).name}: CACHED", file=sys.stderr)
    else:
        variants = [
            {
                "model": model,
                "system": transcription_system_with_context(),
                "base_url": base_url,
                "api_key": api_key,
                "max_tokens": 8000,
            },
            {
                "model": model,
                "system": transcription_system_with_context(request_boxes=False),
                "base_url": base_url,
                "api_key": api_key,
                "max_tokens": 8000,
            },
            {
                "model": FALLBACK_MODEL,
                "system": transcription_system_with_context(request_boxes=False),
                "base_url": base_url,
                "api_key": api_key,
                "max_tokens": 8000,
            },
        ]
        text, usage = transcribe_with_fallbacks(Path(panel_path), variants, usable=usable)
        tokens = int(usage.get("total_tokens", 0) or 0)
        store_read(Path(panel_path), cache_spec, text, tokens)
    plain, boxes = parse_transcription_response(text)
    return plain.split("\n"), normalized_bands(plain.split("\n"), boxes, panel_h), tokens


def main(argv: list[str] | None = None) -> int:

    parser = argparse.ArgumentParser(prog="eval_batch")
    parser.add_argument("batch_ids", nargs="+")
    parser.add_argument("--model", default="z-ai/glm-4.6v")
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--work-dir", type=Path, default=WORK_DIR)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--pages", default="", help="comma-separated page stems; empty = all")
    args = parser.parse_args(argv)
    api_key = args.api_key or os.environ.get("OPENROUTER_API_KEY")

    t0 = monotonic()
    total_written = 0
    total_refused = 0
    total_tokens = 0
    reports: list[dict[str, Any]] = []

    for batch_id in args.batch_ids:
        result = _process_batch(
            batch_id,
            args.work_dir,
            (args.model, args.base_url, api_key),
            args.workers,
            wanted={s for s in args.pages.split(",") if s},
        )
        reports.append(result)
        total_written += result["written"]
        total_refused += result["refused"]
        total_tokens += result["tokens"]

    elapsed = round(monotonic() - t0, 1)
    print(
        json.dumps(
            {
                "written": total_written,
                "refused": total_refused,
                "tokens": total_tokens,
                "elapsed_s": elapsed,
                "reports": reports,
            },
            indent=1,
        )
    )
    return 0


def _detect_phase(
    pages_with_text: list[Path], batch: tuple[str, Path, Any], panel_dir: Path, engine: Any
) -> dict[str, dict[str, Any]]:
    """Phase 1 of the batch (extracted 2026-08-29 for the complexity
    bar): detect each page's content panel. A page whose stored layout
    is current and clean skips the rec entirely."""
    batch_id, guess_dir, store = batch
    panels: dict[str, dict[str, Any]] = {}
    for ip in pages_with_text:
        pg = ip.stem
        lp = f"{batch_id}/ocr-guess/{pg}.layout.json"
        try:
            layout = load_layout_store(store, lp)
        # lucidlint: ignore swallow a stored layout unreadable falls back to a fresh run; the error is surfaced
        except Exception as exc:
            print(f"  {pg}: stored layout unreadable ({str(exc)[:60]}) — reprocessing", file=sys.stderr)
            layout = None
        if layout is not None and layout_is_current(layout) and not validate_layout(layout):
            print(f"  {pg}: stored layout clean, skipping", file=sys.stderr)
            continue
        prep = prep_panel(ip, layout, panel_dir, pg)
        if not prep:
            continue
        try:
            pieces = _detect_pieces(engine, Path(prep["path"]))
            rows = cluster_rows(pieces)
            unions = [union(r) for r in rows]
            panels[pg] = {
                "path": prep["path"],
                "h": prep["h"],
                "x0": prep["x0"],
                "y0": prep["y0"],
                "unions": unions,
            }
        # lucidlint: ignore swallow the batch isolates one page's failure; the rec error is surfaced above
        except Exception as exc:
            print(f"  rec {pg} FAILED: {str(exc)[:80]}", file=sys.stderr)
    return panels


def _make_engine() -> Any:
    pass  # type: ignore[missing-import]  # paddleocr lives only in .venv-htr


def _vlm_read_phase(
    panels: dict[str, dict[str, Any]], conn: tuple[str, str, str | None], workers: int
) -> tuple[dict[str, tuple[list[str], list[tuple[float, float, str]], int, list[dict]]], float]:
    """Phase 2 of the batch (extracted 2026-08-29 for the complexity
    bar): read every panel's text with the VLM in parallel. The read is
    a pure function of the panel bytes + the call spec, so the cache
    makes unchanged pages free."""
    model, base_url, api_key = conn
    t0 = monotonic()
    vlm_results: dict[str, tuple[list[str], list[tuple[float, float, str]], int, list[dict]]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for pg, panel in panels.items():
            row_count = len(panel["unions"])
            futures[pool.submit(_vlm_read, panel["path"], panel["h"], row_count, conn)] = pg
        for future in as_completed(futures):
            pg = futures[future]
            try:
                texts, bands, tok = future.result()
                report = _self_report_for(Path(panels[pg]["path"]), "\n".join(texts))
                vlm_results[pg] = (texts, bands, tok, report)
                print(f"  vlm {pg}: {len(bands)} bands, {tok} tok", file=sys.stderr)
            # lucidlint: ignore swallow one page's VLM failure; surfaced above, the batch continues
            except Exception as exc:
                print(f"  vlm {pg} FAILED: {exc}", file=sys.stderr)
    return vlm_results, round(monotonic() - t0, 1)


def _page_gate_bad(page_unions: list[list[float]], labels: list[str], im: Any) -> list[int]:
    """The image-aware gates (extracted 2026-08-29 for the complexity
    bar): ink under every box, one text band per box, a glyph-plausible
    label. A page failing here writes nothing — refusal is the system
    telling the truth."""
    return [
        i
        for i, u in enumerate(page_unions)
        if not has_ink(u, im)
        or text_line_count(u, im) > 1
        or glyph_extent_violation(labels[i], u, orientation_from_aspect(u))
    ]


def _assemble_page(
    page: tuple[str, list[str], Any, list[dict], list[list[float]], float, float],
    batch_ctx: tuple[Path, Any, str, tuple[str, str, str | None], int],
) -> tuple[list[dict], list[int], int, int]:
    """One page's assembly (extracted 2026-08-29 for the complexity
    bar): the unions to page space, the label matching, the image-aware
    gates, the self-report flags. The refusal counters and the write
    stay in the caller."""
    pg, texts, bands, report, unions, x0, y0 = page
    oriented_dir, _store, _batch_id, _conn, _workers = batch_ctx
    with Image.open(oriented_dir / f"{pg}.jpg") as im:
        pw, ph = im.size
        page_unions = [
            part
            for u in (offset_box(v, x0, y0) for v in unions)
            for part in (split_by_bands(u, im) if text_line_count(u, im) > 1 else [u])
        ]
        labels = match_labels(page_unions, texts, bands)
        bad = _page_gate_bad(page_unions, labels, im)
    out_lines = [
        {
            "index": i,
            "text": labels[i],
            "box": [round(v) for v in u],
            "conf": 1.0,
            "words": [],
            "box_source": "ink",
            "orientation": orientation_from_aspect(u),
        }
        for i, u in enumerate(page_unions)
    ]
    by_line = selfreport_words_by_line([ln["text"] for ln in out_lines], report)
    flagged = sum(len(v) for v in by_line.values())
    if flagged:
        print(f"  {pg}: {flagged} self-flagged words", file=sys.stderr)
    for ln in out_lines:
        ln["words"] = flag_line_words(ln["text"], by_line.get(ln["index"], set()))
    return out_lines, bad, pw, ph


def _assemble_phase(
    panels: dict[str, dict[str, Any]],
    vlm_results: dict[str, tuple[list[str], list[tuple[float, float, str]], int, list[dict]]],
    batch_ctx: tuple[Path, Any, str, tuple[str, str, str | None], int],
) -> tuple[int, int]:
    """Phase 3 of the batch (extracted 2026-08-29 for the complexity
    bar): assemble, validate and write each page's layout. The per-page
    recall/rescue passes fire only on the gates' refusals."""
    oriented_dir, store, batch_id, conn, workers = batch_ctx
    model, base_url, api_key = conn
    written = 0
    refused = 0
    for pg in sorted(panels):
        result = vlm_results.get(pg)
        if not result:
            continue
        texts, bands, _tok, report = result
        page = (pg, texts, bands, report, panels[pg]["unions"], panels[pg]["x0"], panels[pg]["y0"])
        out_lines, bad, pw, ph = _assemble_page(page, batch_ctx)
        if bad:
            refused += 1
            print(f"  {pg} REFUSED (image gates): {len(bad)} boxes off-ink or multi-line", file=sys.stderr)
            continue
        assembled = {"page": pg, "width": pw, "height": ph, "lines": out_lines, "unmatched": []}
        violations = validate_layout(assembled)
        if violations:
            refused += 1
            print(f"  {pg} REFUSED ({len(violations)}): {violations[0][:80]}", file=sys.stderr)
            continue
        write_layout_store(assembled, store, f"{batch_id}/ocr-guess/{pg}.layout.json")
        written += 1
        print(f"  {pg} written ({len(out_lines)} lines)", file=sys.stderr)
    return written, refused


def _process_batch(
    batch_id: str,
    work_dir: Path,
    conn: tuple[str, str, str | None],
    workers: int,
    wanted: set[str] | None = None,
) -> dict[str, Any]:
    model, base_url, api_key = conn
    oriented_dir = work_dir / batch_id / "oriented"
    guess_dir = work_dir / batch_id / "ocr-guess"
    store = PipelineStore(work_dir)
    image_paths = sorted(oriented_dir.glob("*.jpg"))

    pages_with_text = [p for p in image_paths if (guess_dir / p.with_suffix(".txt").name).exists()]
    if wanted:
        pages_with_text = [p for p in pages_with_text if p.stem in wanted]
    print(f"batch {batch_id}: {len(pages_with_text)} pages", file=sys.stderr)

    # Phase 1: rec-detect each page's content panel (local, sequential);
    # Phase 2: the VLM reads (parallel, network-bound). The panels must
    # live through BOTH — a TemporaryDirectory here would delete them
    # before Phase 2 reads them (2026-08-22); cleanup waits for the
    # finally below.
    engine = _make_engine()
    panel_dir = Path(tempfile.mkdtemp(prefix="eval-batch-"))
    try:
        panels = _detect_phase(pages_with_text, (batch_id, guess_dir, store), panel_dir, engine)
        vlm_results, vlm_elapsed = _vlm_read_phase(panels, (model, base_url, api_key), workers)
    finally:
        # the panels must live through Phase 2 (2026-08-22) — and die
        # after it: the uncleaned mkdtemp dirs leaked ~2.8G of full-page
        # PNGs into /tmp across five batch runs and filled the tmpfs
        # that pytest's own tempdir shares (2026-08-26).
        shutil.rmtree(panel_dir, ignore_errors=True)

    batch_ctx = (oriented_dir, store, batch_id, (model, base_url, api_key), workers)
    written, refused = _assemble_phase(panels, vlm_results, batch_ctx)
    return {
        "batch": batch_id,
        "pages": len(pages_with_text),
        "written": written,
        "refused": refused,
        "tokens": sum(r[2] for r in vlm_results.values()),
        "vlm_elapsed_s": vlm_elapsed,
    }


def _detect_pieces(engine: Any, panel_path: Path) -> list[list[float]]:
    """The rec's detection pieces (the REAL ink)."""
    # lucidlint: ignore inline-import the .venv-htr seam — paddleocr lives only in .venv-htr
    from tools.layout_detect import detect_page

    raw = detect_page(engine, panel_path)
    return [[float(v) for v in d["box"]] for d in raw["detections"] if d["box"]]
