# Layout requirements — draft for adjudication

Status: DRAFT (2026-08-30). This table is Phase 0 of the layout redesign:
every line carries its source, its status, and the mechanism question it
forces. Nothing here is agreed until the adjudication marks it. After
adjudication the confirmed lines become/amend PRD requirements
(TRANSCRIPTION-REVIEW-PRD) and the TECH-SPEC layout section is rewritten
from them.

## The fidelity ruling (2026-08-30, user — to be written up as a VR)

> The transcription must decompose the page into segments — each a
> coherent piece of writing (a body line, a margin annotation, an
> insertion) — each carrying its own text, its own box, and its own
> orientation, such that the transcription reconstructs into a markdown
> table where every segment sits at its original position and
> orientation. Margin annotations that are insertions get modeled as
> relationships (this segment inserts into that one at this point),
> never merged into the target's text and never flattened into reading
> order — because the writer's structure is meaning. The table is the
> fidelity specification: even if the UI renders differently, anything
> the table loses, the transcription has destroyed.

This sharpens VR7 ("marginal notes... appear in their place") from
*not lost* to *structurally faithful, insertions as relationships*.

## The table

| # | Requirement (the layout must…) | Source | Status | Mechanism question it forces |
|---|---|---|---|---|
| L1 | A proposed transcription is produced for every page, made with prior knowledge of the set of people and places which may appear in the letter, and every segment is boxed — a page reaching review without the proposal and its boxes is a pipeline failure | L1 ruling 2026-08-30 + VR14 | NEW — write as VR (amends VR14's wording) | (design) the context source: the archive's people/places registry |
| L2 | Text in any direction is captured — orientation never drops content | VR15 | documented — CONFIRMED (the fidelity table + the per-segment rulings already imply the capture; the rotation mechanism is design) | — |
| L3 | A segment is the longest run of text on a single line that belongs together — it ends where the writing logically separates: a column, a margin annotation, an insertion, a distinct hand. Each segment carries its own text, box, and orientation. When the pipeline's proposed segmentation is wrong, the reviewer can merge or split segments | segment ruling 2026-08-30 | NEW — write as VR | (design, not requirement) how the pipeline finds segments — the mechanism is the TECH-SPEC's business |
| L4 | An insertion is one or more ordinary segments — text, box, orientation, positioned by the grid like any other segment. The insertion POINT is separate data: a character position within another segment. The inserted text is never merged into the target's text, never flattened into reading order | insertion ruling 2026-08-30 | NEW — write as VR | — |
| L5 | When the writer drew an insertion mark (a caret, a line to the margin), the pipeline PROPOSES the point it indicates; the reviewer confirms or moves it — a proposed point is never treated as validated. With no mark, the point starts unset and the reviewer places it. A proposal never silently alters text | L5 ruling 2026-08-30 | NEW — write as VR | (design) how marks are detected is the TECH-SPEC's business |
| L6 | Margin annotations that are independent notes (not insertions) remain their own segments, at their position, never dropped, never merged | geometry log 2026-08-22 ("the item and its annotation are separate transcript lines"), user-confirmed | PROMOTED — write as VR | — |
| L7 | The transcription is reconstructable into a markdown table where each segment sits at its original position; each segment's orientation is stored as data (markdown cannot render rotated text today — the storage makes it displayable the day a format can, by any renderer) — the table plus the stored orientations are the fidelity specification | L7 ruling 2026-08-30 (amended: store rotation as data) | NEW — write as VR | — |
| L8 | Where a segment is a machine transcription and the machine is really uncertain about a word, that word is marked up visibly. The markup directs the reviewer's attention; it never alters the transcription's content | L8 ruling 2026-08-30 ("useful to have words marked up where it's a machine transcription and the machine is really uncertain") | NEW — write as VR | (design) how the pipeline knows it is uncertain — the multi-reader confidence check is one candidate mechanism, not the requirement |
| L9 | The honesty gates stay strict: a layout the gates refuse is never served, and a refusal means the process is not good enough yet — fix the process, never bypass the gate. The end state the process owes the reviewer: every page served with every segment boxed and the full transcription confirmable (the display needs boxes for confirmation to be possible) | L9 ruling 2026-08-30 + VR14 | NEW — write as VR (sharpens the documented behavior into the development forcing-function) | (design) the gate granularity — segment vs page — chosen for the clearest development signal |
| L10 | The process is cost conscious: tokens are not spent for no reason (what counts as "no reason" — redundant reads, unbounded retries, ignoring already-known results — is design) | L10 ruling 2026-08-30 + VR16 | NEW — write as VR alongside VR16 | (design) what the reads cost under the chosen mechanism, and the batching/caching that respects cost-consciousness |
| L12 | A human transcription always supersedes a machine transcription: once the reviewer has corrected or validated a segment's text, no pipeline re-run, new model, or rescue pass may overwrite it. Machine reads may fill segments the human has not touched | the precedence ruling 2026-08-30 | NEW — write as VR | (design) how re-runs detect and preserve human-validated segments |
| L11 | Each segment's transcription is produced from a reading of that segment's own extent. A reading from elsewhere never supplies, displaces, or relocates a segment or its text | L11 ruling 2026-08-30 (the month's experiments: every failure was the join, not the reading or the detection) | NEW — write as the architecture decision | (design) the per-segment clip read is the current candidate |

## Rulings so far (2026-08-30, in order)

1. **L7** — the fidelity table is a spatial grid (position structural).
2. **L3** — a segment is the longest run of text on a single line that
   belongs together; the reviewer can merge or split. Requirements speak
   the document's language; mechanisms are design.
3. **L4** — insertions are ordinary segments positioned by the grid; the
   insertion POINT is a character position within another segment.
4. **L5** — the pipeline proposes the point from the writer's marks
   (else unset); the reviewer always confirms before validation.
5. **L11** — every segment's transcription comes from a reading of that
   segment's own extent, on every page; reader agreement is confidence,
   reader disagreement is doubt.
6. **L7 amended** — markdown cannot render rotated text: the orientation
   is stored as data per segment, displayable when a format supports it.
7. **L12** — a human transcription always supersedes a machine
   transcription; machine reads fill only untouched segments.
8. **L8** — words marked up where the segment is a machine transcription
   and the machine is really uncertain. The multi-reader confidence
   mechanism is not a requirement — it is one candidate design.

ADJUDICATED 2026-08-30: every line walked and ruled. The table is the
working contract for the TECH-SPEC rewrite.

## Open questions for the conversation (one at a time)

1. **The fidelity table's shape** (L7) — RULED 2026-08-30: **a spatial
   grid.** Rows = the page's vertical bands, columns = horizontal bands;
   each segment occupies the cell where its ink sits; rotated segments
   each segment occupies the cell where its ink sits. AMENDED same day:
   markdown cannot render rotated text — each segment's orientation is
   STORED as data, so any future format (or the app's own renderer) can
   display it. Open follow-up: how the bands are derived.
2. **Segment granularity** (L3) — RULED 2026-08-30: **the longest run
   of text on a single line that belongs together** (ends at a logical
   separation: column, margin annotation, insertion, distinct hand).
   Stated in the document's terms; how the pipeline finds segments is
   implementation. The reviewer can merge or split when the proposal is
   wrong.
3. **Insertion point** (L4/L5) — RULED 2026-08-30: **a character
   position within another segment.** Proposed by the pipeline when the
   writer's mark indicates it, otherwise unset; always reviewer-confirmed
   before validation. The inserted segments are ordinary segments.
4. **The upright typed page** (L11) — RULED 2026-08-30: **every
   segment's transcription comes from a reading of that segment's own
   extent, on every page.** No path remains where text is produced
   elsewhere and attached; reader agreement is confidence, reader
   disagreement is doubt (L8).

## What is and is not a requirement source

The evals assert the CURRENT (matching-era) design's behavior — they are
acceptance data for that design, not sources for the redesign's
requirements. Requirement sources: the PRD's verification requirements
(VR1–VR17), the user's rulings. The multi-reader confidence mechanism
was wrongly drawn from an eval contract into this table and removed on
ruling 2026-08-30 (L8 now requires only the uncertainty markup itself).

## What this session's evidence contributes

- The rec's detection pieces are reliable ink measurements in any
  orientation (eval_columns: 0 boxless on the postcard's rotated panel).
- The VLM reads rotated text correctly but its boxes are unreliable
  slabs (the model trial §4; this week's rescue attempts).
- Every matching-based design failed on the join, not on reading or
  detection. The gates and refusals were honest responses to that join
  failing.

## Experiment 2026-08-30: the vision model draws the boxes (user's proposal)

The question: can the vision model produce the geometry (the user's
proposal), with the coordinates recovered programmatically?

Tested against the postcard's back, glm-4.6v via the gateway:

- **Image output**: not available through chat completions on this
  route — the model narrated drawing the rectangles and returned text.
- **SVG output**: works. 16 rectangles; after rescaling the model's
  imagined frame (998x912) to the real image (1665x1152), 15 aligned
  well with actual writing, 1 sat on blank card.
- **Rotated content**: the upright read misses the rotated message
  entirely (the same blind spot VR15 targets). Pre-rotating the card
  90 degrees and asking again produced 9 rectangles; all landed on real
  writing after the inverse rotation, shapes matching (tall/narrow for
  vertical lines).
- **Granularity**: block-level, not line-level — fine segmentation
  still needs the ink measurement or a finer request.

Consequence for the architecture: the vision model can propose
geometry as SVG (rendered and measured programmatically — the model's
coordinate frame must be rescaled; never trusted directly), and
rotated content requires pre-rotated passes (the §6 rotation, fed to
the model instead of done after it). Combined with the ink measurement
for fine boundaries and per-box clip reads for text, this is the
second candidate mechanism for the per-segment pipeline, alongside
rec-detect clustering. The design conversation picks between them
against the requirements.
