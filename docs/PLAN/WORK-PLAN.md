# The current work — remaining on the active subset

The living plan for what's left on the current PRD subset: the ingest →
transcription → identity pipeline. The full-PRD plan is `PLAN.md`; the
folder's map is `README.md`. Detailed designs are linked per item.

Every item lands with the repo's test conventions (`make test`). Ordered
by dependency.

## 1. The typed pipeline (design: `pipeline-stages-plan.md`)

| # | Item | State | Acceptance |
|---|---|---|---|
| 1.1 | `tools/stages.py` — the Stage enum (object, artefact, human flag) + the Document and identity artefacts' schemas (`schemas.py` has only the rows-side loaders today) | not started | typed scaffold, no behaviour change |
| 1.2 | `Rows.from_words` — the agreed classmethod name (the code has `Rows.build`) | not started | rename, no behaviour change |
| 1.3 | Scan pickup (UR3): watcher + worker run orient → marks → words → draft rows → `rows_pending` | not started | a dropped scan reaches the check-rows queue with no manual step |
| 1.4 | Drawing UI (stage 4): trace with live merge on finger-lift; strokes save through typed `Traces` (design: `segment-review-stories.md`) | not started | drawing fixes a wrong row; the adjustment persists through the typed seams |
| 1.5 | The portal: three doors + counts (rows to check / documents to review / identities proposed — unfinished memories ride the identities queue, per PRD §9 F10 / INGEST-PRD 2026-09-22) | not started | the home doors show the counts; each opens the right surface |
| 1.6 | Identification review (stage 8): proposed entities from agreed Documents → confirmations into the identity tables | not started (depends on 1.5) | confirmations land in `IDENTITY_TABLES` |
| 1.7 | Design task (DR2): where the non-per-page artefacts (identity tables, captured stories) live in the archive | undecided | a proposal showing each kind's home |
| 1.8 | PaddleOCR remnants (ruling 2026-09-22: zero rec use) — remove the vestigial references: `layout_stage.py`'s stale ".venv-htr" docstring + paddle FLAGS env; `pipeline.py`'s stale comment; the cross-reader agreement fallback in `layout.py` (verify it is dead in the single-pass path, then delete); `test_layout.py`'s `_stub_paddleocr` no-op | not started | no paddleocr reference or stub in the served path or tests |

## 2. The ingest review — the claim model (design: `INGEST-PLAN.md`)

Slices 1–6 (identity → disposition → population → closed; pre-answered
claims; discovery; compound-claim decomposition; closure). **None
landed** — the review chat still runs the disposition-first walk; the
review-chat findings R1–R14 (`ux-fixes-plan.md`) stay open until these
land.

Unfinished memories (PRD §9 F10) enter this same review — the same
queue, the same walk (INGEST-PRD, 2026-09-22 ruling: an unfinished
memory may simply have more to tell; the conversation is the same one
that elicits further memories about the item and the identities that
emerge).

## 3. Layout and measurement seams (records: `strip-grouping-plan.md` postmortem; `geometry-experiments-log.md`; `design-decisions.md`)

| # | Seam | State |
|---|---|---|
| 3.1 | Cursive/rotated-page measurement — the served ink-projection primitive measures upright text only; the Godolphin 90° message is unmeasured; the orli rotated pass hallucinated and was deleted | REOPENED |
| 3.2 | RegionGate vs grouped boxes — bands may overlap in y across columns; whether the typed-page Gate B allowance extends here | undecided |
| 3.3 | Tight-schedule multi-line bands — page-01's tight section measures merged; the grouping model transcribes multi-line segments (L3 violated in the serve; the reviewer sees it; 287 doubt-flags awaiting review) | known limitation |
| 3.4 | Word-cutting remnants (`tests/test_reader.py`): word 9690 (ruled two words; the pipeline keeps one — targeted fix, deliberately not a page-wide rule); the y3640 nested-pair weld ((1164,3640,1386,3688) ⊃ (1314,3646,1348,3680)) — two words still fused | open |

## 4. Rulings (2026-09-22) — directions closed

- **PaddleOCR: zero use.** The rec is not a reader, not a fallback, not a
  check (1.8 removes its remnants; the rec-dependent research priorities
  are ruled out — `ocr-verification-research.md`).
- **Review edits store the transcription.** Edits are the correct text,
  stored as such; they will never feed a model (no retraining or
  calibration loop).
- **Transkribus is not a reference.**

Loose ends that fit neither plan: `SCRAPS.md`.