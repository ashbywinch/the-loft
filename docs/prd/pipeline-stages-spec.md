# Pipeline stages — specification

The eight product stages, from the user's side, with the developer
requirements the code must meet. The companion plan (the refactor steps)
lives in `docs/plans/pipeline-stages-plan.md`.

## User requirements

### UR1. The eight stages

1. **Marks** — the detected ink strokes (automatic).
2. **Words** — the word boxes made from marks (automatic).
3. **Rows** — the proposed rows (automatic, from the words and the
   drawn lines).
4. **Rows fixed when wrong** — the requirement is that the user can fix
   rows the pipeline identified wrongly; drawing yellow lines is the
   MECHANISM, not a requirement in itself. Whether any lines are
   necessary is the user's determination — if the rows are already
   correct, no lines are needed. The user must not need to add lines to
   rows that are already correct: an **incomplete set of lines merges
   with the draft rows**, live as the user lifts their finger from
   drawing a line, so a wrong line can be deleted and redrawn
   immediately.
5. **Rows agreed** — the rows as built from the drawn lines (no separate
   agreement step; the same object as 3).
6. **Proposed transcripts** — the draft Document: each row with the
   proposed text. During transcription, **the VLM decides what is an
   interjection and where it injects** (which line it inserts into); the
   decision is shown to the user for agreement, never hidden.
7. **Agreed transcripts** — the Document after the user's review: the
   review gate lets the user correct it, so the agreed Document is most
   likely NOT the draft — it carries the user's edits. The draft may be
   PARTLY user-corrected before the review is finished.
8. **Identified entities** — Person, Relationship, Place, Theme, Org,
   with their mentions linked into the agreed Documents.

### UR2. One portal — "work that needs doing"

One page in the UI lists every pending human item, with counts and
routing:

- **Check the rows** — the pages whose rows have not been through the
  user's check, e.g. "3 pages to check"; the user decides whether any
  yellow lines are needed (none are, if the rows are already right).
- **Review the transcripts** — the draft Documents awaiting the gate,
  e.g. "2 documents need review".
- **Identify people/places** — the proposed entities awaiting
  confirmation, e.g. "4 people, 1 place proposed".

Each item opens the right surface. Nothing human-looping lives outside
the portal.

### UR3. New scans are picked up automatically

When scans are added, the backend notices them itself and runs the
machine stages — orient, marks, words, draft rows — so the pages arrive
at the row-check stage with no manual steps. The draft rows must exist
WITHOUT any drawn lines (the words' own line structure), because whether
lines are needed is the user's determination; the row check then decides
whether adjustments are necessary.

## Developer requirements

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
  `Rows.from_words(words, user_lines, page_size)` — not a separately
  named algorithm; the drawn-lines invariants are the row object's
  validation action (`Rows.validate(traces)`), and the file currently
  named "boxjig" is renamed away (a "jig" is not domain vocabulary).
### DR2. The archive is legible full stop

Nothing in the archive folder may confuse a reader about how it fits
into the pipeline. The files are arranged **by page first, then by
pipeline phase**; the FINAL agreed artefacts are the most prominent
thing to find, with the intermediate products (proposed rows, draft
Documents) present but less prominent. The artefacts that are not per
page — the identity tables (people, relationships, places, themes,
orgs) and the captured stories/memories — need a consciously chosen
arrangement of their own, decided as part of the plan (see the plan's
design task), so a reader can see where each kind lives and how the
pages' agreed Documents feed it.
### DR3. The website export is understandable

The export for the website (the app's `data/` files) must be traceable
from the pipeline: which agreed artefacts and identity tables feed which
exported file, and how the export is regenerated.