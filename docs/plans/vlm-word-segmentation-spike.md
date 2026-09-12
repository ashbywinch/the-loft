# Spike: VLM-word-segmentation — numbered word boxes, VLM segments

Status: spike (not committed to as the product path). Started 2026-09-12.

## Why

The per-word measurement work converged on honest per-word baselines and
waistlines (the f, the g, Opera, the row-16 tail — all pinned). But
*segmenting the page* — which words belong to which line/aside/marginal
note — is a reading task. We have a model that can read pages: the VLM. The
spike: **give the VLM a page (or a section) with every detected word boxed
in its own colour and numbered, and let it return JSON — the transcribed
segments with each word assigned to one of them.**

Everything partitions cleanly:

- **Detection stays ours**: the existing reader/model gives every word's
  box + measured geometry (`WordGeometry`) — the VLM never guesses where
  the words are.
- **Reading is the VLM's**: the transcript, the segment boundaries, the
  types.
- **Assignment is the contract**: the VLM returns the word ids it read into
  each segment; we reconcile that every word is assigned exactly once.

## Segment types — the definitions that matter

**`body`** — the running text, one segment per line.

**`injection`** — text meant to be injected INTO other text. The author's
signal: a `^` under a line with text squeezed above it — the injected text
belongs at that point of the main line. An injection therefore CARRIES ITS
INJECTION POINT, and the JSON schema requires it: the point is where the
caret sits, expressed as the word it follows (or precedes).

**`marginalia`** — text with NO injection point: a drawn box with extra
text in it, a random margin note. The JSON schema requires that marginalia
carry no injection point (and the VLM must not invent one).

**`rule`** — an underline/flourish the detector found (the VLM may assign
no transcript to it; it exists so the word ids reconcile).

## The JSON contract (v1)

```json
{
  "segments": [
    { "id": "seg-1", "type": "body", "transcript": "London Opera Centre", "word_ids": [129, 130, 131, 135, 138] },
    { "id": "seg-2", "type": "injection", "transcript": "my dear",
      "injection_point": { "after": 147 }, "word_ids": [152, 153] },
    { "id": "seg-3", "type": "marginalia", "transcript": "Send this first", "word_ids": [160] },
    { "id": "seg-4", "type": "rule", "word_ids": [151] }
  ]
}
```

- `injection_point.after` = the word id the caret follows (for a caret at
  the very start of a line: the line's first word id precedes it — the
  schema only ever requires *after*; `before` is a fallback we re-ask for).
- `injection_point` is REQUIRED for `injection`, FORBIDDEN for everything
  else (the schema validator enforces both ways).
- `word_ids` are the section's rendered ids — the caller renumbers to page
  ids.

