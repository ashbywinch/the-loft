"""The flag pass (2026-08-15, user-approved): the transcription model's OWN
doubt is the flag source. Runs in the main venv (tools/vlm.py — the model
API), one call per page: the model reviews its own transcription with line
numbers and marks the words it is least sure of, or that read oddly in
context (a misread often survives because the misread word still looks
word-like). The report lands as ``selfreport.json`` beside ocr-guess; the
layout pass merges it into the per-word flags (tools/layout.build_layout).

The cross-reader agreement this replaces over-flagged (75-90% of lines on
the real cursive pile — the detector's rec model garbles every line);
the probe: 4 flagged words on page-03 vs the cross-reader's 77.

Usage: python -m tools.selfreport <batch_id> [page ...]
"""

from __future__ import annotations

import concurrent.futures
import json
import sys
from pathlib import Path

from tools.atomic import atomic_write
from tools.selfreport_driver import run_cli
from tools.vlm import selfreport_words

REPORT_NAME = "selfreport.json"
_MAX_WORKERS = 6  # the VLM calls are IO-bound — no shared state between pages


def _process_page(image: Path, guess_dir: Path) -> None:
    """One page's self-report (a thread pool worker). Writes atomically
    when the model responds; fails loudly on error (the pool propagates
    the exception)."""
    guess_path = guess_dir / image.with_suffix(".txt").name
    if not guess_path.exists():
        print(f"selfreport: {image.name} — no guess text, skipping", file=sys.stderr)
        return
    out = guess_dir / f"{image.stem}.{REPORT_NAME}"
    if out.exists():
        print(f"selfreport: {image.name} — already done, reusing")
        return
    guess = guess_path.read_text(encoding="utf-8")
    print(f"selfreport: {image.name} — asking the model…", flush=True)
    unsure = selfreport_words(image, guess)
    atomic_write(out, json.dumps(unsure, indent=1, ensure_ascii=False) + "\n")
    print(f"selfreport: {image.name} -> {len(unsure)} unsure words -> {out.name}")


def run_batch(batch_id: str, page_names: list[str] | None, work_dir: Path) -> int:
    """Self-report every page with a guess text, in parallel (the VLM call
    is IO-bound — threads are the right concurrency model). Returns 0 on
    success, or 1 when a page's call fails."""
    guess_dir = work_dir / batch_id / "ocr-guess"
    oriented_dir = work_dir / batch_id / "oriented"
    if not guess_dir.is_dir() or not oriented_dir.is_dir():
        print(f"selfreport: no guess/oriented dirs for batch {batch_id!r}", file=sys.stderr)
        return 1
    pages = [p for p in sorted(oriented_dir.glob("*.jpg"))]  # all names, not just page-* (the phone-export duplicates)
    if page_names:
        wanted = set(page_names)
        pages = [p for p in pages if p.name in wanted]
    if not pages:
        return 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(_process_page, image, guess_dir): image for image in pages}
        for future in concurrent.futures.as_completed(futures):
            exc = future.exception()
            if exc is not None:
                print(f"selfreport: {futures[future].name} FAILED: {exc}", file=sys.stderr)
                return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(
        argv,
        prog="selfreport",
        description="The flag pass per batch",
        pages_help="optional page names to limit the pass",
        runner=run_batch,
    )


if __name__ == "__main__":
    sys.exit(main())
