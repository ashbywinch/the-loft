# Strip-grouping production plan — the layout stage's measured-geometry path

**Status:** SPIKE-VALIDATED (2026-09-07/08); productionising not yet
started. Spike evidence: `geometry-experiments-log.md` §"The
numbered-strips spike"; live artifacts in /tmp/spike-strips2/
(unpersisted — the ledger records the findings).

## What this is

The layout stage (TECH-SPEC §16.17) currently asks the VLM for
coordinates. The spike proved what TRIG (arXiv:2504.04974) measured:
coordinate generation on text-rich pages is near-hopeless (GPT-4o under
10% IoU) — and on the Music College letter (adopt-20260813-201004
page-01/02) the model fabricated boxes in every mode tried: full-page,
two halves, 100px and 50px drawn grids, drawn-box verification — ~15
gateway calls, every one refused by the gates. The captured thinking
shows why: the model reads the page perfectly, then disowns the image
mid-reasoning ("since I can't see the image") and fabricates uniform
boxes.

The validated replacement: **kraken measures, the VLM reads.**

1. kraken 7 + orli — already the HTR stage's line detector
   (`tools/htr.py`, ~200k pages of training) — measures line-baseline
   fragments: 768 raw on page-01, clustered to 106 strips.
2. The strips are drawn numbered on the page (thin green outlines,
   margin numbers — the writing untouched). ONE VLM call **groups** the
   numbered pieces into segments and transcribes each group verbatim.
3. Each segment's box = the measured ink extent of its group's y-band
   (row projection). The model never generates a coordinate.

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

### 2. The grouping read replaces the coordinate read
`segment_page(grid=True)` → `group_segments(...)`: the system prompt
becomes the grouping prompt (segment definition L3 as negatives + the
numbered-rectangles contract `{"lines": [{"pieces": [...], "text":
...}]}`); every fragment index must appear in exactly one group or be
marked empty (validation, fail-loud). Mode selection stays as today:
small cards keep the single-pass grid read (the Godolphin serves cleanly
on it — no tokens spent regressing a working path, L10); portrait
sheets take strips + grouping. Acceptance: contract tests (deterministic
prompt, piece validation, duplicate/unknown index refusal) + the
integration fixture on a synthetic tall page.

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

### 7. Docs + spec
TECH-SPEC §16.17 rewritten from what landed (the grouping read, the
measured boxes, the findings loop); the ledger's spike entry linked;
AGENTS.md routing row for the plan file added when the work starts.

## Test discipline (every slice)

TDD per `docs/testing-standards.md`: fake-urlopen fakes (never
monkeypatch), injectable seams, no sleeps. `make test` stays the one
gate. The saved spike responses are the integration fixtures — the real
model's behavior pinned without network.

## Open questions (user rulings needed)

- Mode selection (slice 2): grouping for ALL pages, or keep the
  small-card grid path? (Recommended: the aspect threshold as today.)
- Grouping-call budget: 1 call/page — is the fragment count bounded
  (cap the strip count; over-cap → page refuses with the count named)?
- RegionGate vs grouped boxes: bands may overlap in y across columns —
  does the region rule need the typed-page allowance too?

## Definition of done

page-01 AND page-02 of the Music College letter serve through
`make pipeline ARGS="layout adopt-20260813-201004 page-01.jpg page-02.jpg"`
with 0 gate violations — every line's transcription read from its own
measured extent — and render in the review surface. Then the real
re-processing of the First test pile, one page at a time.
