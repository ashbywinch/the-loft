"""Transcribing a page's rows: the machine's per-row text.

A TRANSCRIPT is one page's texts, each a `RowTranscript` (document/transcript.py); the
DETECTOR's reading (`tools/reader.py`'s `Reading`) is a different thing — the
fitted lines and split words `words.json` holds. This module turns the former out
of the latter.

A page is read by NUMBERING ITS ROWS — one numbered chip per row, drawn at the
end of the line it belongs to and in that row's own colour, over the row's
tinted band — and asking the model for the writing of each numbered row. The
page arrives as short bands (bands reach the model at the page's own
resolution; one tall image does not), each band carrying exactly the rows it
holds. A row the bands leave blank or doubled is then shown ALONE: a crop of
its own words with everything else painted over in the paper's colour, so a
neighbour's writing cannot be read as this row's.

This is the pipeline's read stage (`tools/pipeline.py`'s `_read_pages`) and it
is also its own eval: there is no confirmed transcript for these pages yet, so
the run checks what needs none — the contract holds (every numbered row
appears in exactly one transcript, none missing, none twice), the kinds are
counted, and the transcript is not degenerate (no row without words, plausible
words per row, transcripts distinct — a model repeating one line down the page
is a failure with no gold needed).

The raw answer and the numbered renders are written beside the run, so a
failure is diagnosed from the artifact rather than re-billed.

Usage: PYTHONPATH=. .venv/bin/python -m pipeline.transcribe.transcripts [page...]
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

import numpy as np
from PIL import Image

from document.numbered_rows import NumberedRows
from document.rectangle import Rectangle
from document.schemas import load_user_row_adjustments
from document.transcript import Transcript, TranscriptError
from document.word import Word
from pipeline.detect.reader import reading_for_page
from pipeline.model.vlm import VlmOptions, transcribe_images_vlm
from pipeline.rows.render import render_rows
from pipeline.rows.rows import Rows

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
    "row two transcripts.\n\n"
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


@dataclass(frozen=True)
class Transcriber:
    """One page being read: its rows, where its artifacts go, and what reads it.

    The transcription is ONE pass over this — the bands, the rows they leave, the
    answer, the verdict — so the pass travels as this record rather than as five
    arguments threaded through four functions.
    """

    image_path: Path
    rows: list[Any]
    fixture: Path | None = None
    call: Callable[..., tuple[str, dict[str, int]]] | None = None
    model: str | None = None
    out_dir: Path = OUT_DIR

    def transcribe(self) -> dict[str, Any]:
        """One page, one model call, and every checkable condition measured."""
        image = Image.open(self.image_path)
        size = (image.width, image.height)
        # the rows the reviewer's drawn lines make, when they exist: the reading
        # happens against the CORRECT rows, never the draft the geometry proposed
        # with a fixture directory the reader is shown the CORRECT rows — the words
        # a reviewer's lines were adjudicated against, and those lines applied —
        # rather than the draft the geometry proposed over a live parse
        words = words_from(self.fixture / "words.json") if self.fixture else words_for(self.image_path, image)
        builder = Rows.from_words(words, size)
        rows = (
            builder.adjust(load_user_row_adjustments(self.fixture / "user-row-adjustments.json")["lines"])
            if self.fixture
            else builder.rows()
        )
        if not rows:
            # a page the reader found no writing on: no strips to cut, no call to
            # pay for, and nothing to record — the stage leaves its marker unwritten
            return {
                "page": self.image_path.name,
                "rows": 0,
                "transcripts": {},
                "band_notes": ["no rows on the page"],
            }
        # the strips are cut from the REVIEW SURFACE'S OWN rendering — the rows
        # tinted in their per-row hues by `render_rows` (the same function the
        # review surface and the reading sheet use), then numbered with the same
        # `.rv-rownum` pill. The model sees what the reviewer sees.
        self.out_dir.mkdir(parents=True, exist_ok=True)
        numbered, render_paths = _cut_and_save_strips(image, rows, self.out_dir, self.image_path.stem)

        # the universe is the rows NUMBERED, each once: neighbouring bands overlap,
        # so a row can appear in two of them with its own single number
        drawn = len({number for strip in numbered for number in strip.numbers.values()})

        # ONE BAND PER CALL, each told exactly which rows it carries, and each
        # given what the earlier bands read — the same continuity the pipeline's
        # transcription prompt uses. A call per band also keeps every image at full
        # resolution (one band, not three) and asks for a smaller answer, so no
        # completion is cut off mid-JSON.
        started = time.monotonic()
        band_transcripts = _Bands(
            numbered=numbered,
            render_paths=render_paths,
            stem=self.image_path.stem,
            out_dir=self.out_dir,
            model=self.model,
            call=self.call,
        ).read()
        every = sorted({number for strip in numbered for number in strip.numbers.values()})
        needing = _rows_needing_a_second_look(band_transcripts.transcripts, every)
        alone = self.unsettled(needing)
        answer = self.answer(band_transcripts.transcripts, alone)
        seconds = time.monotonic() - started
        refusals, usage = band_transcripts.refusals, band_transcripts.usage

        report: dict[str, Any] = {
            "page": self.image_path.name,
            # the endpoint and the model the transcript ACTUALLY used, and how long it
            # took: a run that answers in under a second is not reading a page
            "endpoint": _endpoint(),
            "model": self.model or "dynamic/image",
            "seconds": round(seconds, 1),
            "rows": len(rows),
            "words": sum(len(row.word_boxes) for row in rows),
            "strips": len(numbered),
            "usage": usage,
            "renders": [str(path) for path in render_paths],
        }
        # the per-row text, whether or not the WHOLE page passes the contract: the
        # reviewer sees the machine's attempt (stage raw) and corrects it, and a
        # refusal is the eval's verdict on the page — not a reason to serve no
        # transcript at all. The pipeline's read stage reads this; the eval reports the
        # refusal beside it.
        report["transcripts"] = {
            str(number): str(segment.get("transcript", ""))
            for segment in json.loads(answer).get("segments", [])
            for number in segment.get("rows", [])
        }
        # the transcript is written where the page's other artifacts live. It was
        # computed and dropped before this (the reviewer's copy came from a step
        # run by hand), and an assembled transcript nobody can read back is not a
        # transcript the pipeline can serve.
        (self.out_dir / f"{self.image_path.stem}.answer.json").write_text(
            json.dumps({"answer": answer, "usage": usage}, indent=1)
        )
        # the verdict is the COMBINED transcript's: a band's refusal is a working
        # note (those rows were shown alone and may well have been read there)
        try:
            transcript = Transcript.from_answer(answer, rows=drawn)
        except TranscriptError as exc:
            report["refused"] = str(exc)
            report["band_notes"] = refusals
            return report
        report["band_notes"] = refusals

        report.update(_measure(transcript))
        return report

    def unsettled(self, needing: list[int]) -> dict[int, str]:
        """The rows the bands could not settle, read one at a time from masked
        crops — each crop keeps ONLY the row's own words, everything else painted
        over in the paper's colour, so no neighbour's ink can be read as this row's
        (a crop rectangle was not enough: rows 36/37 interleave vertically and no
        rectangle holds one without the other)."""
        if not needing:
            return {}
        print(f"  {len(needing)} row(s) the bands could not settle: {needing} — reading them alone")
        alone: dict[int, str] = {}
        for number, text in transcribe_rows_alone(
            self.image_path, numbers=needing, fixture=self.fixture, call=self.call, out_dir=self.out_dir
        ):
            alone[number] = text
        return alone

    def answer(self, band_transcripts: list[Any], alone: dict[int, str]) -> str:
        """The page's transcript: every row, the bands' text where it settled a row
        and the row-alone text where it did not."""
        segments = []
        for row in sorted(self.rows, key=lambda r: r.number):
            text = alone.get(row.number)
            kind = "body"
            after = None
            if text is None:
                for one in band_transcripts:
                    if row.number in one.rows:
                        text, kind, after = one.text, one.kind, one.injection_after
                        break
            entry: dict[str, Any] = {"rows": [row.number], "type": kind, "transcript": text or ""}
            if after is not None:
                entry["injection_after"] = after
            segments.append(entry)
        return json.dumps({"segments": segments})


def transcribe(
    image_path: Path,
    *,
    fixture: Path | None = None,
    call: Callable[..., tuple[str, dict[str, int]]] | None = None,
    model: str | None = None,
    out_dir: Path = OUT_DIR,
) -> dict[str, Any]:
    """One page transcribed: its rows, its bands, its transcript, its verdict.

    The rows are the reviewer's drawn lines when a fixture carries them, the
    detector's own otherwise — the pass itself is `Transcriber.transcribe`.
    """
    image = Image.open(image_path)
    words = words_from(fixture / "words.json") if fixture else words_for(image_path, image)
    builder = Rows.from_words(words, (image.width, image.height))
    rows = (
        builder.adjust(load_user_row_adjustments(fixture / "user-row-adjustments.json")["lines"])
        if fixture
        else builder.rows()
    )
    return Transcriber(
        image_path=image_path, rows=rows, fixture=fixture, call=call, model=model, out_dir=out_dir
    ).transcribe()


def _cut_and_save_strips(
    image: Image.Image, rows: list[Any], out_dir: Path, stem: str
) -> tuple[list[NumberedRows], list[Path]]:
    """The page's bands, numbered, written beside the run — and their paths, for
    the answer beside them."""
    # the band count comes from the writing's height and the measured
    # readable band height — not from a fixed number of strips
    numbered = NumberedRows.render_strips(render_rows(image, rows), rows)
    paths = []
    for index, strip in enumerate(numbered):
        path = out_dir / f"{stem}.strip-{index + 1}.jpg"
        strip.image.save(path, quality=88)
        paths.append(path)
    return numbered, paths


def row_transcripts(
    image_path: Path,
    out_dir: Path,
    *,
    model: str | None = None,
    call: Callable[..., tuple[str, dict[str, int]]] | None = None,
) -> dict[int, str]:
    """The page's rows read: each row's number and the writing read for it.

    This is what the pipeline's read stage consumes. A page whose transcript
    returns nothing answers with an empty mapping — the caller must leave its
    marker unwritten, not record an empty transcript as done.
    """
    report = transcribe(image_path, model=model, call=call, out_dir=out_dir)
    return {int(number): text for number, text in report.get("transcripts", {}).items()}


def transcribe_rows_alone(
    image_path: Path,
    *,
    numbers: list[int],
    fixture: Path | None = None,
    call: Callable[..., tuple[str, dict[str, int]]] | None = None,
    out_dir: Path = OUT_DIR,
) -> list[tuple[int, str]]:
    """Read named rows ONE AT A TIME, each from a MASKED crop of its own words
    only.

    A row is a piece of writing that the reviewer's lines separated, and in the
    tight stacks its band overlaps its neighbours' — a crop of the band shows
    three rows' ink, so the reader sees the same writing three times. Each crop
    keeps only the row's own words, everything else painted over in the paper's
    colour, and the piece is alone; the running transcript gives it the thread
    of the letter.
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
    # persisted like every other transcript: a row read once is never paid for
    # twice, and the assembly below reads the file rather than re-asking
    (out_dir / f"{stem}.alone.json").write_text(
        json.dumps({"rows": {str(number): text for number, text in read}}, indent=1)
    )
    return read