- `transcript` carries the page's formatting AS MARKERS, the existing
  convention (2026-08-16, `design-decisions.md`; prompted in `tools/vlm.py`
  and `tools/segment_page.py`; rendered in `app/markdown.js`): a word the
  writer crossed out is `~~word~~` (double tilde — GFM's strike), a word the
  writer underlined is `~word~` (single tilde — the deliberate in-house
  sibling, since markdown has no standard underline; `<u>` is HTML and the
  renderer is text-nodes-only). As close to standard Markdown as the format
  allows; the markers are content, never dropped, never literal in the
  surface.
## Rendering the input — the numbered boxes

New renderer (a pure function): given a section + the words, produce the
image:

- one hue per word, cycling a designed palette (distinct under the VLM's
  vision, and in grayscale too — the model may downscale);
- the number ON the perimeter: a small filled chip at the box's
  top-left corner, so the number is on the box but outside its ink;
- **collision-free**: a chip must never cover another word's box — the
  label is placed at the first free direction (above, below, left, right,
  then further along the perimeter), skipping positions that intersect any
  other box;
- high-resolution sections — small text needs the pixels (the letter's
  small words are ~20px; keep them ≥ 40px after any provider downscale).

## Tiling — maximise complete segments

The VLM cannot guess the tail of a line it cannot see, so tiles should
contain WHOLE segments. Ideas, tried in order:

1. **The whole page.** The simplest complete-segment answer; the question
   is whether any of the page's smallest text survives the provider's
   downscale. Measured first: a tile that is the whole letter may force the
   small words below reading size — if the whole-page attempt reads the
   body fine but fumbles the small writing, that failure pattern tells us
   where the seams should go.
2. **Tile in Y only.** Full-width horizontal strips — lines are horizontal,
   so every body line stays complete. The seam position matters: place
   seams at the widest ink-free horizontal bands (the natural gaps between
   lines), not mid-row. Afterwards, **zoom into the edge zones where small
   or dense words sit** (marginalia, near the seams) and attempt them again
   at higher resolution.
   - **The partial-segment guard**: NEVER use the zoomed attempt's output
     for a segment the zoom cut up — a full body line that overlaps the
     zoomed margin area is PARTIAL in the zoom, and the zoom's guess about
     it is worthless (the VLM saw a fragment). The zoom's assignments apply
     ONLY to the words it fully contains; the partial line's words keep
     the Y-tile's assignment and are reconciled there.
   - The seam decision: a word crossed by a seam is drawn whole in the
     upper tile (or the lower — whichever keeps it readable), never split.

## The gold — what "worked" means

We calculate the correct segmentation OURSELVES from the yellow lines (the
reviewer's traces are the ground truth; the detector never used them, the
spike is judged against them):

- each yellow line defines one segment: its covered words (the existing
  coverage logic: the words its band and x-extent reach);
- segment TYPES from the trace's geometry: a long horizontal trace = body;
  a caret/`^` mark = an injection whose point is at the caret's apex
  (derived from the trace's shape and position); a boxed or free-floating
  note trace = marginalia — refined during the spike against the actual
  traces, and the reviewer adjudicates what the shapes can't tell;
- FORMATTING gold from the same traces: a long flat trace running BELOW a
  word's bodies (under its feet) = the word is underlined (expected
  `~word~`); a trace drawn THROUGH the word's bodies (across the x-height)
  = struck (expected `~~word~~`). The VLM's markers are checked against
  this per covered word — where the author underlined or crossed out, the
  transcript must carry the marker, and the two trace positions are how the
  gold separates underline from strike;
- the spike's output scores: assignment exactness (every word in the same
  segment as the lines say), type correctness, the FORMATTING markers
  (`~…~` / `~~…~~`) against the trace positions, and — for the transcripts
  — the reviewer reads the sample (there is no transcript gold in the
  archive; the VLM's reading is checked on a section-by-section basis).

## Milestones (spike-sized)

1. **The numbered renderer** — whole page + Y-tiles: distinct hue +
   perimeter number per word, collision-free; visuals checked by the user.
2. **The gold extractor** — the yellow lines → segment per trace + type +
   caret injection points, reviewer-adjudicated.
3. **Whole-page attempt** — schema v1 through the VLM; assignment vs the
   gold on the whole letter; transcript sanity on the known examples (the
   "London Opera Centre" group, the f/g/Opera words).
4. **Y-tiling attempt** — seams at the ink-free bands; then the zoomed
   edge attempts with the partial-segment guard; the three strategies
   scored against the gold.
5. **The report** — what worked vs the yellow lines, and whether the path
   outperforms the geometry-only grouping.

## Reconciliation

- A section's segments' `word_ids` must equal the section's rendered ids
  (set equality, minus `rule`s); unassigned or double-assigned words are
  visible failures — re-run the section or hand it to the reviewer, never
  silently merge.
- Across tiles: each word's final segment comes from the tile that fully
  contains it (per the partial-segment guard), then the page maps back.

## Risks / open questions

- **The VLM reads handwriting**: hallucination, dropped words, invented
  words — measured against the gold from milestone 2.
- **Label collision**: dense zones (line 18's) leave few free perimeter
  positions; chips may need to sit outside the section or shrink.
- **Schema adherence**: invalid JSON, wrong ids, an injected-text-without-
  point or marginalia-with-a-point — re-ask boundedly, then flag.
- **The injection point's precision**: the caret may sit BETWEEN words —
  `after` the preceding word needs the VLM to name the right word id; the
  spike measures how often it lands.
- **Cost/latency**: whole page + tiles × the letter — fine for the spike.
- Doesn't touch `tools/page.py`'s grouping yet; a good result would re-open
  it as the evidence the grouping should match.

## Where the outputs live

- The numbered renderer lives in `tools/` (pure, tested — the collision
  logic gets unit tests the moment it draws).
- The VLM calls + the gold extractor live in a spike script (not the
  library) until the contract settles.
## Rulings while starting (2026-09-12) — the definitions that landed

The session that started implementation settled every open mechanic. All
user rulings:

1. **The judgement is attribution.** The correct output: "the model
   correctly attributes every word to the correct segment, as adjudicated
   by the yellow lines". The gold extractor's proposed attribution is
   shown to the user for validation before any VLM call. Segment-outline
   renderings were tried and rejected as the wrong frame — the frame is
   word → segment attribution.
2. **Traces define segments — the numbers match by construction.** The
   render universe is the traced words: the union of the gold segments'
   word ids equals the rendered set by construction; reconciliation is a
   consistency check, not a judgement. Untraced writing (the heading at
   y≈2248 above the first trace, the specks) is outside the spike's
   universe, reported, never forced into a segment.
3. **The traces are the gold and nothing else.** No formatting gold
   (underline/strike) is derived from traces — a VLM understands those
   natively. The transcript carries the existing markers (`~…~` /
   `~~…~~`) but no gold checks them.
4. **Judged vs ride-along.** Boundaries + segment types are scored;
   transcripts ride along and are the user's in-app business, not the
   spike's judgement — "the other stuff is much harder and more annoying
   for them to verify so we should try and get it right first time".
5. **Types: the letter has both insertions and marginalia**, so the type
   check exercises `body` / `marginalia` / `injection`. Which trace-groups
   are which, and the injection points, are proposed by the extractor and
   adjudicated by the user.
6. **Spike scope: page-01 first**, then the postcard (two-direction text)
   and a handwritten form — the existing trace-adding tool gives them
   gold; the driver is artifact-parameterized so adding them is data +
   traces, not code.
7. **Baseline: geometry-only.** The report compares against the
   detector's own line grouping (the words' row fit, no VLM), not the
   served strip-path layout. "Ideally this path produces correct results
   and then it's better than geometry by definition."
8. **The word set.** The /tmp-era copy (346 words) contained the 526×492
   "grey mass" — already ruled not-a-word (commit 7f3d4aa, 2026-09-11:
   components over 2.5× the spacing are unclaimed ink). The fresh reader
   run emits 455 marks, the blob split into per-line pieces. The user
   confirmed the detection "mostly fine"; a couple of stacked words
   detected as one are DEFERRED (open item: fix the deterministic word
   finder vs. let the VLM point them out and fix after the fact).
9. **Detection state.** `tools/reader.py`'s trace path was broken — it
   constructed the old `Mark(strokes=…)` shape; `Trace` (`tools/trace.py`)
   is the class. Fixed 2026-09-12 (import + two renames); the tests had
   passed only because they ran with empty strokes. Word detection's home:
   `tools/reader.py` (`read_page`), `tools/mark.py` (`find_marks`,
   `baseline_row`, `waistline_row`), `tools/pagescale.py` (the ruler).
   The find-it path is being added to AGENTS.md's decision tree — this
   session's organisation lesson: the detection was undiscoverable, three
   stale pycs under the dead boxdet/boxrows names.
10. **Data lives in the repo.** Inputs moved from `/tmp/trace` to
    `tests/fixtures/page01-wordseg/` (`strokes.json` — the 44 raw traces,
    `words.json` — the fresh 455-mark run with `line`/`baseline`/
    `waistline`, `boxes.json`, `surface.json`; provenance in the dir's
    README). Stale and duplicate files deleted. The scan itself stays in
    the archive, reached by path — public repo, family material.
11. **Model path.** House glm-4.6v via the local :9123 proxy with
    CLOUDFLARE_AIGATEWAY_TOKEN (the route that served page-01), responses
    sha-keyed through `tools/vlm_cache.py` so re-runs are free.
12. **Checkpoints.** Stop at each milestone: 1 the renderer visuals, 2 the
    gold attribution for adjudication, 3–4 the model calls, 5 the report
    vs geometry-only.