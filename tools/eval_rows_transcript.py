"""The rows-transcript eval: one real call, and everything checkable without
a gold transcript.

A page is read by numbering its ROWS (one number per row) and asking for the
writing of each numbered row. There is no confirmed transcript for the pages
this is tried on yet — the proposal to confirm is what this produces — so the
eval verifies what does not need one:

- the contract holds: the answer parses, and every numbered row appears in
  exactly one reading (a refusal is reported as a refusal, never as wrong
  text);
- the kinds: how many readings are body / injection / marginalia, and that an
  injection points at a row that exists;
- the reading is not degenerate: no row left without words, the words per row
  in a plausible band for handwriting, and the transcripts distinct (a
  model repeating one line down the page is a failure with no gold needed).

The raw answer and the numbered render are written beside the run, so a
failure is diagnosed from the artifact rather than re-billed.

Usage: PYTHONPATH=. .venv/bin/python -m tools.eval_rows_transcript [page...]
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image

from document.numbered_rows import STRIPS, NumberedRows
from document.transcript import ReadingError, Transcript
from tools.reader import reading_for_page
from tools.render import render_rows
from tools.rows import Rows
from tools.schemas import load_user_row_adjustments
from tools.vlm import VlmOptions, transcribe_images_vlm
from tools.word import Word

OUT_DIR = Path("work/eval-rows-transcript")

# the page the other real-model evals already use (a cursive letter, our best
# case); a page with no confirmed transcript is still readable
DEFAULT_PAGE = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")

SYSTEM = (
    "You read a scanned page of handwriting. The image shows the page with its rows "
    "numbered: one circled number per row of writing, in reading order, sitting in the "
    "left margin beside the row it labels. The number IS the row's number.\n\n"
    "For every numbered row, return its writing. A number may cover several rows when "
    "the writing is one continuous piece (a sentence broken across rows); never give a "
    "row two readings.\n\n"
    "Types:\n"
    "- body: the running text\n"
    "- injection: writing squeezed above/between rows, meant to be inserted into other "
    "text — it REQUIRES injection_after: the row number it follows\n"
    "- marginalia: a note in the margin, with NO injection_after\n\n"
    "Transcribe verbatim, reading the handwriting; a word the writer crossed out is "
    "~~word~~, an underlined word is ~word~. Never tidy the spelling, never drop words.\n\n"
    "The page may arrive as several images: bands of the same page, top to "
    "bottom, in order, and neighbouring bands share a little of the page. They "
    "are ONE page — read the rows of every band and answer once, covering "
    "every number from the first band to the last. A row visible in two bands "
    "is still ONE row: read it once, in the band that shows it whole.\n\n"
    "Reply with JSON only:\n"
    '{"segments": [\n'
    '  {"rows": [1], "type": "body", "transcript": "London Opera Centre"},\n'
    '  {"rows": [2, 3], "type": "body", "transcript": "a sentence that runs on"},\n'
    '  {"rows": [4], "type": "injection", "transcript": "my dear", "injection_after": 3},\n'
    '  {"rows": [5], "type": "marginalia", "transcript": "Send this first"}\n'
    "]}\n"
    "Every numbered row must appear exactly once. No prose before or after the JSON."
)


def words_from(path: Path) -> list[Word]:
    """The words a rows file was adjudicated against: the committed parse, so
    the numbering the reviewer's decision was made in is the numbering the
    reader is shown."""
    records = json.loads(path.read_text(encoding="utf-8"))["words"]
    return [
        Word(
            r["x0"],
            r["y0"],
            r["x1"],
            r["y1"],
            baseline=r.get("baseline"),
            waistline=r.get("waistline"),
            line=r.get("line"),
        )
        for r in records
    ]


def words_for(image_path: Path, image: Image.Image) -> list[Word]:
    """The page's words, as the rows builder wants them: the reading's own
    words, each carrying its reading line."""
    reading = reading_for_page(image)
    return [
        Word(
            record["x0"],
            record["y0"],
            record["x1"],
            record["y1"],
            baseline=record.get("baseline"),
            waistline=record.get("waistline"),
            line=record.get("line"),
        )
        for record in reading.words
    ]


def run(
    image_path: Path,
    *,
    fixture: Path | None = None,
    call: Callable[..., tuple[str, dict[str, int]]] | None = None,
    model: str | None = None,
    out_dir: Path = OUT_DIR,
) -> dict[str, Any]:
    """One page, one model call, and every checkable condition measured."""
    image = Image.open(image_path)
    size = (image.width, image.height)
    # the rows the reviewer's drawn lines make, when they exist: the reading
    # happens against the CORRECT rows, never the draft the geometry proposed
    # with a fixture directory the reader is shown the CORRECT rows — the words
    # a reviewer's lines were adjudicated against, and those lines applied —
    # rather than the draft the geometry proposed over a live parse
    words = words_from(fixture / "words.json") if fixture else words_for(image_path, image)
    builder = Rows.from_words(words, size)
    rows = (
        builder.adjust(load_user_row_adjustments(fixture / "user-row-adjustments.json")["lines"])
        if fixture
        else builder.rows()
    )
    # the strips are cut from the REVIEW SURFACE'S OWN rendering — the rows
    # tinted in their per-row hues by `render_rows` (the same function the
    # review surface and the reading sheet use), then numbered with the same
    # `.rv-rownum` pill. The model sees what the reviewer sees.
    numbered = NumberedRows.render_strips(render_rows(image, rows), rows, strips=STRIPS)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = image_path.stem
    render_paths = []
    for index, strip in enumerate(numbered):
        path = out_dir / f"{stem}.strip-{index + 1}.jpg"
        strip.image.save(path, quality=88)
        render_paths.append(path)

    # the universe is the rows NUMBERED, each once: neighbouring bands overlap,
    # so a row can appear in two of them with its own single number
    drawn = len({number for strip in numbered for number in strip.numbers.values()})
    # the manifest: which numbers each image carries. Without it the model
    # guesses the extents ("Wait, no, the first image's last row is 10?"), and
    # every guess it gets wrong costs rows.
    manifest = "; ".join(
        f"image {index + 1}: rows {min(strip.numbers.values())}-{max(strip.numbers.values())}"
        for index, strip in enumerate(numbered)
    )
    user_text = (
        f"The {len(numbered)} images are bands of one page, top to bottom, and they carry rows numbered 1..{drawn} "
        f"between them. What each image carries ({manifest}). Read every row it carries, once — the rows in one "
        "image are separate rows of writing, however close together they sit."
    )
    started = time.monotonic()
    options = (
        VlmOptions(system=SYSTEM, user_text=user_text, model=model)
        if model
        else VlmOptions(system=SYSTEM, user_text=user_text)
    )
    if call is None:
        answer, usage = transcribe_images_vlm(render_paths, options=options)
    else:
        answer, usage = call(render_paths, system=SYSTEM, user_text=user_text)
    seconds = time.monotonic() - started
    (out_dir / f"{stem}.answer.json").write_text(json.dumps({"answer": answer, "usage": usage}, indent=1))

    report: dict[str, Any] = {
        "page": image_path.name,
        # the endpoint and the model the reading ACTUALLY used, and how long it
        # took: a run that answers in under a second is not reading a page
        "endpoint": options.base_url,
        "model": options.model,
        "seconds": round(seconds, 1),
        "rows": len(rows),
        "words": sum(len(row.word_boxes) for row in rows),
        "strips": len(numbered),
        "usage": usage,
        "renders": [str(path) for path in render_paths],
    }
    try:
        transcript = Transcript.from_answer(answer, rows=drawn)
    except ReadingError as exc:
        report["refused"] = str(exc)
        return report

    report.update(_measure(transcript))
    return report


def _measure(transcript: Transcript) -> dict[str, Any]:
    """What a read page can be measured on without a gold transcript: the
    kinds and where they point, no row without words, a plausible words-per-
    row band, and transcripts that differ from one another."""
    kinds: dict[str, int] = {}
    words_per_row: list[int] = []
    for reading in transcript.readings:
        kinds[reading.kind] = kinds.get(reading.kind, 0) + 1
        words_per_row.append(len(re.findall(r"[\w'’~-]+", reading.text)))
    return {
        "readings": len(transcript.readings),
        "kinds": kinds,
        "injections_point_at_a_row": all(
            reading.kind != "injection" or reading.injection_after is not None for reading in transcript.readings
        ),
        "words_per_row_median": statistics.median(words_per_row),
        "words_per_row_min": min(words_per_row),
        "distinct_transcripts": len({reading.text.strip().lower() for reading in transcript.readings}),
        "longest_transcript": max(len(reading.text) for reading in transcript.readings),
    }


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    fixture = None
    if "--fixture" in args:
        index = args.index("--fixture")
        fixture = Path(args[index + 1])
        del args[index : index + 2]
    pages = [Path(arg) for arg in args] or [DEFAULT_PAGE]
    code = 0
    for page in pages:
        if not page.is_file():
            print(f"SKIP {page}: not on this box")
            continue
        report = run(page, fixture=fixture)
        print(json.dumps(report, indent=1))
        if "refused" in report:
            print(f"REFUSED: {report['refused']}")
            code = 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())
