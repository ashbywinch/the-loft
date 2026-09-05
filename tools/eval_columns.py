"""The ink-column experiment (2026-08-22): the rec's detection pieces on
the rotated panel are the REAL ink (its recognition is garbage, but its
boxes are measurements). Cluster the pieces by x-proximity into the
message's line-columns; each column's union-box is the MEASURED line
box; the VLM reads each column's clip and labels it. The boxes come
from the ink, the text from the model that reads cursive — each engine
does what it is good at.

Usage: eval_columns.py <batch_id> <page> <panel-x0> <panel-y0> <panel-x1> <panel-y1>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from time import monotonic
from typing import Any

from paddleocr import (  # type: ignore[missing-import]  # the rec lives in .venv-htr; this script runs there
    PaddleOCR,  # noqa: F401
)
from PIL import Image

from tools.layout_detect import (  # noqa: E402  the rec engine config (paddleocr lives in .venv-htr, this script runs there)
    ENGINE,
    detect_page,
)
from tools.vlm import VlmError, parse_transcription_response, transcribe_image_vlm, transcription_system_with_context


def _cluster_rows(boxes: list[list[float]], gap: float = 50.0) -> list[list[list[float]]]:
    """The rec's pieces clustered by y-proximity into ROWS — the rotated
    panel's message lines are horizontal, so one line's pieces share the
    y-band (the 2026-08-22 mistake clustered by x, the wrong axis, and
    merged the whole message into one column). Returns the rows'
    piece-lists, top to bottom."""
    ordered = sorted(boxes, key=lambda b: (b[1] + b[3]) / 2)
    rows: list[list[list[float]]] = []
    for b in ordered:
        cy = (b[1] + b[3]) / 2
        if rows and cy - (rows[-1][-1][1] + rows[-1][-1][3]) / 2 < gap:
            rows[-1].append(b)
        else:
            rows.append([b])
    return rows


def _union(boxes: list[list[float]]) -> list[float]:
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


def run(
    batch_id: str,
    page: str,
    work_dir: Path,
    panel: tuple[int, int, int, int],
    model: str = "z-ai/glm-4.6v",
    base_url: str = "https://openrouter.ai/api/v1",
    api_key: str | None = None,
) -> dict[str, Any]:
    """The ink-column read: the rec's pieces on the rotated panel
    clustered into columns, each column's union-box labelled by the
    VLM, the boxes remapped into the page frame."""
    image_path = work_dir / batch_id / "oriented" / f"{page}.jpg"
    px0, py0, px1, py1 = panel
    with Image.open(image_path) as im:
        width, height = im.size
        panel_img = im.crop((px0, py0, px1, py1)).rotate(90, expand=True)
    rot_w, rot_h = panel_img.size
    # the rec's pieces (the .venv-htr engine — import here to keep the
    # main venv free of the heavy dependency)
    engine = PaddleOCR(**ENGINE)
    try:
        panel_path = Path("/tmp/panel-ink.png")
        panel_img.save(panel_path)
        raw = detect_page(engine, panel_path)
    finally:
        del engine
    pieces = [d["box"] for d in raw["detections"] if d["box"]]
    rows = _cluster_rows(pieces)
    lines: list[dict[str, Any]] = []
    tokens = 0
    failed = 0
    started = monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        for i, col in enumerate(rows):
            union = _union(col)
            crop_path = Path(tmp) / f"col-{i}.png"
            panel_img.crop((int(union[0]), int(union[1]), int(union[2]), int(union[3]))).save(crop_path)
            try:
                text, usage = transcribe_image_vlm(
                    crop_path,
                    model=model,
                    system=transcription_system_with_context(),
                    base_url=base_url or "https://openrouter.ai/api/v1",
                    api_key=api_key,
                    max_tokens=4000,
                )
                plain, _ = parse_transcription_response(text)
            except (VlmError, ValueError, KeyError, IndexError, TypeError) as exc:
                print(f"column {i} read FAILED: {str(exc)[:100]}", file=sys.stderr)
                failed += 1
                continue
            tokens += int(usage.get("total_tokens", 0) or 0)
            label = plain.strip().split("\n")[0] if plain.strip() else ""
            # the union-box (the rotated frame!) -> the panel -> the page
            # the union is in the ROTATED frame's PIXELS — the inverse
            # without the normalized scaling: x = H' - y', y = x'
            ux0, uy0, ux1, uy1 = union
            page_box = [rot_h - uy1 + px0, ux0 + py0, rot_h - uy0 + px0, ux1 + py0]
            lines.append(
                {
                    "index": len(lines),
                    "text": label,
                    "box": [round(v) for v in page_box],
                    "conf": 1.0,
                    "words": [],
                    "box_source": "ink",
                }
            )
            print(
                f"column {i} [{round(union[0])},{round(union[1])}-{round(union[2])},{round(union[3])}]: {label[:44]!r}",
                file=sys.stderr,
            )
    elapsed = monotonic() - started
    report = {
        "page": page,
        "pieces": len(pieces),
        "rows": len(rows),
        "failed_rows": failed,
        "lines": len(lines),
        "boxless": 0,
        "tokens": tokens,
        "elapsed_s": round(elapsed, 1),
    }
    out = work_dir / batch_id / "ocr-guess" / f"{page}.columns.json"
    out.write_text(
        json.dumps(
            {"page": page, "width": width, "height": height, "lines": lines, "unmatched": []},
            indent=1,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval_columns", description="The ink-column experiment")
    parser.add_argument("batch_id")
    parser.add_argument("page")
    parser.add_argument("panel", nargs=4, type=int, help="x0 y0 x1 y1 (the panel in the page frame)")
    parser.add_argument("--model", default="z-ai/glm-4.6v")
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--work-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    from tools.loft_paths import WORK_DIR

    report = run(
        args.batch_id,
        args.page,
        args.work_dir or WORK_DIR,
        tuple(args.panel),
        model=args.model,
        base_url=args.base_url,
        api_key=args.api_key or os.environ.get("OPENROUTER_API_KEY"),
    )
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
