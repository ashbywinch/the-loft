# Pipeline stages — the refactor plan

The companion to `docs/prd/pipeline-stages-spec.md` (the requirements).
This is the plan only: the object model agreed first, then the typed
scaffold, the missing surfaces, and the sequencing.

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
and the boxes agree — currently `tools/boxjig.py`) are an ACTION of the
row layer, not a noun: the plan folds them into the row object's
validation (`Rows.validate(traces)`) and renames the file away; a "jig"
is not domain vocabulary and appears nowhere in the model.

## The interjection / marginalia decision

User ruling (2026-09-19): the VLM decides what is an interjection and
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
  batch processor built on `tools/pipeline.py`), not by the web server.
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
- **The API server** (`tools/server.py`) — the front's only window: it
  reads the registry/archive (the portal items, the drafts) and accepts
  the user's writes (row adjustments, transcript confirmations,
  identifications), recording them through the typed seams. User writes
  mark their page/batch for re-processing; the worker picks that up on
  its next pass (e.g. a row adjustment rebuilds that page's rows).
- **The front end** (the app) — reads the portal via the API and POSTs
  the user's decisions via the API; it holds no pipeline state.

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
    S->>R: records adjustment; marks page for re-processing
    W->>R: picks the page up, rebuilds its rows
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
`docs/prd/pipeline-stages-spec.md`; the PRD's scope rule keeps
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