def masked_row(row: Any, page: Image.Image, ordered: list[Any]) -> Image.Image:
    """The page's region for this row with EVERYTHING but the row's own words
    painted over in the paper's colour.

    The crop rectangle holds the row's words plus a little air; the mask then
    erases whatever else that rectangle contains. A rectangle alone cannot
    isolate a row whose region interleaves a neighbour's (page-01's 36/37, 76px
    of vertical overlap): there is no rectangle holding one without the other.
    Painting the neighbour over leaves only this row's writing to be read, and
    it is exactly what "read this row alone" means."""
    rect = row_crop(row, page.size)
    # PIL's crop wants its own 4-tuple; the record is the Rectangle above it
    region = np.asarray(page.convert("RGB").crop((int(rect.x0), int(rect.y0), int(rect.x1), int(rect.y1)))).copy()
    paper = np.array(NumberedRows.background_of(page, ordered))
    mask = np.zeros((region.shape[0], region.shape[1]), dtype=bool)
    pad = 2  # word boxes hug the ink; a couple of px so the strokes are never shaved
    for word in row.word_boxes:
        x0 = max(0, int(word.x0) - rect.x0 - pad)
        y0 = max(0, int(word.y0) - rect.y0 - pad)
        x1 = min(region.shape[1], int(word.x1) - rect.x0 + pad)
        y1 = min(region.shape[0], int(word.y1) - rect.y0 + pad)
        mask[y0:y1, x0:x1] = True
    region[~mask] = paper
    return Image.fromarray(region.astype("uint8"), "RGB")


