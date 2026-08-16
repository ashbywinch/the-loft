# Design Decisions

The register of the review surface's design decisions with their rationale
(user, 2026-08-16: "let's make sure we're recording all our design decisions
with rationale"). The detailed records — the problems, the walks, the
evidence — live in `docs/plans/ux-fixes-plan.md`; this register is the
one-line memory: the decision, why, and where. The standards that govern the
UX process (and the reviewer rules) live in omp-config (`skill://ux-process`,
docs/ux-standards.md).

| Date | Decision | Rationale | Detail |
|---|---|---|---|
| 2026-08-16 | The page image is a plain `<img>` in a transform-scaled layer, not OpenSeadragon | The OSD 6.1.0 build's tile pipeline never rendered in the verification browsers; the surface uses a fraction of it (one jpeg, pinned boxes, pan/zoom); a plain `<img>` paints anywhere and is verifiable by screenshot/pixel-read | TECH-SPEC §16.16; ux-fixes-plan |
| 2026-08-16 | One top bar carries everything: back, title, document chips, page chips | The count was drawn three ways (chip, badge, dots); the document boundary was invisible until the last page; visible sequences replace words | ux-fixes-plan "Navigation reorg" |
| 2026-08-16 | Boxless transcription lines take the unmatched detector lines by reading order, marked `box_source: "positional"`, rendered dashed | 101 of 323 lines (31%) had no boxes — the rec model cannot read cursive, so content matching fails; a positional anchor is real geometry, approximate alignment, and the dashed style says so | tools/layout.py; ux-fixes-plan |
| 2026-08-16 | The ↻ press is a pipeline correction: local view first, a queued DESIRED-rotation intent (no image upload), idempotent backend delta, async re-transcription with a grey-out note | The arbiter cannot read cursive, so an upside-down page passes review AND its transcription is unreliable (proven: four wrong words on page-02); the front/back end are different boxes and the backend may be off; multiple presses must coalesce (no reprocess on the first press) | TECH-SPEC §16.16; ux-fixes-plan "Orientation fix" |
| 2026-08-16 | Selecting a transcription line highlights only — never zooms | The zoom-on-select was dislocating (user: "it's dislocating"); the dual-pane link brings the region into view at the same zoom | review.js |
| 2026-08-16 | The transcription scroll and the image pan are linked — roughly the same text shows in both panes | The reviewer reads the words against the picture; the line boxes map the two (user: "they stay matched up") | review.js |
| 2026-08-16 | A flagged line can be marked "✓ Fine" without editing (the verbatim text counts as verified) | A line can be correct even with the model's red squiggles on it | review.js |
| 2026-08-16 | The zoom buttons (Fit/−/+) are gone; fingers pinch | The buttons got in the way; the pinch works | review.js |
| 2026-08-16 | Formatting in the transcription: `~~struck~~` (crossed out in the letter) and `~underlined~` (underlined in the letter); a floating edit menu appears only when text is selected (Cut · Copy · Paste · Delete · Select all · strike · underline), positioned above the selection | The letter's emphasis is evidence and must survive into the archive; the mobile keyboard leaves almost no screen, so the controls are contextual (the platform edit-menu pattern), never a permanent toolbar | review.js; app/markdown.js |
| 2026-08-16 | One click on a transcription line enters EDIT mode; a click away (another line, the panes, a navigation) ACCEPTS; Escape discards | Select-then-edit was two steps for the most common action; a separate save button is redundant when every exit accepts (user: "one click to put a line in editing mode... I click away and it accepts") | review.js |
| 2026-08-16 | `make serve` always auto-reloads the backend (watchfiles; watch roots = `tools/` + `tests/`) | Backend changes should apply without a manual restart; uvicorn's reload-exclude patterns can't match mid-path dirs, so narrowed watch roots are the honest fix | Makefile; tools/cli.py |
| 2026-08-16 | A UX reviewer interacts ONLY as the persona could, and never corrects without visible evidence; the evidence channel is part of every finding | The structure channel demonstrably overrides correct pixels in agent beliefs (Perception-Fusion Gap, arXiv:2607.04334); a walker "fixed" transcription errors while the document was not visible and narrated a reading it never performed | omp-config: ux-process SKILL.md, ux-standards P16/P17 |

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
