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

**VR10 — Reorientation is the reviewer's act, immediate and reliable.**
A page's orientation changes only because the reviewer changed it — never
on its own, even after a reload or a return visit. When the reviewer does
change it: (i) the page shows the corrected way round instantly and stays
that way on every look thereafter, whatever else is happening — what the
reviewer set is what they see, and it never reverts; and (ii) the
corrected transcription reliably arrives, and when it arrives late it
updates the text, never the orientation the reviewer set (user
requirement, 2026-08-16).

**VR11 — The review proceeds page by page, in any order, at the reviewer's
pace.** Each page is finished on its own; a document is finished only when
every one of its pages is finished. The reviewer moves through the pile in
whatever order suits them — leaving a page or a document and coming back
later — and the system never loses their place or confuses their
progress. The reviewer moves at their own speed: nothing in the app ever
slows them down or asks for more than they choose to do (user
requirement, 2026-08-16: power readers blast through without the app
getting in their way).

**VR12 — Fully reviewed work leaves the pending pile.** A document whose
pages are all finished is done: it disappears from the list of work still
to be reviewed (user requirement, 2026-08-16).

**VR13 — Completed work is visibly marked, so nothing is redone.** Lines
and pages the reviewer has already handled stay clearly marked; returning
to the batch shows exactly what remains, so no finished work is re-checked
(user requirement, 2026-08-16).

**VR14 — Every page arrives fully processed by the pipeline.** For every
page, the pipeline identifies the text, produces its bounding boxes, and
provisionally transcribes it. A page that reaches the review without all
three is a pipeline failure — the review never works around it by hand
(user requirement, 2026-08-16).

**VR15 — Text in any direction is captured.** A page whose text runs in
more than one direction — a postcard with a rotated message — still has
every word identified, boxed, and provisionally transcribed: nothing is
missed because of its orientation (user requirement, 2026-08-16).

**VR16 — The app runs lightly on this laptop.** The review app and the
processing pipeline keep their memory use steady no matter how long they
run or how much they process, leave a CPU core free for other work, and
the heavy analysis tools load only while a piece of work is being
processed and free themselves afterwards (user requirement, 2026-08-17).

**VR17 — The reviewer can look at the document in any order and never
lose their place.** Checking the machine's transcription means going
back and forth between the words on the page and the machine's reading
of them. The reviewer needs to look at any part of the document closely,
find the corresponding word in the transcription, and return to where
they were reading without searching. The reviewer never gets stuck in a
correction — they can always keep or abandon a change. The reviewer can
mark a line as verified and change their mind later (user requirement,
2026-08-17, walkthrough finding 2026-08-17).
The reviewer can mark a word as verified and change their mind later
(user requirement, 2026-08-17, walkthrough finding 2026-08-17).

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
11. Turning a page shows it the corrected way round immediately, and it
    stays that way on every subsequent visit, whatever else is happening
    (VR10).
12. The corrected transcription for a reoriented page reliably arrives;
    when it arrives late it updates the text, never the orientation
    (VR10).
13. A page's orientation changes only because the reviewer changed it —
    never on its own, even after a reload or a return visit (VR10).
14. When the corrected transcription can't arrive, the surface says so
    plainly — it never implies the text is fine, and never blames a change
    the reviewer didn't make (VR10, VR8).
15. A fast reader can move through the batch at full speed, with nothing
    in the app making them do extra steps (VR11).
16. Finishing a page moves the reviewer on; a page or document they left
    unfinished is exactly where they left it when they return, in any
    order (VR11, VR9).
17. A document whose pages are all finished is no longer listed as pending
    work (VR12).
18. Lines and pages already handled are visibly marked on return, so none
    are redone (VR13).
19. Leaving and returning restores the exact document and page the
    reviewer was on, with their handled work marked (VR9, VR13).
20. A page whose text runs in several directions shows all of it, with the
    0° lines first, then each next direction in turn; the page initially
    shows the way the pipeline determined is right-way-up — the printed
    writing upright (VR15).
21. A two-sided item such as a postcard is one document — its picture side
    the first page, its text side the second — identified by the pipeline,
    never corrected by hand (VR6, VR14).
22. The review app's memory use stays flat however long it runs and
    whatever it processes — it never grows with use (VR16).
23. While the pipeline processes a batch, the rest of the laptop keeps
    running smoothly: a core stays free, and the heavy analysis tools
    release their memory when their stage is done (VR16).
24. The reviewer can look at a different part of the document without
    losing their place in the transcription (VR17).
25. The reviewer can tell whether a line has been checked and can change
    their mind (VR17, walkthrough finding 2026-08-17).
26. The reviewer can work through the document in whatever order makes
    sense to them (VR17, user 2026-08-17).
27. The reviewer can mark a document complete even when some lines are
    not checked (VR17, user 2026-08-17).
28. The reviewer can move to the next document without confirming the
    current one (VR17, user 2026-08-17).

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
