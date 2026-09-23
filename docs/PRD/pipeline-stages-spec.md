# Pipeline stages — user requirements

User requirements for the stages that an image needs to go through. The developer
requirements the code must meet (the object model, the archive legibility, the
website export) live in `docs/PLAN/pipeline-stages-plan.md`, alongside the
refactor plan.

## UR1. The eight stages to process an image of writing

0. **Orient** - Establish which way up the page is
1. **Marks** — The system detects ink strokes
2. **Words** — The system creates word boxes from the marks
3. **Rows** — The system creates proposed rows from the words
4. **User adjusted rows** — The user is able to fix
   rows the pipeline identified wrongly, as simply and quickly as possible.
   Our hypothesis is that having the user
   draw lines across any (real) rows that were not identified correctly is
   the best way to implement this. Whether any lines are
   necessary is the user's determination — if the rows are already
   correct, no lines are needed. The user must not need to add lines to
   rows that are already correct: an **incomplete set of lines merges
   with the draft rows**, live as the user lifts their finger from
   drawing a line, so the user can see if they've drawn the line incorrectly and can delete
   and redraw it immediately.
   User adjusted rows are of the exact same type as the proposed rows.
5. **Proposed transcripts** — the draft Document: each row with the
   proposed text, as well as metadata about whether each row is a normal row,
   marginalia, or an interjection (text intended to be inserted at a specific point in
   another row).
6. **Agreed transcripts** — the Document after the user's review and any corrections.
7. **Proposed entities** — Person, Relationship, Place, Theme, Org, mentioned in the document.
    These entities may be already existing in the system or new entities that haven't been
   previously documented.
8. **Agreed entities** - Person, Relationship, Place, Theme, Org, with all their
    properties agreed by the user. A user may also identify Stories during this
   process. A Story in turn needs to go through the same process of agreeing entities.

## UR2. One portal — "work that needs doing"

One page in the UI lists every pending human work item, with counts and
routing:

- **Check the rows** — the pages whose rows have not been through the
  user's check, e.g. "3 pages to check"; the user decides whether any
  yellow lines are needed (none are, if the rows are already right).
- **Review the transcripts** — the draft Documents awaiting the gate,
  e.g. "2 documents need review".
- **Identify people/places** — Documents awaiting 
  confirmation of the entities therein, e.g. "2 documents need review"
  (this may include Stories that the logged in user has told).

Each item opens the right surface. Nothing human-looping lives outside
the portal.

## UR3. New scans are picked up automatically

When scans are added, the app notices them itself and runs the
machine stages — orient, marks, words, draft rows — so the pages arrive
at the row-check stage with no manual steps. The draft rows must exist
WITHOUT any drawn lines (the words' own line structure), because whether
lines are needed is the user's determination; the row check then decides
whether adjustments are necessary.
