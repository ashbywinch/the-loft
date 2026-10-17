# Pipeline stages — the refactor plan

The companion to `docs/PRD/pipeline-stages-spec.md` (the requirements).
This is the plan only: the object model agreed first, then the typed
scaffold, the missing surfaces, and the sequencing.

**Status:** the rows foundation landed — the
row library (`tools/rows.py`), the per-stage typed schema loaders
(`pipeline/schemas.py`), the fixture (`tests/fixtures/page01-rows-gold/`).
Of the sequencing: step 1's rows-adjacent schemas exist, but the `Stage`
enum (`tools/stages.py`), the Document and identity artefacts' schemas,
and step 2's `Rows.from_words` rename have not landed; steps 3–6 (the
UR3 scan pickup, the stage-4 drawing UI, the portal, the stage-8
identification flow) are unbuilt.

## The layout (agreed 2026-10-08)

The object model names the objects; this names where the code lives.

**Agreed placement, three homes:**

1. **The document model lives in `document/`.** The records themselves —
   `Word`, `Row`, `Trace`, `Mark`, the geometry (`Rectangle`), `Transcript`,
   `RowTranscript` — each owning its invariants, with the typed loaders of
   their wire shapes (`document/schemas.py`) beside them. A developer reads
   the model from the folder's listing alone.
2. **The pipeline functionality lives in `pipeline/`** — particularly as it
   is surfaced to the app. The chain driver, the store, the stage machinery
   (detection, rows, rendering, transcription), the model client, and the
   API the app talks to (`pipeline/server.py`, `pipeline/sync.py`). The
   pipeline is not a `tools/` item.
3. **`tools/` is only for separate small command-line utilities.** The
   TECHSPEC-§12 list: thumbnails, index/archive rebuilds, archive checks,
   export, fake-data generation. Nothing that belongs to the model or the
   chain lives there.

**Folder size rule:** a folder that has grown too big for a human to read its
list of files is split further — the pipeline splits into stage-group
subpackages (`pipeline/detect/`, `pipeline/rows/`, `pipeline/transcribe/`,
`pipeline/model/`, `pipeline/api/`, `pipeline/evals/`, and the chain driver +
store at the `pipeline/` top), and its evals live under `pipeline/evals/`
because evaluation is the chain's, not the tools drawer's.

### The move (mechanical, seams unchanged)