def row_crop(row: Any, size: tuple[int, int]) -> Rectangle:
    """The rectangle holding one row's words plus a little air — neighbours may
    be inside it, which the mask removes."""
    width, height = size
    left = max(0, int(min(word.x0 for word in row.word_boxes)) - ALONE_MARGIN)
    right = min(width, int(max(word.x1 for word in row.word_boxes)) + ALONE_MARGIN)
    top = max(0, int(min(word.y0 for word in row.word_boxes)) - ALONE_MARGIN)
    bottom = min(height, int(max(word.y1 for word in row.word_boxes)) + ALONE_MARGIN)
    return Rectangle(left, top, right, bottom)


@dataclass(frozen=True)
class _AloneReader:
    """Reading rows one at a time: the page they are cropped from, where the
    crops and transcripts are kept, and what writes the transcripts."""

    image: Image.Image
    out_dir: Path
    stem: str
    call: Callable[..., tuple[str, dict[str, int]]] | None
    ordered: list[Any]

    def text_of(self, row: Any, above: list[tuple[int, str]]) -> str:
        """One row transcribed from a masked crop of its own words only — no
        neighbour's ink, nothing else in the image to confuse it with."""
        path = self.out_dir / f"{self.stem}.row-{row.number}.jpg"
        masked_row(row, self.image, self.ordered).save(path, quality=90)
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
        row_transcripts = Transcript.from_answer(answer, rows=[row.number]).row_transcripts
        text = row_transcripts[0].text if row_transcripts else ""
        print(f"  row {row.number}: {text!r}")
        return text


