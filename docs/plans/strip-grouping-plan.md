# Strip-grouping production plan — the layout stage's measured-geometry path

**Status:** SPIKE-VALIDATED (2026-09-07/08); productionising not yet
started. Spike evidence: `geometry-experiments-log.md` §"The
numbered-strips spike"; live artifacts in /tmp/spike-strips2/
(unpersisted — the ledger records the findings).

**The Godolphin correction + resolution (2026-09-08, user):** the
card's substantial message is written at 90° on its left side. The
grid read transcribed it correctly but NORMALIZED it to upright
horizontal boxes — the rotation was never detected or handled. The
coordinate path therefore fails BOTH page types. RESOLVED by dual-
orientation detection: run the line detector at 0° AND on the 90°-
rotated page, inverse-map the second pass's boxes, and merge — the
rotated message's lines detect normally in the rotated frame
(empirically: 17 detections in the message zone CCW vs 8 CW; the
vision check confirms 12 boxes each enclosing one vertical message
line, none missing). The user has approved the typed-letter Surya
boxes (multiline boxes acceptable; grouping can split).
1. The strips are drawn numbered on the page (thin green outlines,
   margin numbers — the writing untouched). ONE VLM call **groups** the
   numbered pieces into segments and transcribes each group verbatim.
2. Each segment's box = the measured ink extent of its group's y-band
   (row projection). The model never generates a coordinate.
3. Detection runs at BOTH orientations (0° for upright text; the page
   re-detected at 90° for vertical writing, boxes inverse-mapped) and
   the two box sets merge — every line of writing is measured in
   whichever frame it reads horizontally.

The spike served the previously-refused seam region with **0 gate
violations** — 30 verbatim lines in reading order on the Music College
letter.

## The law this implements

- **L3/L11** (layout-requirements-draft): segmentation is decided by
  reading; every segment's transcription comes from a reading of its
  own extent.
- The user, 2026-09-07: "We don't know what text is meant to be part of
  the same segment as other text without reading it" — grouping is the
  reading act; geometry is measurement.
- **L9**: the gates keep arbitrating. A page that still fails after the
  findings loop refuses exactly as before.
- No fallback to the paddle path (2026-09-06 ruling). Test data never
  enters the family archive.

## Work slices

### 1. Strip measurement moves into the pipeline
The spike's clustering (kraken baselines → fragments → y/x-overlap
merge → numbered strips) becomes a tested module
(`tools/strip_measure.py` or into `tools/htr.py`): `measure_strips(image)
-> strips`. Cache the raw baselines (kraken is ~32 min/page on this
laptop CPU — see slice 6). Acceptance: on page-01, 768 baselines →
~106 strips, deterministic across runs; unit tests pin the merge rule
and the sliver filter on a synthetic fixture.

### 2. The grouping read replaces the coordinate read — for ALL pages
(ruling revised 2026-09-08: the Godolphin card proves the coordinate
path fails on rotated writing too; there is no working path to
protect). `segment_page(grid=True)` → `group_segments(...)`: the system
prompt becomes the grouping prompt (segment definition L3 as negatives
+ the numbered-rectangles contract `{"lines": [{"pieces": [...],
"text": ...}]}`); every fragment index must appear in exactly one
group or be marked empty (validation, fail-loud). Acceptance: contract
tests (deterministic prompt, piece validation, duplicate/unknown index
refusal) + integration on BOTH fixtures — the typed letter AND the
Godolphin card with its rotated message correctly oriented.

### 2b. Rotation normalization (new — the Godolphin finding)
Per-strip clip reads are rotation-normalized: a tall strip (height >
width) is rotated upright before its read, and the strip's measured
extent stays the box; the segment's `orientation` records 90/270 (L7
storage, VR18's upright display). The grouping contract gains the
segment's reading rotation as a discrete per-group selection. The
Godolphin card is the acceptance fixture: its 90° message must come
back as oriented segments with boxes aligned to the vertical writing.

### 3. Measured boxes from groups
Each group's box = the ink projection of its y-band (pad ±6px), NOT the
union of its listed pieces — tonight the model under-listed a line's
pieces (104 chars on one 50px piece) and the band measurement is immune
to that. Empty-text groups are dropped loudly (the model's own verdict:
no writing). Acceptance: the grouped page-01 layout passes
`validate_layout` with 0 violations — already demonstrated in the spike,
pinned as a test with the saved response.

### 4. The findings loop closes on grouped segments
The gates run on the grouped layout; violations map to findings by text
prefix (built: `_gate_findings`); one bounded verification round re-reads
with the checker's measurements attached. Acceptance: the spike's 3→1
convergence pinned as a test; a second non-converging round refuses
honestly.

### 5. Pipeline wiring + per-page recovery
`make pipeline ARGS="layout <batch> [page...]"` runs the strip path;
completion markers, fail-loud, and per-page recovery unchanged
(§16.14.2). The stored layout shape is unchanged — the review surface
needs nothing new (box_source values "segment"/"verified" already
render).

### 6. Remote kraken (decision + spike)
kraken segmentation is ~32 min/page locally — load-bearing now. Options
researched: Riksarkivet's hosted HTR (free, purpose-built; account
needed), Transkribus layout API (account exists; READ-COOP activation
blocked in August — one support email), GPU-hosted kraken
(Modal/Replicate container of the exact CLI, ~1h setup, cents/page).
Spike Riksarkivet first; fall back to the container. Acceptance: page-01
baselines from a remote run match the local run's strip clustering.

## Test discipline (every slice)

TDD per `docs/testing-standards.md`: fake-urlopen fakes (never
monkeypatch), injectable seams, no sleeps. `make test` stays the one
gate. The saved spike responses are the integration fixtures — the real
model's behavior pinned without network.

## Open questions — status after the 2026-09-08 walk-through

- Mode selection: RESOLVED — grouping for ALL pages (ruling revised;
  the Godolphin card disproved the threshold's assumption). Cursive-
  portrait validation is slice 2's acceptance.
- Grouping-call budget: the field's answer to silent omission is
  decomposition (smaller batches), schema-validated full-coverage
  responses, and verification rounds (Liao et al. 2024; TRIG 2025) —
  matching the built design. CONTRACT: batches of ≤50 pieces, every
  piece accounted per batch, ONE re-ask for omissions. RULING (2026-09-08,
  user): pieces still unaccounted after the re-ask are dropped loudly and
  the page SERVES — the loss named in the run log (L10). Deliberately the
  starting posture, not the settled one: "We don't know until we see it.
  Serving them to start with is an easy way to help me see them so I can
  make a judgement" — the served pages make the losses visible, and
  refusal (L9) stays available if what the user sees argues for it.
- RegionGate vs grouped boxes: still open — bands may overlap in y
  across columns; the typed-page Gate B allowance may extend here.
  Decide when the grouping fixture runs against the real gates.

## Definition of done

page-01 AND page-02 of the Music College letter serve through
`make pipeline ARGS="layout adopt-20260813-201004 page-01.jpg page-02.jpg"`
with 0 gate violations — every line's transcription read from its own
measured extent — and render in the review surface. Then the real
re-processing of the First test pile, one page at a time.