| today | goes to |
|---|---|
| `tools/row.py` `tools/word.py` `tools/rectangle.py` `tools/trace.py` `tools/schemas.py` | `document/` — the model and its typed loaders |
| `tools/pipeline.py` `tools/pipeline_store.py` `tools/registry.py` | `pipeline/` — the chain, its store, its registry |
| `tools/reader.py` `tools/mark.py` `tools/ink.py` `tools/line.py` `tools/ruler.py` | `pipeline/detect/` |
| `tools/rows.py` `tools/render.py` `tools/boxjig.py` `tools/page_visuals.py` | `pipeline/rows/` (boxjig folds into the traces validation as planned) |
| `tools/transcripts.py` | `pipeline/transcribe/` |
| `tools/vlm.py` `tools/vlm_cache.py` `tools/ai_client.py` | `pipeline/model/` |
| `tools/ocr.py` `tools/classify.py` `tools/grouping.py` `tools/htr.py` `tools/layout*.py` | `pipeline/` — the per-stage model steps |
| `tools/server.py` `tools/sync.py` `tools/auth.py` | `pipeline/api/` — the app's window |
| `tools/eval_*.py` (the chain's) | `pipeline/evals/` |

`tools/` keeps only the small CLI utilities (archive stores, projection,
`atomic`, `attestation`, `gates`, `loft_paths`, `pii_markers`, the
memory/capture flow, the export and demo-data generators, `cli.py`).

`app/`, `tests/`, `research/`, `docs/`, `scripts/` are unchanged in kind;
`tests/` mirrors the packages (`tests/document/`, `tests/pipeline/`).

## The object model (agreed 2026-09-19)

Six objects cover the eight stages; the rest are states of the same
object:

| # | Stage | Object | State / note |
|---|---|---|---|
| 1 | Marks | **Mark** — a connected ink stroke with baseline/waistline | in-memory only |
| 2 | Words | **Word** — a box with measures, from marks | `words.json` (`Words`) |
| 3 | Rows (proposed) | **Row** — words on one line, with a band | `Rows.from_words(words, row_adjustments, page_size)` — a classmethod on the object, not a separately named algorithm |
| 4 | Drawn input | **Trace** — one drawn row indication; the drawing IS the agreement | `strokes.json` / `user-row-adjustments.json`; an INCOMPLETE set merges with the draft rows, live on finger-lift |
| 5 | Rows agreed | **Row** (the same object) | built from the traces; no separate step |
| 6 | Proposed transcripts | **Document** — the transcript as line-based text with its boxes | draft state: the draft Document artifact — one schema for the Document, draft is a state, not a second type |
| 7 | Agreed transcripts | **Document** (the same object) | agreed state: `ocr-confirmed/<doc>.txt` + the registry record |
| 8 | Identities | **Person, Relationship, Place, Theme, Org** + mention-links | `IDENTITY_TABLES` in `tools/archive.py` |

Actors (reader, pipeline, server, page_visuals) are tools over these
objects. The drawn-lines invariants (the A1–A7 checks that the traces
and the boxes agree — currently `pipeline/boxjig.py`) are an ACTION of the
row layer, not a noun: the plan folds them into the row object's
validation (`Rows.validate(traces)`) and renames the file away; a "jig"
is not domain vocabulary and appears nowhere in the model.

## The interjection / marginalia decision

User ruling: the VLM decides what is an interjection and
where it injects, at the transcription phase (stage 6). The code today
does not record the decision: segments carry {label, text, orientation,
box} and the draft Document's lines {index, text, box, conf, box_source, words} —
no kind, no target. The plan:

1. The segmentation prompt asks the model to mark interjection lines and
   their injection target.
2. The Document schema carries `kind` (body / interjection / marginalia)
   and `injection_target` (a line index).
3. The transcript-review surface renders the interjection at its target
   so the same gate agrees it.

## The human-input surfaces

1. **Draw the lines (stage 4)** — new UI surface: drawing on the page
   with live merge: lifting the finger merges the new line into the
   draft rows; a wrong line is deleted and redrawn. The strokes save
   through the typed `Traces`.
2. **Review the transcripts (6→7)** — the existing `#/review` gate,
   extended to show the interjections at their injection points.
3. **Identify people/places (stage 8)** — build the scan-driven
   identification review (per IMPORT-PRD): the proposed entities from
   each agreed Document enter the review chat ("4 people, 1 place
   proposed"), and their confirmations land in the identity tables.

## The portal — "work that needs doing"

One list on the home screen (the review hub) enumerates every pending
human item with counts, and each opens the right surface:

| Portal item | Count shown | Opens |
|---|---|---|
| Check the rows | "3 pages to check" (the user decides whether lines are needed) | the draw surface (1) |
| Review the transcripts | "2 documents need review" | the review gate (2) |
| Identify people/places | "4 people, 1 place proposed" | the identification review (3) |

`home.js` currently shows one promo door with "N documents + N imports +
N drafts to review" (the review hub's own batches, imports and drafts).
That promo extends to three doors — one per portal item above — each
with its own count: the rows-to-check count comes from the pages whose
rows have not been through the user's check; the review count already
exists; the identification count comes from the proposed-entity queue.

## Design task — the non-per-page artefacts

Part of the plan, before step 4: decide the archive arrangement for the
artefacts that are not per page — the identity tables (people,
relationships, places, themes, orgs) and the captured stories — per DR2
(the archive legible full stop; final artefacts most prominent, the
intermediate products less so). The proposal is a step of the plan, not
decided here: it must show where each kind lives and how the pages'
agreed Documents feed it.
## The scan pickup (UR3)

Requirement (UR3): scans added to the batch are noticed by the backend,
the machine stages run, and the pages land in the row-check queue — no
manual steps.

**"Enqueue the batch", concretely:** the batch registry's record IS the
queue. Each page in the batch carries a stage status, and the transitions
are the pipeline:

`new` (watcher adds the page) → `oriented` → `marks` → `words` →
`rows_draft` (the draft rows, built from the words alone — no
adjustments needed) → **`rows_pending`** — the page is now in the
portal's "Check the rows" queue.

- The machine stages are run by the WORKER (a separate process — the
  batch processor built on `pipeline/chain.py`), not by the web server.
- The worker advances each page through the stages, writing each stage's
  artifact through its typed schema (atomic write-then-rename per the
  atomic-write rule), and stops at `rows_pending` — nothing human-looping
  runs in the worker.
- A page leaves `rows_pending` when the user's row check is recorded
  (adjusted or confirmed); the portal counts `rows_pending` pages in the
  "Check the rows" door.

## Back end and front end: the seams

Two processes, clearly separated:

- **The worker** — the batch processor (stages 1–6 machine steps). It
  never serves HTTP and never reads the user's input directly.
- **The API server** (`pipeline/server.py`) — the front's only window: it
  reads the registry/archive (the portal items, the drafts) and accepts
  the user's writes (row adjustments, transcript confirmations,
  identifications), recording them through the typed seams. The row
  corrections are APPLIED where they land — the server builds and
  persists the corrected rows, and its response IS the apply (the live
  merge cannot wait on anything else). A user write marks its page/batch
  for re-processing, and the worker picks that up on its next pass to
  transform the corrected rows into the draft Document (the
  proposed-transcripts stage — each row's text, kind and injection
  target are read then, per the interjection ruling). The server never
  contacts the worker — only the worker proceeds on its own next pass.
- **The front end** (the app) — reads the portal via the API and POSTs
  the user's decisions via the API; it holds no pipeline state.

**The read stage transcribes the rows** (2026-10-07). `pipeline/chain.py`'s
`_read_pages` used to fill each row's text from the page guess's `.txt`, split
into lines and indexed onto the rows in order — which put a sentence one row out
wherever the rows and the text's lines ran differently. The rows' text now comes
from `pipeline/transcribe/transcripts.py` (`Transcriber.transcribe`): the page's rows are
numbered (one chip per row, at the end of the line it belongs to, in that row's
own colour over its tinted band), the page goes to the model as short bands that
each carry exactly their own rows, and any row the bands leave blank or doubled
is transcribed from a MASKED crop — the row's own words, everything else painted
over in the paper's colour, so a neighbour's writing cannot be read as this
row's. The guess stage keeps its role (the page's running text, the document
boundaries); it is no longer the rows' text source. A page whose transcription
returns nothing writes no `rows.json` at all: the marker rule, an artifact that
looks done but is empty being worse than a page to re-run.

