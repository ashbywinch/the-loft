# Transcription Validation — Feature PRD (the review surface)

- **Status:** draft for agreement (2026-08-15)
- **Epic:** 6.11.3 Transcription Validation (Notion)
- **Inputs:** `research/OCR Correction UX & Tools Guide.pdf` (2026-08-15); the capture pipeline's requirements `MULTI-DOC-IMPORT-PRD.md` R7/R10/R12/R13/R14; the sync contract (TECH-SPEC §16.15)
- **Requirements only.** How the screen is built — the viewer, the alignment, the confidence signals, the layout — is the TECH-SPEC's job, and the new tech (bounding-box alignment, per-word confidence) is **spiked before the spec** (2026-08-15) to see what the pipeline can produce. This PRD says what the reviewer experiences, not what the UI is made of.

## 1. Purpose

The family's reviewer corrects and accepts the machine's transcription drafts
in a screen built for that work. The pipeline produces a genuine draft the
reviewer fixes word-by-word — never OCR garbage they would re-type from
scratch (MULTI-DOC-IMPORT-PRD.md R10, acceptance criterion 7). This PRD
defines the review experience on the cheap always-on front end (R14): the
reviewer knows what they're reading, fixes what is wrong without ambiguity,
moves through the work quickly — and never sacrifices accuracy for speed.
Only what they confirm ever reaches the archive (R7).

The reviewer is a family member, not a technologist. The work must be
obvious: what to check, what is doubtful, what happened before.

## 2. Requirements

**VR1 — The reviewer never hunts.** Every word of the proposed
transcription is tied to the place on the page it came from, visibly and
unambiguously. When the reviewer reads a word, they see where it is on the
page; when they look at the page, they know which words it produced.
Finding the right part of the image or of the proposed text is never a
struggle. (What makes this possible — line/region alignment — is a
pipeline capability to be spiked; the requirement is the reviewer's
experience, not the mechanism.)

**VR2 — Fixing is precise and effortless.** The reviewer changes exactly
what is wrong — a word, a line, a passage — and nothing else. There is
never ambiguity about what a correction will change, and what is already
right is never re-typed.

**VR3 — Fast and fluid, never at accuracy's expense.** The review feels
simple and quick; the work flows without friction. But speed is never
bought by making it easier to miss a mistake — a design that lets the
reviewer skim past a wrong word is a failure. The drafts exist to be
corrected; the surface makes correcting the natural, easy act.

**VR4 — What needs checking is visible.** The reviewer can tell where the
machine was unsure without re-reading everything — their attention is
guided to the doubtful places. (The confidence signal is a pipeline
capability to be spiked; the requirement is that the reviewer's effort
goes where it's needed.)

**VR5 — Confirmation is the only gate.** Each document is confirmed,
corrected-then-confirmed, or rejected — nothing else. The confirmed text
is the document's words; a rejection is recorded and nothing is silently
dropped. Only confirmed text reaches the archive (R7; the confirmations
contract, TECH-SPEC §16.15).

**VR6 — The grouping is part of the review.** The reviewer sees which
pages make up each document and confirms the grouping with the text
(R13) — a multi-page letter is one review unit, and a wrong grouping can
be corrected.

**VR7 — Varied layouts survive the review.** Marginal notes, corner text
boxes, and filled-in forms appear in the transcription in their place —
the review never loses the layout content the pipeline transcribed (R12).

**VR8 — The review works from the always-on home.** The surface runs on
the cheap, always-on front end (R14): it reads the machine's drafts and
writes confirmations over the sync seam, and a failed sync never loses a
confirmed transcription. The reviewer's tablet is the primary surface —
**landscape is the natural reviewing posture** (the page and its words
side by side, per the product's tablet-first platform, PRD §1). The same
review works on a phone: the handwriting is big enough to read and the
words are usable on the smaller screen (user, 2026-08-15).

**VR9 — The work is bounded and resumable.** The reviewer can see what
remains in a batch, leave partway, and come back without re-reading what
they already handled. Progress is visible.

**VR10 — Reorientation is immediate and persistent.** When the reviewer
turns a page with the ↻ control, the page is reoriented instantly, and it
stays reoriented every time they look at it thereafter — regardless of
what the back end is doing (a pending, delivered, or failed
re-transcription never reverts or re-flags the reviewer's own correction).
The reviewer's view of a page they fixed is authoritative on their side;
the back end's async re-read is invisible unless it has something to say
(user requirement, 2026-08-16).

## 3. Acceptance criteria

1. A reviewer opening a batch knows at a glance what each document is and
   how many pages it spans.
2. Reading any word of the proposed text, the reviewer can see where it is
   on the page without searching; looking at the page, they know which
   words it produced (VR1).
3. Correcting a word changes that word and nothing else; the confirmed
   text is exactly what the reviewer reviewed (VR2, VR5).
4. The review moves without waiting, hunting, or ambiguity — and the
   reviewer's speed never comes from skipping a check (VR3).
5. The doubtful places in the text are visible without a full re-read
   (VR4).
6. Confirming a document publishes its text; rejecting records the
   rejection; the archive contains nothing unconfirmed (VR5, R7).
7. A three-page letter reviews as one document whose pages the reviewer
   sees and confirms; a wrong grouping can be corrected (VR6, R13).
8. A page with a marginal note or a corner text box shows that content in
   its place, and the reviewer can correct it without losing it (VR7,
   R12).
9. The whole flow works on the always-on home; a failed sync loses nothing
   confirmed (VR8, R14).
10. Leaving a batch and returning resumes where the reviewer stopped,
    with progress visible (VR9).
11. Turning a page reorients it immediately, and it appears that way on
    every subsequent visit, independent of the back end's re-transcription
    state (VR10).
12. When a page's re-read after a correction fails, the surface says so
    plainly ("the re-read failed") — it never implies the text is fine, and
    never blames a correction the reviewer never made (VR10, VR8).

## 4. Non-goals

- Producing the alignment (bounding-box) data or the per-word confidence
  signal — pipeline-side capabilities, to be **spiked** for feasibility
  before the TECH-SPEC; their absence must not block the review
  experience (VR1/VR4 stand as requirements).
- The visual mechanics (viewer layout, highlight interactions, cue
  styling) — the TECH-SPEC + UX wireframe's job, in service of VR1–VR4.
- The import identification review (to/from, people, places, dates) —
  `IMPORT-PRD.md`.
- The ingest review conversation — `INGEST-PRD.md`.
- Correction on the capture backend itself — the reviewer's home is the
  always-on front end (R14).
