# Design Decisions

The register of the review surface's design decisions with their rationale
(user, 2026-08-16: "let's make sure we're recording all our design decisions
with rationale"). The detailed records — the problems, the walks, the
evidence — live in `docs/PLAN/ux-fixes-plan.md`; this register is the
one-line memory: the decision, why, and where. The standards that govern the
UX process (and the reviewer rules) live in omp-config (`skill://ux-process`,
docs/ux-standards.md).

| Date | Decision | Rationale | Detail |
|---|---|---|---|
| 2026-08-16 | The page image is a plain `<img>` in a transform-scaled layer, not OpenSeadragon | The OSD 6.1.0 build's tile pipeline never rendered in the verification browsers; the surface uses a fraction of it (one jpeg, pinned boxes, pan/zoom); a plain `<img>` paints anywhere and is verifiable by screenshot/pixel-read | TECHSPEC §16.16; ux-fixes-plan |
| 2026-08-16 | One top bar carries everything: back, title, document chips, page chips | The count was drawn three ways (chip, badge, dots); the document boundary was invisible until the last page; visible sequences replace words | ux-fixes-plan "Navigation reorg" |
| 2026-08-16 | Boxless transcription lines take the unmatched detector lines by reading order, marked `box_source: "positional"`, rendered dashed | 101 of 323 lines (31%) had no boxes — the rec model cannot read cursive, so content matching fails; a positional anchor is real geometry, approximate alignment, and the dashed style says so | tools/layout.py; ux-fixes-plan |
| 2026-08-16 | The ↻ press is a pipeline correction: local view first, a queued DESIRED-rotation intent (no image upload), idempotent backend delta, async re-transcription with a grey-out note | The arbiter cannot read cursive, so an upside-down page passes review AND its transcription is unreliable (proven: four wrong words on page-02); the front/back end are different boxes and the backend may be off; multiple presses must coalesce (no reprocess on the first press) | TECHSPEC §16.16; ux-fixes-plan "Orientation fix" |
| 2026-08-16 | The reviewer's ↻ is the only thing that reorients. Local display updates instantly + persists (authoritative — never reverts); the reorientation is delivered reliably to the backend, which reorients + re-OCRs + returns the updated transcription; a late backend catch-up changes OCR, never the display. No stored intent is ever replayed or auto-delivered | A field test showed a stale queued intent re-orienting a page the reviewer never touched and marking its re-read failed; the local view must be authoritative and only the reviewer's press may reorient | PRD VR10 + acceptance 11-14; ux-fixes-plan "Orientation fix" |
| 2026-08-16 | The review proceeds page by page in any order: each page is confirmed on its own (a document is done when all pages are confirmed), the reviewer skips/returns freely, a fast reader confirms without checking any line, and fully confirmed documents leave the pending pile | The flag-tour navigation proved unreliable (it jumped backward to a finished page) and the confidence signal can't drive an ordered tour; the reviewer's real need is to move freely and track what's done (VR3, VR9). | PRD VR11-13 + acceptance 15-19; extra navigation held back until the reviewer has tried the basics |
| 2026-08-16 | Selecting a transcription line highlights only — never zooms | The zoom-on-select was dislocating (user: "it's dislocating"); the dual-pane link brings the region into view at the same zoom | review.js |
| 2026-08-16 | The transcription scroll and the image pan are linked — roughly the same text shows in both panes | The reviewer reads the words against the picture; the line boxes map the two (user: "they stay matched up") | review.js |
| 2026-08-16 | A flagged line can be marked "✓ Fine" without editing (the verbatim text counts as verified) | A line can be correct even with the model's red squiggles on it | review.js |
| 2026-08-16 | The zoom buttons (Fit/−/+) are gone; fingers pinch | The buttons got in the way; the pinch works | review.js |
| 2026-08-16 | Formatting in the transcription: `~~struck~~` (crossed out in the letter) and `~underlined~` (underlined in the letter); a floating edit menu appears only when text is selected (Cut · Copy · Paste · Delete · Select all · strike · underline), positioned above the selection | The letter's emphasis is evidence and must survive into the archive; the mobile keyboard leaves almost no screen, so the controls are contextual (the platform edit-menu pattern), never a permanent toolbar | review.js; app/markdown.js |
| 2026-08-16 | One click on a transcription line enters EDIT mode; a click away (another line, the panes, a navigation) ACCEPTS; Escape discards | Select-then-edit was two steps for the most common action; a separate save button is redundant when every exit accepts (user: "one click to put a line in editing mode... I click away and it accepts") | review.js |
| 2026-08-16 | `make serve` always auto-reloads the backend (watchfiles; watch roots = `tools/` + `tests/`) | Backend changes should apply without a manual restart; uvicorn's reload-exclude patterns can't match mid-path dirs, so narrowed watch roots are the honest fix | Makefile; tools/cli.py |
| 2026-08-16 | A UX reviewer interacts ONLY as the persona could, and never corrects without visible evidence; the evidence channel is part of every finding | The structure channel demonstrably overrides correct pixels in agent beliefs (Perception-Fusion Gap, arXiv:2607.04334); a walker "fixed" transcription errors while the document was not visible and narrated a reading it never performed | omp-config: ux-process SKILL.md, ux-standards P16/P17 |
| 2026-09-18 | The word-detector's cut decisions live as `Writing` methods; the shared word measurement is the `WordShape` record; `split_shapes(shapes, lines, unit)` remains only as the test seam | (marks, lines, unit) threaded through every cut function because they ARE the writing's own fields — a mark cannot know its own word boundaries ("is this strip a word / one line / continued below" is answered by the page's rows, ruler and other marks). lucidlint's "split out a class" suggestion for the clump was a vocabulary mistake the existing noun already answered (filed: ashbywinch/lucidlint#22) | geometry-experiments-log 2026-09-17/18; tools/reader.py, tools/mark.py |
| 2026-09-18 | A row of near-empty ink cuts: a gap is a word boundary when its row's longest run is ≤ ¼ of both flanks (substantial flanks) and the two sides sit on different fitted lines. Strict: a tie at exactly ¼ is a letter's internal gap, not a cut | "of"/"hess" (box 47) and the two crossed-out rows (box 37) are separated by such rows (0.22, 0.03); letters' internal dips are shallower or same-line — the single "A" letter's internal gap ties at 0.25 and must not cut | geometry-experiments-log; tools/reader.py `_gap_row` |
| 2026-09-18 | A gap cut's pieces must still be tall enough and joined-up; the width and flatness bars are waived for gap cuts (named `waive_width`/`waive_band` on `is_word_shaped`) | the gap, not shape, is the separation evidence: "of" is a real word thinner than the width bar and a crossed-out row is flatter than the aspect bar; but a gap cannot make an 8px sliver or two stray ascenders into a word (the y3456 "two ascenders" refusal) | mark.py `is_word_shaped`; tools/reader.py `_gap_pieces_are_words` |
| 2026-09-18 | `WORD_MIN_WIDTH` stays 0.8 × x-height — not reduced | admitting "of" (w20px) also admits word-chunks of 16–36px: 25 real-pipeline words split (incl. user-ruled one-word 5555 and a single "A"); the reduction does not even fix box 47 (its gap boundary is never proposed by the fit) — cost shown at `evidence/all-25-split-v2.jpg` | geometry-experiments-log; tests/test_reader.py (`test_one_word_is_never_split`) |
| 2026-09-18 | A word split across two components rejoins when the mark whose ink starts exactly at the shape's bottom edge (same fitted line, NOT a word alone) is its continuation — box 334 | the lower word's top (y4538–4544, 4px) continues in mark 342 (x1424–1440, w9 — a fragment, not a word); adjacent full words below are different words (measured: 342 is the page's only such mark) | tools/reader.py `_continuation`; tests/test_reader.py (334 pin) |
| 2026-09-18 | The 2px vertical rule at page x2008 is form ink, stripped before anything else | box 37's "square" was that rule + the two crossed-out rows (the interior was empty — the nested words were their own components all along); the rule is the only column on the page with a 239-row continuous run | tools/reader.py `_strip_vertical_rules` |
| 2026-09-18 | An underline welded under its words is separated by its band rows (≥2 rows each running ≥60% of the mark's width, span ≥70px) and stripped as a line | the y3640 weld (one box containing three words) was boxed as a word because the line-fit never proposed the cut there; a stroke evidences itself in its runs, and a 70px floor keeps word-tails out | mark.py `classify_line` (stroke rule); tools/reader.py `_band_cut` |
| 2026-09-18 | `boxdet.py` / `boxsimple.py` / `boxscale.py` deleted | the dead predecessor of this pipeline ("boxdet's machinery dies" per boxsimple's own thesis); nothing imported them — the standing `duplicate` findings were same-origin debt, not a deliberate parallel | git history; docs/PLAN/vlm-word-segmentation-spike.md |
| 2026-09-18 | User ruling: 9690 (998,3220,1076,3282) is two words — OPEN targeted fix | ruled on the zoomed split render; the current pipeline keeps it one (one fitted line; its inter-word gap scores 0.5 — too shallow for the gap rule); deliberately not a new page-wide rule | tests/test_reader.py; geometry-experiments-log |
| 2026-09-22 | Testimony provenance is gathered, never classified: when a statement's source matters, the flow asks the narrator ("Did she say that to you personally?" / "What did you see that made you think that?") and records the answer verbatim, attributed, as the provenance — an inferred epistemic status (evidenced/first-hand/commentary/guess/hearsay) is never stored | the five-way taxonomy was never ruled on; classification would put the machine's words in the narrator's place and contradict §10 (the archive records what the family says, verbatim) | PRD §19 req 2; TECHSPEC §16.9 |

## The transcription's geometry comes from the VLM that read the page (2026-08-16)

The rec engine (PaddleOCR) cannot read cursive: it merged lines into tall
boxes, sat them below the true ink (page-05's first line had NO box at
all — its ink starts 83px above the topmost box), and the positional
fallback anchored the reading's first line to a stray mid-page fragment.
The band anchor + pan floor then clipped the page's true first line and
the image couldn't scroll up to it.

Decision: the geometry must come from the model that CAN read the page —
the VLM. Its transcription prompt now asks for per-line bounding boxes
(normalized 0-1000) alongside the text; the layout anchors each line with
the VLM's own box (`box_source: "vlm"`, solid — text-anchored), and the
rec association is the fallback for lines the VLM gave no usable box. A
sanity guard drops the model's collapsed bottom-edge boxes (< ⅓ the
median line height — page-05's last four lines came back as a 9px
sliver) so those lines fall back to the association rather than a
useless anchor. Proven on the failing page: all 26 lines boxed in
reading order, the first line at the true top (y2312 vs the ink 2302).

The surface's band-margin (half a top-box height) stays — it covers the
rec-fallback pages whose boxes still sit below the ink.
