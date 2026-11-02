# Page categories and document types

Status: **PROPOSED** (user's rulings 2026-11-02). The categorisation is a
pipeline stage (`document/stages.py`: `classify`, artefact `classify.json`);
this note fixes what it names and what each name implies for reading.

## Two vocabularies

- **Page category** — what one scan is. The classifier's answer, per page.
- **Document type** — what a group of pages is: `letter`, `postcard`, `form`,
  `record`… The grouping's answer, derived from the categories of the pages it
  joined. A *postcard* is a `photograph` page plus a `postcard_face` page; a
  letter is `writing` pages; a form is `form` pages.

The category is not a status: a page's status stays its stage progress
(`new → classified → oriented → words → rows_draft → rows_pending →
rows_adjusted → transcripts_proposed`).

## The page categories

| category | what it is | reading route |
|---|---|---|
| `photograph` | a picture — snapshot, the picture side of a postcard | none; the image is the evidence |
| `printed` | printing is writing too: type, print or typescript — a letter, a page of print, a list | one direct VLM transcription, line for line |
| `handwriting` | writing in pen or pencil, however neat | the row pipeline: auto rows → the human row check → the transcription review |
| `postcard_face` | a postcard's written side: message and address, usually in **two different orientations**; `medium` is `printed` or `handwritten` | printed faces take the direct read; handwritten ones the row pipeline (auto rows first; when the auto detection is bad the reviewer draws the rows directly). The two regions are transcribed as two blocks, each named with its orientation |
| `form` | a page shape: printed fields and filled values (a medal card, a statement); `medium` says whether the filling is printed or handwritten | one structured read: labels and their values, not prose |
| `drawing` | an illustration or sketch (no maps for now) | none; captions/labels only if the page carries them |

`map` is deliberately not a category yet (user, 2026-11-02).

The medium is carried by the two page SHAPES (`postcard_face`, `form`), which
may be printed or handwritten; `printed` and `handwriting` are categories in
their own right, so the medium is implied by the name (user, 2026-11-02:
"printing is also writing").

## What the read keeps

The document's transcription is **markdown and keeps every structure the page
has, within reason** — markdown carries horizontal text only, so an
orientation is named in a heading rather than drawn:

```markdown
## Message (rotated 90°)

Dear Mum, …

## Address (upright)

Mrs A. Fawcett
76 Victoria Avenue
Hull
```

A form is a markdown table (label | value), the shape the medal card already
uses. A printed page keeps its printed lines one per line. A photograph has no
text.

## What this changes in the pipeline (built 2026-11-02)

1. The classifier's answer is the six categories above; `medium` applies to
   `postcard_face` and `form` (`pipeline/classify.py`, `PageClassification`).
2. The read stage is a route table keyed on the page category — none / direct /
   rows / structured (`read_route`): `process` sends printed pages to
   `printed_pages`, forms to `structured_pages`, handwriting and handwritten
   postcard faces down the row chain, and photographs/drawings nowhere.
   `pipeline/ocr.py` (the tesseract arbiter and the density route) and the
   guess stage are gone; orientation is the vision model's own call
   (`pipeline/orient.py`), and a page's text is its read's text.
3. A postcard face's two orientations want per-region detection or the human's
   own lines; the reviewer's drawn lines already express "these words are one
   row", so the human path needs no new machinery. Not built yet.
4. Document types are derived by the grouping scorer
   (`pipeline/grouping.py`): the model judges boundaries over the pages'
   readings (it never re-reads text), and the scorer weighs that against the
   physical evidence — duplex sides, paper size, page numbers. The category of
   each page feeds it (a photo page joins its document).

## Open

- How good the structured form read is (labels vs fills, tables, ticks) — a
  small trial on the medal card, whose transcription is already a table.
- Whether a postcard face's regions are detected per orientation automatically
  or the reviewer always draws the lines first (the user's "skip the auto
  detection if it's particularly bad").