Vocabulary, because two things are easy to confuse here: the DETECTOR reads a
page — `pipeline/detect/reader.py`'s `Reading` is the fitted lines and split words that
`words.json` holds. A TRANSCRIPT is what a model says the writing says: one
page's `Transcript` (`document/transcript.py`), each of its rows a
`RowTranscript` (the rows it covers, its text, its kind, its injection target).

**The bands are sized by height, and the height is measured** (2026-10-07).
`NumberedRows.render_strips` used to cut every page into a fixed three bands; the
count now comes from the writing's own height and the tallest band the model
reads at full resolution (`MAX_BAND_HEIGHT` = 856px) — the fewest bands that
leave none taller than that, with a cut only where the rows leave a gap. The
measurement (`pipeline/eval_band_size.py`, one production call per band) found two
separate effects: the whole writing on one image (2360px) lost the **bottom
eight** row numbers — resolution, which is what bands are for — while a band's
call can also come back **empty** at any size (the same 1286px bands read 41/41
twice and named nothing once). Height is not the cure for the second; the masked
alone path is, and it is already the repair.

```mermaid
sequenceDiagram
    participant W as Worker
    participant R as Registry/Archive
    participant S as API server
    participant F as App (the portal)
    participant U as User
    W->>R: detects new scans, registers pages (status: new)
    W->>W: runs stages: orient → marks → words → draft rows
    W->>R: writes artifacts, sets status rows_pending
    F->>S: GET /portal (pending items + counts)
    S->>R: reads page statuses
    S-->>F: "3 pages to check", "2 documents to review", ...
    U->>F: draws adjustments / confirms rows
    F->>S: POST row adjustment (a page)
    S->>S: applies it: builds and persists the corrected rows (the response)
    S->>R: records adjustment; marks page for re-processing
    W->>R: picks the page up on its next pass; transcribes the corrected rows into the draft Document
    U->>F: reviews the transcript (stage 6→7)
    F->>S: POST confirmation (with the user's edits)
    S->>R: records the agreed Document
    W->>R: picks up, writes the agreed Document artifact
```

