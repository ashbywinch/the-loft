"""The layout pass's segment stage (TECH-SPEC §16.16/§16.17).

The §16.17 single pass: ONE multimodal call per page returns every text
segment with verbatim text, orientation, and a pixel box
(tools.segment_page); this module builds the page Layout from those
segments and persists it through the store. When the ink gate (Gate D)
finds a box on blank card, a bounded SECOND pass re-asks for just the
failed lines with a deterministic, failure-facts prompt
(_second_pass) — the gates stay the arbiter of what serves.

Runs on the MAIN venv (urllib + PIL — no detector engine, no
.venv-htr; the paddle stack left the layout path with the
detect-then-match pipeline it served, 2026-09-06).

Usage: make pipeline ARGS="layout <batch_id> [page ...]" — or
python -m tools.layout_detect <batch_id> [--work-dir DIR] [page ...]
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from tools.layout import (  # lucidlint: ignore private-import the single-pass build consumes the house per-word builder
    Layout,
    _words_out,
    drop_inkless_boxes,
    write_layout_store,
)
from tools.loft_paths import WORK_DIR
from tools.pipeline_store import PipelineStore
from tools.segment_page import (
    SegmentPageError,
    page_needs_two_pass,
    relocate_segments,
    segment_page,
    segment_page_two_pass,
)
from tools.store import DiskStore  # noqa: F401
from tools.text import vlm_line_words

# The proven engine config (spike, 2026-08-15) — the rec model rides along
# (its noisy text IS the cross-reader confidence signal).
# Tolerances for the coordinate-space assertion: the engine maps detections
# back to the input image; a coordinate straying past the image bounds means
# the mapping changed and every stored box would be wrong.
_BOUNDS_EPSILON = 4.0


def run_batch(
    batch_id: str,
    page_names: list[str] | None,
    work_dir: Path,
    urlopen=None,
    api_key=None,
) -> int:
    """Layout the batch's oriented pages; page_names narrows the set (None =
    every oriented page). Returns 0 on success. Every run's diagnostics —
    the per-clip VLM calls (timing + tokens + failures), the drops, the
    per-page results — are teed to ``work/<batch>/logs/layout-<run>.log``
    so a problematic run is examinable AFTER the fact (2026-08-22: the
    rebuild timeouts were undiagnosable — the calls were silent)."""
    oriented_dir = work_dir / batch_id / "oriented"
    guess_dir = work_dir / batch_id / "ocr-guess"
    if not oriented_dir.is_dir():
        print(f"layout: no oriented dir for batch {batch_id!r}", file=sys.stderr)
        return 1
    # all jpgs, not just page-*: phone-export duplicates arrive as names
    # like "1782635795946-5f7905a9~2.jpg" (the PhotoScan batch, 2026-08-16)
    # and must not be silently skipped by the layout pass
    pages = [p for p in sorted(oriented_dir.glob("*.jpg"))]
    wanted: set[str] = set()
    if page_names:
        # The CLI takes bare stems ("page-02"); the glob yields full
        # filenames ("page-02.jpg") — normalize so the filter actually
        # matches (2026-08-20: a raw `p.name in wanted` silently produced
        # an empty page list and exit 0, a no-op that looked like success).
        wanted = {p if p.endswith(".jpg") else p + ".jpg" for p in page_names}
        pages = [p for p in pages if p.name in wanted]
        if not pages:
            print(
                f"layout: FATAL — none of the requested pages exist in {oriented_dir}: {', '.join(sorted(wanted))}",
                file=sys.stderr,
            )
            return 2
    outcomes = [
        _process_page(image, guess_dir, (batch_id, page_names, wanted, work_dir), urlopen=urlopen, api_key=api_key)
        for image in pages
    ]
    if 2 in outcomes:
        return 2
    refused = outcomes.count(1)
    missing = _missing_guesses(guess_dir, pages, outcomes)
    if missing:
        print(
            f"layout: {len(missing)} page(s) skipped — no guess text: {', '.join(sorted(missing))}",
            file=sys.stderr,
        )
    return 1 if refused else 0


def _missing_guesses(guess_dir: Path, pages: list[Path], outcomes: list[int]) -> list[str]:
    """The quietly-skipped pages: laid out 0 (or skipped implicitly) but
    with no guess text — extracted for the complexity bar."""
    return [
        image.name
        for image, outcome in zip(pages, outcomes, strict=True)
        if outcome == 0 and not (guess_dir / image.with_suffix(".txt").name).exists()
    ]


def _process_page(
    image: Path,
    guess_dir: Path,
    batch: tuple[str, list[str] | None, set[str], Path],
    urlopen=None,
    api_key=None,
) -> int:
    """Lay ONE page out — 0 = laid out or quietly skipped, 1 = refused
    (the gates: boxless lines now fail the run, 2026-08-22), 2 = fatal
    (an explicitly requested page has no guess text). Split from
    run_batch for the complexity bar. ``batch`` = (batch_id, page_names,
    wanted, work_dir)."""
    batch_id, page_names, wanted, work_dir = batch
    vlm_path = guess_dir / image.with_suffix(".txt").name
    if not vlm_path.exists():
        rc = _warn_missing_guess(image.name, vlm_path.name, page_names, wanted)
        return 2 if rc else 0
    try:
        _layout_one(image, guess_dir, batch, urlopen=urlopen, api_key=api_key)
        return 0
    except (ValueError, SegmentPageError) as exc:
        # the refusal is recorded, not fatal (the per-page pattern) — and
        # the single pass's garbage-response failure refuses the page the
        # same way: no fallback to the old detect-then-match path
        # (2026-09-06, user: "do NOT fall back to the old path, it
        # doesn't work").
        print(f"layout: {image.name} refused — {str(exc)[:160]}", file=sys.stderr)
        return 1


def _build_page_layout(image: Path, guess_dir: Path, urlopen=None, api_key=None):
    """The §16.17 single-pass build: ONE multimodal call returns every
    text segment with verbatim text, orientation, and a pixel box — text
    detection, box detection and transcription in one pass. No detector,
    no matching: the segments carry text and box together, so there is
    nothing to join (2026-09-06, the user: the old detect-then-match path
    does not work — do not fall back to it). The self-report's red-word
    flags apply to the words by line index, as before."""
    if page_needs_two_pass(image):
        segments, _usage = segment_page_two_pass(image, urlopen=urlopen, api_key=api_key)
    else:
        segments, _usage = segment_page(image, urlopen=urlopen, api_key=api_key)
    vlm_text = "\n".join(s["text"] for s in segments)

    selfreport_path = guess_dir / f"{image.stem}.selfreport.json"
    selfreport = None
    if selfreport_path.exists():
        selfreport = json.loads(selfreport_path.read_text(encoding="utf-8"))
    report_by_line: dict[int, set[str]] = {}
    use_selfreport = selfreport is not None
    if selfreport:
        for entry in selfreport:
            line_no = entry.get("line")
            if isinstance(line_no, int) and 1 <= line_no <= len(segments):
                report_by_line.setdefault(line_no - 1, set()).add(str(entry.get("word", "")))

    with Image.open(image) as im:
        width, height = im.size

    lines: list[dict[str, Any]] = []
    for i, seg in enumerate(segments):
        vw = vlm_line_words(seg["text"])
        words_out = _words_out(
            vw,
            selfreport_line=report_by_line.get(i),
            rec_words=[],
            use_selfreport=use_selfreport,
        )
        line_conf = (sum(w["conf"] for w in words_out) / len(words_out)) if words_out else 0.0
        lines.append(
            {
                "index": i,
                "text": seg["text"],
                "box": seg["box"],
                "conf": line_conf,
                "words": words_out,
                "orientation": seg["orientation"],
                "box_source": "segment",
            }
        )
    vlm_path = guess_dir / image.with_suffix(".txt").name
    vlm_path.write_text(vlm_text + "\n", encoding="utf-8")
    return Layout(image.stem, width, height, lines, [])


def _layout_one(
    image: Path,
    guess_dir: Path,
    batch: tuple[str, list[str] | None, set[str], Path],
    urlopen=None,
    api_key=None,
) -> None:
    """Layout ONE page: read its guess/orientation/self-report, run the
    single-pass layout build, and persist via the store. ``batch`` =
    (batch_id, page_names, wanted, work_dir)."""
    batch_id, page_names, wanted, work_dir = batch
    layout = _build_page_layout(image, guess_dir, urlopen=urlopen, api_key=api_key)
    boxes_before_gate_d = {ln.get("index"): ln.get("box") for ln in layout.lines}
    # Gate D (2026-08-20): a boxed line must contain the ink it claims —
    # page-03's transcription boxes sat ~200px above the real text, and
    # a well-proportioned box in a blank region is an estimate, not an
    # anchor; the box is dropped (the line stays flagged).
    inkless = layout.drop_inkless(image)
    if inkless:
        print(f"layout: {image.name} — {inkless} box(es) with no ink dropped (Gate D)", file=sys.stderr)
    # a zero-extent box skips the ink probe (nothing to crop) — retire it
    # here so the second pass can re-ask (2026-09-07)
    degenerate = _drop_degenerate_boxes(layout.lines)
    if degenerate:
        print(f"layout: {image.name} — {degenerate} degenerate box(es) dropped", file=sys.stderr)
    if inkless or degenerate:
        _second_pass(image, layout, boxes_before_gate_d, urlopen=urlopen, api_key=api_key)
    # Gate E as a correction (2026-08-22): a box that claims another
    # line's region with different text shadows the confirmed anchor —
    # page-03's boxless lines sat on the P.S. margin, refusing the page
    # at the serve gate. The lower-confidence box drops.
    conflicts = layout.drop_conflicts()
    if conflicts:
        print(f"layout: {image.name} — {conflicts} conflicting box(es) dropped (Gate E)", file=sys.stderr)
    out = guess_dir / f"{image.stem}.layout.json"
    # the store roots at the work_dir this run was GIVEN, not the global
    # WORK_DIR: the hermetic tests pass a tmp dir, and the hardcoded root
    # wrote to /run/media/... on CI — which has no work disk (2026-08-29,
    # the build-and-test failure on all four PRs)
    store = PipelineStore(work_dir)
    store_path = str(Path(batch_id) / "ocr-guess" / out.name)
    write_layout_store(layout.to_dict(), store, store_path)
    flagged = sum(1 for line in layout.lines for w in line["words"] if w["conf"] == 0.0)
    print(
        f"layout: {image.name} {len(layout.lines)} lines, "
        f"{len(layout.unmatched)} unmatched, {flagged} flagged words -> {out.name}"
    )


def _drop_degenerate_boxes(lines: list[dict[str, Any]]) -> int:
    """Gate D's blind spot: a zero-extent box (the model sat a line on
    the page's edge) has nothing to crop, so the ink probe skips it.
    Retire the box here — the second pass is the line's way back in
    (2026-09-07). Returns the count retired."""
    dropped = 0
    for line in lines:
        box = line.get("box")
        if isinstance(box, list) and len(box) == 4 and (box[2] <= box[0] or box[3] <= box[1]):
            line["box"] = None
            dropped += 1
    return dropped


def _second_pass(
    image: Path,
    layout: Layout,
    boxes_before: dict[int, list[float] | None],
    urlopen=None,
    api_key=None,
) -> None:
    """The bounded second pass (2026-09-07, user: no use spending tokens
    on things that are already correct): the lines whose geometry failed
    — Gate D's blank-card boxes AND degenerate boxes (zero extent, or
    sitting off the page) — get ONE repair call naming only them,
    prompted by the recorded failure facts. A relocated box must clear
    the SAME checks — non-degenerate, and carrying ink: the gates are
    the arbiter, never the model — and a "not present" verdict drops the
    segment loudly (a first-pass invention is not evidence). Anything
    unresolved stays boxless for Gate F to refuse, exactly as without
    the pass."""
    with Image.open(image) as im:
        width, height = im.size

    def _degenerate(box: Any) -> bool:
        return isinstance(box, list) and len(box) == 4 and (box[2] <= box[0] or box[3] <= box[1])

    failures = []
    for line in layout.lines:
        rejected = boxes_before.get(line.get("index"))
        if line.get("box") is not None:
            continue
        if not isinstance(rejected, list) or len(rejected) != 4:
            continue
        failures.append(
            {
                "index": int(line["index"]),
                "text": str(line.get("text", "")),
                "px": rejected,
                "box_2d": [
                    rejected[0] * 1000.0 / width,
                    rejected[1] * 1000.0 / height,
                    rejected[2] * 1000.0 / width,
                    rejected[3] * 1000.0 / height,
                ],
                "reason": (
                    "the box is degenerate (zero extent) or sits outside the page"
                    if _degenerate(rejected)
                    else "the box holds no ink"
                ),
            }
        )
    if not failures:
        return
    answer = relocate_segments(image, failures, urlopen=urlopen, api_key=api_key)
    by_index = {int(ln["index"]): ln for ln in layout.lines}
    for index, px_box in answer["relocated"].items():
        line = by_index[index]
        probe = [{"box": list(px_box)}]
        usable = px_box[2] > px_box[0] and px_box[3] > px_box[1]
        if usable and drop_inkless_boxes(probe, image) == 0:
            line["box"] = probe[0]["box"]
            line["box_source"] = "repaired"
            print(f"layout: {image.name} line {index} — the second pass relocated it", file=sys.stderr)
        else:
            print(
                f"layout: {image.name} line {index} — the second pass's box fails the checks too; Gate F will refuse",
                file=sys.stderr,
            )
    for index in answer["not_present"]:
        line = by_index[index]
        layout.lines.remove(line)
        print(
            f"layout: {image.name} line {index} ({str(line.get('text', ''))[:30]!r}) — "
            "the second pass found no such text on the page; segment dropped",
            file=sys.stderr,
        )


def _warn_missing_guess(image_name: str, txt_name: str, page_names: list[str] | None, wanted: set[str]) -> int:
    """A page with no guess text must never be laid out from geometry alone
    (2026-08-20 — the bad page-02 layout was exactly that). Explicitly
    requested pages are fatal (2); implicit pages are skipped loudly with
    a stderr warning. Returns the exit code to return, 0 to continue."""
    if page_names and image_name in wanted:
        print(
            f"layout: FATAL — no guess text for {image_name} (requested explicitly). "
            f"Run the guess stage first, or restore {txt_name}.",
            file=sys.stderr,
        )
        return 2
    print(f"layout: no guess text for {image_name} — skipping", file=sys.stderr)
    return 0


@contextlib.contextmanager
def _run_log(work_dir: Path, batch_id: str) -> Any:
    """Tee the run's stderr diagnostics to ``work/<batch>/logs/
    layout-<run>.log`` — a problematic run stays examinable after the
    fact (2026-08-22: the rebuild timeouts were undiagnosable because the
    layout stage's VLM calls were silent)."""
    # a FRESH file per run (the microseconds + the pid make the name
    # unique) — never an accumulating log the runs keep appending to
    # (2026-08-22, user: no one big growing log file)
    log_path = work_dir / batch_id / "logs" / f"layout-{datetime.now():%Y%m%d-%H%M%S-%f}-{os.getpid()}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("w", encoding="utf-8")
    real_stderr = sys.stderr

    class _Tee:
        def write(self, text: str) -> int:
            real_stderr.write(text)
            log.write(text)
            return len(text)

        def flush(self) -> None:
            real_stderr.flush()
            log.flush()

    try:
        with contextlib.redirect_stderr(_Tee()):
            yield log_path
    finally:
        log.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="layout_detect", description="The layout pass per batch")
    parser.add_argument("batch_id")
    parser.add_argument("pages", nargs="*", help="optional page names to limit the pass")
    parser.add_argument("--work-dir", type=Path, default=WORK_DIR)
    args = parser.parse_args(argv)
    with _run_log(args.work_dir, args.batch_id) as log_path:
        print(f"layout: run log -> {log_path}", file=sys.stderr)
        # §16.17: the single-pass segment stage IS the layout build — one
        # VLM call per page for text, boxes and orientation. No detector
        # engine: the paddle stack (and the .venv-htr interpreter it
        # required) is gone from the layout path (2026-09-06).
        return run_batch(args.batch_id, args.pages or None, args.work_dir)


if __name__ == "__main__":
    sys.exit(main())
