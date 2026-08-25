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
from tools.box import orientation_from_aspect  # noqa: E402
from tools.gates import validate_layout
from tools.ink import cluster_rows, match_labels, union
from tools.layout import load_layout_store, write_layout_store  # noqa: E402
from tools.loft_paths import WORK_DIR  # noqa: E402
from tools.pipeline_store import PipelineStore  # noqa: E402
from tools.vlm import (  # noqa: E402
    parse_transcription_response,
    transcribe_image_vlm,
    transcription_system_with_context,
)


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
    from tools.layout_detect import detect_page  # inline: paddleocr lives in .venv-htr

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


def _vlm_read(
    panel_path: str, model: str, base_url: str, api_key: str | None, panel_h: int
) -> tuple[list[str], list[tuple[float, float, str]], int]:
    """One panel's VLM read — the text + the normalized bands."""
    text, usage = transcribe_image_vlm(
        Path(panel_path),
        model=model,
        system=transcription_system_with_context(),
        base_url=base_url,
        api_key=api_key,
        max_tokens=8000,
    )
    plain, boxes = parse_transcription_response(text)
    tokens = int(usage.get("total_tokens", 0) or 0)
    return plain.split("\n"), normalized_bands(plain.split("\n"), boxes, panel_h), tokens


def main(argv: list[str] | None = None) -> int:
    # lucidlint: ignore long-param-list the batch run's inputs are the CLI's own args
    parser = argparse.ArgumentParser(prog="eval_batch")
    parser.add_argument("batch_ids", nargs="+")
    parser.add_argument("--model", default="z-ai/glm-4.6v")
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--work-dir", type=Path, default=WORK_DIR)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    api_key = args.api_key or os.environ.get("OPENROUTER_API_KEY")

    t0 = monotonic()
    total_written = 0
    total_refused = 0
    total_tokens = 0
    reports: list[dict[str, Any]] = []

    for batch_id in args.batch_ids:
        result = _process_batch(batch_id, args.work_dir, args.model, args.base_url, api_key, args.workers)
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


# lucidlint: ignore long-param-list the batch's inputs are the CLI's own args


def _process_batch(
    batch_id: str, work_dir: Path, model: str, base_url: str, api_key: str | None, workers: int
) -> dict[str, Any]:
    """Process one batch's pages: rec-detect sequentially, then VLM-read
    in parallel, then assemble + write the layouts that pass validation."""
    oriented_dir = work_dir / batch_id / "oriented"
    guess_dir = work_dir / batch_id / "ocr-guess"
    store = PipelineStore(work_dir)

    image_paths = sorted(oriented_dir.glob("*.jpg"))
    pages_with_text = [p for p in image_paths if (guess_dir / p.with_suffix(".txt").name).exists()]
    print(f"batch {batch_id}: {len(pages_with_text)} pages", file=sys.stderr)

    # Phase 1: rec-detect each page's content panel (local, sequential)
    panels: dict[str, dict[str, Any]] = {}
    engine = _make_engine()
    # The panels persist through BOTH phases — a TemporaryDirectory here
    # would delete them before Phase 2 reads them (2026-08-22).
    panel_dir = Path(tempfile.mkdtemp(prefix="eval-batch-"))
    for ip in pages_with_text:
        pg = ip.stem
        lp = f"{batch_id}/ocr-guess/{pg}.layout.json"
        try:
            layout = load_layout_store(store, lp)
        except Exception:
            layout = None
        if layout is not None and not validate_layout(layout):
            print(f"  {pg}: stored layout clean, skipping", file=sys.stderr)
            continue
        prep = prep_panel(ip, layout, panel_dir, pg)
        if not prep:
            continue
        try:
            pieces = _detect_pieces(engine, Path(prep["path"]))
            rows = cluster_rows(pieces)
            unions = [union(r) for r in rows]
            panels[pg] = {"path": prep["path"], "h": prep["h"], "unions": unions}
            print(f"  rec {pg}: {len(pieces)} pieces -> {len(rows)} rows", file=sys.stderr)
        except Exception as exc:
            print(f"  rec {pg} FAILED: {str(exc)[:80]}", file=sys.stderr)

    # Phase 2: VLM-read all panels (parallel, network-bound)
    vlm_results: dict[str, tuple[list[str], list[tuple[float, float, str]], int]] = {}
    vlm_t0 = monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for pg, panel in panels.items():
            futures[pool.submit(_vlm_read, panel["path"], model, base_url, api_key, panel["h"])] = pg
        for future in as_completed(futures):
            pg = futures[future]
            try:
                texts, bands, tok = future.result()
                vlm_results[pg] = (texts, bands, tok)
                print(f"  vlm {pg}: {len(bands)} bands, {tok} tok", file=sys.stderr)
            except Exception as exc:
                print(f"  vlm {pg} FAILED: {exc}", file=sys.stderr)
    vlm_elapsed = round(monotonic() - vlm_t0, 1)

    # Phase 3: assemble + validate + write
    written = 0
    refused = 0
    batch_tokens = sum(r[2] for r in vlm_results.values())
    for pg in sorted(panels):
        result = vlm_results.get(pg)
        if not result:
            continue
        texts, bands, _ = result
        labels = match_labels(panels[pg]["unions"], texts, bands)
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
            for i, u in enumerate(panels[pg]["unions"])
        ]
        with Image.open(oriented_dir / f"{pg}.jpg") as im:
            pw, ph = im.size
        assembled = {"page": pg, "width": pw, "height": ph, "lines": out_lines, "unmatched": []}
        violations = validate_layout(assembled)
        if violations:
            refused += 1
            print(f"  {pg} REFUSED ({len(violations)}): {violations[0][:80]}", file=sys.stderr)
            continue
        write_layout_store(assembled, store, f"{batch_id}/ocr-guess/{pg}.layout.json")
        written += 1
        print(f"  {pg} written ({len(out_lines)} lines)", file=sys.stderr)

    return {
        "batch": batch_id,
        "pages": len(pages_with_text),
        "written": written,
        "refused": refused,
        "tokens": batch_tokens,
        "vlm_elapsed_s": vlm_elapsed,
    }


def _make_engine() -> Any:
    from paddleocr import PaddleOCR  # type: ignore[missing-import]  # paddleocr lives only in .venv-htr

    from tools.layout_detect import ENGINE  # inline: paddleocr lives in .venv-htr

    return PaddleOCR(**ENGINE)


if __name__ == "__main__":
    sys.exit(main())
