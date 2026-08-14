# Multi-Document Import — Feature PRD (the capture pipeline)

- **Status:** draft — user requirements, 2026-08-13 (the scanning session)
- **Mechanics home:** `docs/TECH-SPEC.md` §16 (implementation details live there, not here)
- **Related:** the artifact-identification flow `docs/prd/IMPORT-PRD.md`; the document-ingest review `docs/prd/INGEST-PRD.md`; the story flow `docs/prd/MEMORIES.md`

## 1. Purpose

Physical piles of documents (envelopes of letters, boxes, photo batches)
become archive items **no matter who scanned them, when, or with what** —
our scanner when it is visible, the user's own scanning when it is not,
and piles that were already scanned long ago. The pipeline must never
depend on the scanner being reachable, and must never endanger the user's
scans: they are the recovery source for everything downstream.

## 2. Requirements

**R1 — The user's scan area is theirs.** The user adds scans to their own
folders, in their own structure, and may rename, move, split, merge, or
remove folders however they see fit. The pipeline never modifies the user's
scan area — nothing is written into it, renamed, moved, or deleted there.
It only reads.

**R2 — Any arrival enters the same pipeline.** Scans produced by our
scanner, scans produced by the user on equipment we cannot see, and
pre-existing piles of scans all become indistinguishable batches downstream.

**R3 — Our records live apart.** Everything we record about the scans —
labels, status, tracking, derived work — lives in a separate area of our
own, beside but never inside the user's scan folders. The user's folders
contain only what the user put there.

**R4 — Reorganising costs us work, never data.** When the user reorganises
their scan area, the pipeline re-attaches to their scans with a bounded
amount of work — automatic where it can be, manual help where it cannot —
and nothing already captured is lost or re-entered. A moved folder keeps
its label and its history.

**R5 — Duplicates are detected, never destroyed.** The pipeline detects
both kinds of duplicate: the same file appearing twice, and the same
physical document scanned again (a re-scan at different settings). It
surfaces them; it never deletes or merges anything automatically.

**R6 — Pile labels ride through.** An envelope or box label the user
enters once stays associated with its pile, survives the pile being
reorganised, and carries into the import so it is not re-entered per item.

**R7 — Capture stages, in trust order.** Each document passes through the
stages the user does the work in: the raw scan; the scan turned the right
way up; the machine's raw OCR attempt; the system's corrected OCR guess;
the user's confirmed transcription. Nothing unconfirmed is treated as the
document's words, and nothing unconfirmed reaches the archive.

**R8 — Knowledge is separate from per-scan data.** The records about
people, places, organisations, items and themes live apart from the
per-scan pipeline stages.

**R9 — The deployable site ships reduced-resolution images.** The public
site never serves the full-resolution scans.

**R10 — Handwriting is transcribed, not guessed at.** The pipeline's
transcription of handwritten (cursive) pages must be reasonably accurate:
the machine's draft is a genuine draft the reviewer corrects, never OCR
garbage the reviewer would have to transcribe from scratch. Printed pages
are transcribed accurately too.

**R11 — Mixed piles are handled by content.** A batch may contain cursive
letters, printed pages, photographs, and drawings. The pipeline must tell
them apart and handle each appropriately: text pages are transcribed, and
a photograph or drawing is treated as an image — never OCR'd as text.

**R12 — Handwriting comes in varied layouts.** Handwriting is not always
plain straight lines: marginal notes, a text box in a corner, two lines
joined with a brace and annotated, a printed form filled in in cursive.
The transcription must not lose content in these layouts — marginal and
boxed text is transcribed in its place, and the printed parts of a
filled-in form are not mistaken for the handwriting (or vice versa).

**R13 — Documents span pages; the grouping comes from the document.** A
letter may run across several pages. The pipeline groups pages into
documents using the document's own structure — the greeting that opens a
letter, the sign-off that closes it — and the reviewer confirms the
grouping along with the text.

**R14 — Two homes: a cheap, always-on browsable front end, and the
capture backend beside the scanner.** The browsable part of the archive
(site, verification, chat) is hosted somewhere cheap and highly available,
so the family can always reach it. The capture backend — scanning,
classifying, transcribing — runs on the machine next to the scanner, so
the scanner's USB connection is direct. The two stay in sync; a failed
sync never loses a confirmed transcription.

## 3. Acceptance criteria

1. Scans from our scanner, from the user's separate scanning, and from an
   already-existing pile all become processed batches, with the user's
   scan area byte-identical before and after.
2. The user renames, moves, splits, or merges a folder; the next run
   re-attaches to the content; a moved pile keeps its label and captured
   history; anything the machine cannot re-attach is flagged for the user
   with the originals intact.
3. Duplicate files (same bytes) are detected at the points scans enter and
   shown rather than auto-handled. Duplicate scans (the same page
   re-captured) are detected once the perceptual-hash work lands — the
   mechanism is a deferred implementation (R5 stands as the requirement).
4. The capture stages (right-way-up, raw OCR, corrected OCR guess,
   confirmed transcription) are visibly distinct; a confirmed
   transcription exists for an item only after the user confirmed it; the
   archive contains no unconfirmed transcription.
5. A label entered once appears in the import prompts without re-entry,
   even after the pile was moved.
6. After any failed or mistaken processing step, the user's scans are
   untouched and the step can be re-run from them.
7. A cursive page's draft is readable: the reviewer corrects individual
   words, not the whole page (R10).
8. In a mixed pile, photographs and drawings are recognized as images and
   never reach a transcription stage; cursive and print are each
   transcribed by their own path (R11).
9. A letter with a marginal note, a corner text box, or a filled-in
   printed form is transcribed without losing the marginal or boxed text
   and without the printed parts masquerading as handwriting (R12).
10. A multi-page letter is grouped into one document from its greeting
    and sign-off, and the reviewer confirms the grouping with the text
    (R13).

## 4. Non-goals

- The identification flow (what the machine proposes about each item —
  to/from, people, places, dates) — `IMPORT-PRD.md`.
- The document-ingest review conversation — `INGEST-PRD.md`.
- The phone-capture path — its output enters through the same seam.