def _rows_needing_a_second_look(transcripts: list[Any], numbers: list[int]) -> list[int]:
    """The rows a band reading left blank or doubled.

    A band's image carries its rows' ink plus their neighbours', so a row in a
    tight stack comes back empty (the model read the line once) or doubled (it
    read the same line twice). Those are exactly the rows to show alone."""
    unread = [number for number in numbers if not _text_of(transcripts, number).strip()]
    seen: dict[str, int] = {}
    doubled: list[int] = []
    for number in numbers:
        text = " ".join(_text_of(transcripts, number).lower().split())
        if len(text.split()) < 4:
            continue
        if text in seen:
            doubled.append(number)
        seen[text] = number
    return sorted(set(unread) | set(doubled))


def _text_of(transcripts: list[Any], number: int) -> str:
    for one in transcripts:
        if number in one.rows:
            return str(one.text)
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

    def read(self) -> _BandTranscripts:
        """Every band read in its own call, with the running transcript as
        context."""
        transcripts: list[str] = []
        usage_total: dict[str, Any] = {}
        one: list[Any] = []
        refusals: list[str] = []
        for index in range(len(self.numbered)):
            read = self._one(index, transcripts)
            _absorb(usage_total, read.usage)
            if read.refusal:
                refusals.append(read.refusal)
                continue
            one.extend(read.transcripts)
            transcripts.extend(read.context)
        combined = json.dumps(
            {
                "segments": [
                    {
                        "rows": list(one.rows),
                        "type": one.kind,
                        "transcript": one.text,
                        **({"injection_after": one.injection_after} if one.injection_after is not None else {}),
                    }
                    for one in one
                ]
            }
        )
        return _BandTranscripts(transcripts=one, refusals=refusals, usage=usage_total, answer=combined)

    def _one(self, index: int, so_far: list[str]) -> _BandTranscript:
        """One band read, parsed, and turned into the context it contributes."""
        strip = self.numbered[index]
        numbers = sorted(strip.numbers.values())
        band_text = band_prompt(index, len(self.numbered), numbers, so_far)
        options = (
            VlmOptions(system=SYSTEM, user_text=band_text, model=self.model)
            if self.model
            else VlmOptions(system=SYSTEM, user_text=band_text)
        )
        answer, usage = self._call(index, band_text, options)
        try:
            band = Transcript.from_answer(answer, rows=numbers)
        except TranscriptError as exc:
            return _BandTranscript(transcripts=[], usage=usage, context=[], refusal=f"band {index + 1}: {exc}")
        return _BandTranscript(
            transcripts=list(band.row_transcripts),
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
class _BandTranscripts:
    """What the bands produced: the row transcripts, the refusals that happened,
    the total usage, and the combined answer."""

    transcripts: list[Any]
    refusals: list[str]
    usage: dict[str, Any]
    answer: str


@dataclass(frozen=True)
class _BandTranscript:
    """What one band's call produced: its row transcripts, the usage it cost, the
    line of context it adds for the bands below, or the refusal that stopped it."""

    transcripts: list[Any]
    usage: dict[str, int]
    context: list[str]
    refusal: str


def _absorb(total: dict[str, Any], usage: dict[str, int]) -> None:
    """Add one call's usage to the run's, reasoning text included."""
    for key, value in usage.items():
        if isinstance(value, int):
            total[key] = total.get(key, 0) + value
    total["reasoning"] = str(total.get("reasoning", "")) + str(usage.get("reasoning", ""))


def band_prompt(index: int, of: int, numbers: list[int], so_far: list[str]) -> str:
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
    for one in transcript.row_transcripts:
        kinds[one.kind] = kinds.get(one.kind, 0) + 1
        words_per_row.append(len(re.findall(r"[\w'’~-]+", one.text)))
    return {
        "row_transcripts": len(transcript.row_transcripts),
        "kinds": kinds,
        "injections_point_at_a_row": all(
            one.kind != "injection" or one.injection_after is not None for one in transcript.row_transcripts
        ),
        "words_per_row_median": statistics.median(words_per_row),
        "words_per_row_min": min(words_per_row),
        "distinct_transcripts": len({one.text.strip().lower() for one in transcript.row_transcripts}),
        "longest_transcript": max(len(one.text) for one in transcript.row_transcripts),
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
            transcribe_rows_alone(page, numbers=alone, fixture=fixture)
            continue
        report = transcribe(page, fixture=fixture)
        print(json.dumps(report, indent=1))
        if "refused" in report:
            print(f"REFUSED: {report['refused']}")
            code = 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())