## Sequencing

1. `tools/stages.py` — the stage enum (object, artefact, human flag) +
   the schemas extended to the Document and identity artefacts (one
   schema per artefact) + the pipeline statuses aligned to the
   vocabulary. No behaviour change — the typed scaffold.
2. `Rows.from_words` naming (the classmethod on the object) — a rename,
   no behaviour change; the no-adjustments draft path (the words' line
   structure) is part of this.
3. The scan pickup (UR3): the watcher + the machine stages onto the
   check-rows queue.
4. Stage 4 drawing UI with live merge (the mechanism by which the user
   fixes wrong rows; the adjustments are already typed).
5. The portal (hub extension + home's three doors).
6. Stage 8 identification flow (depends on the portal routing).


Each step lands with the repo's test conventions; nothing changes
behaviour before its typed boundary exists.
## Developer requirements

The code must meet these (the user-facing half lives in
`docs/PRD/pipeline-stages-spec.md`; the PRD's scope rule keeps
technology out of that folder).

### DR1. The pipeline is findable and understandable from the code alone

A developer opening the repo without context must be able to name the
stages, their objects, and their artefacts:

- One stage vocabulary in code (`tools/stages.py`) naming the eight
  stages, each with its object, its artefact, and whether it needs human
  input.
- The object model is authoritative: Mark, Word, Row, Trace, Document,
  Person/Relationship/Place/Theme/Org. The transport types (reader,
  pipeline, server) are actors over these objects, not stage nouns.
- The row-building algorithm is a method on its object:
  `Rows.from_words(words, row_adjustments, page_size)` — not a
  separately named algorithm; the drawn-lines invariants are the row
  object's validation action (`Rows.validate(traces)`), and the file
  currently named "boxjig" is renamed away (a "jig" is not domain
  vocabulary).

### DR2. The archive is legible full stop

Nothing in the archive folder may confuse a reader about how it fits
into the pipeline. The files are arranged **by page first, then by
pipeline phase**; the FINAL agreed artefacts are the most prominent
thing to find, with the intermediate products (proposed rows, draft
Documents) present but less prominent. The artefacts that are not per
page — the identity tables (people, relationships, places, themes,
orgs) and the captured stories/memories — need a consciously chosen
arrangement of their own (the design task above), so a reader can see
where each kind lives and how the pages' agreed Documents feed it.

### DR3. The website export is understandable

The export for the website (the app's `data/` files) must be traceable
from the pipeline: which agreed artefacts and identity tables feed which
exported file, and how the export is regenerated.