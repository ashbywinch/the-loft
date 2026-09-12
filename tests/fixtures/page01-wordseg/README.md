# page-01 word-segmentation inputs

The spike's canonical inputs for page-01 of `adopt-20260813-201004` (the
Music College letter, 2544×4642) — see
`docs/plans/vlm-word-segmentation-spike.md`.

| File | What | Produced by |
|---|---|---|
| `words.json` | 455 detected marks: `x0,y0,x1,y1` (page px), `line` (the detector's row), `baseline`/`waistline` (measured, page px) | `tools/reader.py read_page` on the archive's `oriented/page-01.jpg`, 2026-09-12 (the Trace-bridge fix) |
| `strokes.json` | The 44 raw reviewer traces, normalized 0–1 (one drawing can drag off-canvas — clamp at use) | the sketch tool's saved review traces |
| `surface.json` | The letter's ink extent (`x0,y0,x1,y1`, page px) — the whole-page attempt's crop | the reviewer's outline of the letter |
| `boxes.json` | The line boxes the reader produced (40 from traces, 40 from the detector) | `read_page` run above |

**Regeneration:** `.venv/bin/python tools/reader.py --page <archive>/oriented/page-01.jpg --trace-dir tests/fixtures/page01-wordseg` (needs the removable-media batch mounted).

The word set here is the detector's marks, not a curated "words only" list —
the spike's universe is the marks the traces cover (the rulings, spike plan
§"Rulings while starting").