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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from document.numbered_rows import STRIPS, NumberedRows
from document.transcript import ReadingError, Transcript
from tools.reader import reading_for_page
from tools.rectangle import Rectangle
from tools.render import render_rows
from tools.rows import Rows
from tools.schemas import load_user_row_adjustments
from tools.vlm import VlmOptions, transcribe_images_vlm
from tools.word import Word

OUT_DIR = Path("work/eval-rows-transcript")
ALONE_MARGIN = 24  # px: air around a row read on its own

# the page the other real-model evals already use (a cursive letter, our best
# case); a page with no confirmed transcript is still readable
DEFAULT_PAGE = Path("/run/media/ashby/One Touch/Loft/work/adopt-20260813-201004/oriented/page-01.jpg")

SYSTEM = (
    "You read a scanned page of handwriting. The image shows the page with its rows "
    "numbered: one numbered chip per row of writing, in reading order, sitting beside "
    "the row it labels. The number IS the row's number.\n\n"
    "Each chip is drawn in the colour of the line it belongs to, and every line of "
    "writing is tinted that same colour: the chip and its row are one colour. When it "
    "is unclear which line a number belongs to — the writing is crowded, the chip sits "
    "between two lines, or two chips are close together — match the chip to the line "
    "whose tint is the SAME colour as the chip, and read that line as that number's "
    "row. The colour decides it; position alone may not.\n\n"
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
    # `.rv-rownum` pill. The model sees what the reviewer sees — WHICH INCLUDES
    # THE ROWS THEMSELVES: the user's drawn lines are the region boundaries,
    # and without them a side-by-side pair (page-01's 12/13) or a multi-line
    # region (its 25) has no visible edge, so the model reads every word right
    # and assigns whole sentences to whichever chip's leader is nearest.
    highlighted = render_rows(image, rows)
    if fixture:
        draw_user_rows(highlighted, load_user_row_adjustments(fixture / "user-row-adjustments.json")["lines"])
    numbered = NumberedRows.render_strips(highlighted, rows, strips=STRIPS)
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
    # ONE BAND PER CALL, each told exactly which rows it carries, and each
    # given what the earlier bands read — the same continuity the pipeline's
    # transcription prompt uses. A call per band also keeps every image at full
    # resolution (one band, not three) and asks for a smaller answer, so no
    # completion is cut off mid-JSON.
    started = time.monotonic()
    band_read = _Bands(
        numbered=numbered,
        render_paths=render_paths,
        stem=stem,
        out_dir=out_dir,
        model=model,
        call=call,
    ).read()
    every = sorted({number for strip in numbered for number in strip.numbers.values()})
    needing = _rows_needing_a_second_look(band_read.readings, every)
    alone = _read_the_unsettled(needing, image_path, fixture, call, out_dir)
    answer = _combined_answer(rows, band_read.readings, alone)
    seconds = time.monotonic() - started
    refusals, usage = band_read.refusals, band_read.usage

    report: dict[str, Any] = {
        "page": image_path.name,
        # the endpoint and the model the reading ACTUALLY used, and how long it
        # took: a run that answers in under a second is not reading a page
        "endpoint": _endpoint(),
        "model": model or "dynamic/image",
        "seconds": round(seconds, 1),
        "rows": len(rows),
        "words": sum(len(row.word_boxes) for row in rows),
        "strips": len(numbered),
        "usage": usage,
        "renders": [str(path) for path in render_paths],
    }
    # the reading is written where the page's other artifacts live. It was
    # computed and dropped before this (the reviewer's copy came from a step
    # run by hand), and an assembled reading nobody can read back is not a
    # reading the pipeline can serve.
    (out_dir / f"{image_path.stem}.answer.json").write_text(json.dumps({"answer": answer, "usage": usage}, indent=1))
    # the verdict is the COMBINED reading's: a band's refusal is a working
    # note (those rows were shown alone and may well have been read there)
    try:
        transcript = Transcript.from_answer(answer, rows=drawn)
    except ReadingError as exc:
        report["refused"] = str(exc)
        report["band_notes"] = refusals
        return report
    report["band_notes"] = refusals

    report.update(_measure(transcript))
    return report


def draw_user_rows(canvas: Image.Image, lines: list[list[tuple[float, float]]]) -> None:
    """The reviewer's drawn row lines, as the review surface draws them —
    yellow, over the paper. The lines are the row boundaries the model must
    see; the numbered chips already say which row is which.

    The lines are NORMALISED to the page (0..1), the form the fixture keeps and
    `Rows.adjust` consumes — drawn raw they were 44 specks in the top-left
    corner, which is not what the reviewer drew."""
    draw = ImageDraw.Draw(canvas)
    for line in lines:
        points = [(x * canvas.width, y * canvas.height) for x, y in line]
        draw.line(points, fill=(250, 210, 30), width=7)


def _read_the_unsettled(
    needing: list[int],
    image_path: Path,
    fixture: Path | None,
    call: Callable[..., tuple[str, dict[str, int]]] | None,
    out_dir: Path,
) -> dict[int, str]:
    """The rows the bands could not settle, read one at a time from their own
    crops — a crop that shows a neighbour's ink as well is why a row came back
    reading like its neighbour, so `alone_crop` clips each crop at the rows
    around it."""
    if not needing:
        return {}
    print(f"  {len(needing)} row(s) the bands could not settle: {needing} — reading them alone")
    alone: dict[int, str] = {}
    for number, text in read_rows_alone(image_path, numbers=needing, fixture=fixture, call=call, out_dir=out_dir):
        alone[number] = text
    return alone


def read_rows_alone(
    image_path: Path,
    *,
    numbers: list[int],
    fixture: Path | None = None,
    call: Callable[..., tuple[str, dict[str, int]]] | None = None,
    out_dir: Path = OUT_DIR,
) -> list[tuple[int, str]]:
    """Read named rows ONE AT A TIME, each from a crop of its own words only.

    A row is a piece of writing that the reviewer's lines separated, and in the
    tight stacks its band overlaps its neighbours' — a crop of the band shows
    three rows' ink, so the reader sees the same writing three times. Cropped to
    the row's own words, the piece is alone; the running transcript gives it the
    thread of the letter.
    """
    image = Image.open(image_path)
    words = words_from(fixture / "words.json") if fixture else words_for(image_path, image)
    builder = Rows.from_words(words, (image.width, image.height))
    rows = (
        builder.adjust(load_user_row_adjustments(fixture / "user-row-adjustments.json")["lines"])
        if fixture
        else builder.rows()
    )
    ordered = sorted(rows, key=lambda row: row.number)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = image_path.stem
    alone = _AloneReader(image=image, out_dir=out_dir, stem=stem, call=call, ordered=ordered)
    read: list[tuple[int, str]] = []
    for row in ordered:
        if row.number in numbers and row.word_boxes:
            read.append((row.number, alone.text_of(row, read)))
    # persisted like every other reading: a row read once is never paid for
    # twice, and the assembly below reads the file rather than re-asking
    (out_dir / f"{stem}.alone.json").write_text(
        json.dumps({"rows": {str(number): text for number, text in read}}, indent=1)
    )
    return read


def alone_crop(row: Any, ordered: list[Any], size: tuple[int, int]) -> Rectangle:
    """The rectangle that contains one row's words and almost nothing else.

    The words get the usual margin, EXCEPT vertically, where no margin may
    cross the midpoint of the gap to the neighbouring rows' bands. In the tight
    stacks the ±24px margin alone reached the neighbour line — page-01's 26 and
    27 both cropped to the same "year we performed the Mahler 8th" — and the row
    is the region the reviewer drew, so its own band is the unit that may not be
    entered."""
    place = next(index for index, other in enumerate(ordered) if other.number == row.number)
    above = ordered[place - 1].band.y1 if place else None
    below = ordered[place + 1].band.y0 if place + 1 < len(ordered) else None
    gap_top = (row.band.y0 - above) / 2 if above is not None else ALONE_MARGIN
    gap_bottom = (below - row.band.y1) / 2 if below is not None else ALONE_MARGIN
    # an overlapping neighbour leaves no gap: a negative margin would push the
    # crop INSIDE the row's own words, so zero is the floor
    margin_top = min(ALONE_MARGIN, max(0.0, gap_top))
    margin_bottom = min(ALONE_MARGIN, max(0.0, gap_bottom))
    width, height = size
    left = max(0, int(min(word.x0 for word in row.word_boxes)) - ALONE_MARGIN)
    right = min(width, int(max(word.x1 for word in row.word_boxes)) + ALONE_MARGIN)
    top = max(0, int(min(word.y0 for word in row.word_boxes) - margin_top))
    bottom = min(height, int(max(word.y1 for word in row.word_boxes) + margin_bottom))
    return Rectangle(left, top, right, bottom)


@dataclass(frozen=True)
class _AloneReader:
    """Reading rows one at a time: the page they are cropped from, where the
    crops and readings are kept, and what does the reading."""

    image: Image.Image
    out_dir: Path
    stem: str
    call: Callable[..., tuple[str, dict[str, int]]] | None
    ordered: list[Any]

    def text_of(self, row: Any, above: list[tuple[int, str]]) -> str:
        """One row transcribed from a crop of its own words only — no
        neighbour's ink, nothing else in the image to confuse it with."""
        path = self.out_dir / f"{self.stem}.row-{row.number}.jpg"
        self.image.crop(alone_crop(row, self.ordered, self.image.size)).save(path, quality=90)
        read_above = "\n".join(f"row {number}: {text}" for number, text in above[-6:])
        prompt = (
            f"This is ONE row of a handwritten letter: row {row.number}, alone. Transcribe exactly what it says, "
            "word for word, keeping any crossing-out as ~~word~~ and any underline as ~word~. If the piece begins or "
            "ends mid-sentence, transcribe just what is here"
            + (f". The rows immediately above it read:\n{read_above}" if read_above else ".")
        )
        options = VlmOptions(system=SYSTEM, user_text=prompt)
        answer, _usage = (
            self.call([path], system=SYSTEM, user_text=prompt)
            if self.call is not None
            else transcribe_images_vlm([path], options=options)
        )
        readings = Transcript.from_answer(answer, rows=[row.number]).readings
        text = readings[0].text if readings else ""
        print(f"  row {row.number}: {text!r}")
        return text


def _combined_answer(rows: list[Any], readings: list[Any], alone: dict[int, str]) -> str:
    """The page's reading: every row, the bands' reading where it settled a row
    and the row-alone reading where it did not."""
    segments = []
    for row in sorted(rows, key=lambda r: r.number):
        text = alone.get(row.number)
        kind = "body"
        after = None
        if text is None:
            for reading in readings:
                if row.number in reading.rows:
                    text, kind, after = reading.text, reading.kind, reading.injection_after
                    break
        entry: dict[str, Any] = {"rows": [row.number], "type": kind, "transcript": text or ""}
        if after is not None:
            entry["injection_after"] = after
        segments.append(entry)
    return json.dumps({"segments": segments})


def _rows_needing_a_second_look(readings: list[Any], numbers: list[int]) -> list[int]:
    """The rows a band reading left blank or doubled.

    A band's image carries its rows' ink plus their neighbours', so a row in a
    tight stack comes back empty (the model read the line once) or doubled (it
    read the same line twice). Those are exactly the rows to show alone."""
    unread = [number for number in numbers if not _text_of(readings, number).strip()]
    seen: dict[str, int] = {}
    doubled: list[int] = []
    for number in numbers:
        text = " ".join(_text_of(readings, number).lower().split())
        if len(text.split()) < 4:
            continue
        if text in seen:
            doubled.append(number)
        seen[text] = number
    return sorted(set(unread) | set(doubled))


def _text_of(readings: list[Any], number: int) -> str:
    for reading in readings:
        if number in reading.rows:
            return str(reading.text)
    return ""


def _endpoint() -> str:
    """The endpoint the calls go to — as the client resolves it, so the report
    cannot describe a different one than was used."""
    return VlmOptions().base_url


@dataclass(frozen=True)
class _Bands:
    """The bands of one page, ready to read: their renders on disk and what
    reads them."""

    numbered: list[NumberedRows]
    render_paths: list[Path]
    stem: str
    out_dir: Path
    model: str | None
    call: Callable[..., tuple[str, dict[str, int]]] | None

    def read(self) -> _ReadBands:
        """Every band read in its own call, with the running transcript as
        context."""
        transcripts: list[str] = []
        usage_total: dict[str, Any] = {}
        readings: list[Any] = []
        refusals: list[str] = []
        for index in range(len(self.numbered)):
            read = self._one(index, transcripts)
            _absorb(usage_total, read.usage)
            if read.refusal:
                refusals.append(read.refusal)
                continue
            readings.extend(read.readings)
            transcripts.extend(read.context)
        combined = json.dumps(
            {
                "segments": [
                    {
                        "rows": list(reading.rows),
                        "type": reading.kind,
                        "transcript": reading.text,
                        **({"injection_after": reading.injection_after} if reading.injection_after is not None else {}),
                    }
                    for reading in readings
                ]
            }
        )
        return _ReadBands(readings=readings, refusals=refusals, usage=usage_total, answer=combined)

    def _one(self, index: int, so_far: list[str]) -> _BandReading:
        """One band read, parsed, and turned into the context it contributes."""
        strip = self.numbered[index]
        numbers = sorted(strip.numbers.values())
        band_text = _band_prompt(index, len(self.numbered), numbers, so_far)
        options = (
            VlmOptions(system=SYSTEM, user_text=band_text, model=self.model)
            if self.model
            else VlmOptions(system=SYSTEM, user_text=band_text)
        )
        answer, usage = self._call(index, band_text, options)
        try:
            band = Transcript.from_answer(answer, rows=numbers)
        except ReadingError as exc:
            return _BandReading(readings=[], usage=usage, context=[], refusal=f"band {index + 1}: {exc}")
        return _BandReading(
            readings=list(band.readings),
            usage=usage,
            context=[f"row {number}: {band.text_of(number)}" for number in numbers],
            refusal="",
        )

    def _call(self, index: int, band_text: str, options: VlmOptions) -> tuple[str, dict[str, int]]:
        """One band's call, and its answer written beside the run."""
        path = self.render_paths[index]
        if self.call is not None:
            answer, usage = self.call([path], system=SYSTEM, user_text=band_text)
        else:
            answer, usage = transcribe_images_vlm([path], options=options)
        (self.out_dir / f"{self.stem}.band-{index + 1}.answer.json").write_text(
            json.dumps({"answer": answer, "usage": usage}, indent=1)
        )
        return answer, usage


@dataclass(frozen=True)
class _ReadBands:
    """What reading the bands produced: the readings, the refusals that
    happened, the total usage, and the combined answer."""

    readings: list[Any]
    refusals: list[str]
    usage: dict[str, Any]
    answer: str


@dataclass(frozen=True)
class _BandReading:
    """What one band's call produced: its readings, the usage it cost, the line
    of context it adds for the bands below, or the refusal that stopped it."""

    readings: list[Any]
    usage: dict[str, int]
    context: list[str]
    refusal: str


def _absorb(total: dict[str, Any], usage: dict[str, int]) -> None:
    """Add one call's usage to the run's, reasoning text included."""
    for key, value in usage.items():
        if isinstance(value, int):
            total[key] = total.get(key, 0) + value
    total["reasoning"] = str(total.get("reasoning", "")) + str(usage.get("reasoning", ""))


def _band_prompt(index: int, of: int, numbers: list[int], so_far: list[str]) -> str:
    """What each band is told: exactly which rows it carries, and the reading of
    the bands above it for the thread of the letter."""
    carried = ", ".join(f"row {number}" for number in numbers)
    above = "\n".join(so_far)
    prompt = (
        f"This image is band {index + 1} of {of} of one page, and it carries exactly {carried} — no others. "
        "Return a reading for each of those rows and nothing else. Each chip carries the colour of the line it "
        "belongs to and that line is tinted the same colour: if it is not clear which line a number goes with, "
        "follow the colour"
    )
    return prompt + (f". The writing above it, already read, is:\n{above}" if above else ".")


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
    alone: list[int] = []
    if "--alone" in args:
        index = args.index("--alone")
        alone = [int(n) for n in args[index + 1].split(",")]
        del args[index : index + 2]
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
        if alone:
            print(f"reading rows {alone} one at a time, each from its own crop")
            read_rows_alone(page, numbers=alone, fixture=fixture)
            continue
        report = run(page, fixture=fixture)
        print(json.dumps(report, indent=1))
        if "refused" in report:
            print(f"REFUSED: {report['refused']}")
            code = 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())
