---
name: show-the-user
description: |
  How to show the user a visual artifact (render, map, zoom, case sheet)
  in this repo: which existing tool renders it, how to serve it on the
  LAN URL, and the mandatory self-check before presenting. Read this
  before showing the user any image.
---

## The reuse rule (2026-09-13: a case-sheet renderer shipped ~100 lines of
generic drawing — caption bars, halo labels, dashed cut rows, dropped-row
runs — that belonged in `tools/page_visuals.py`)

Presentation code is generic until proven otherwise. Before writing any
drawing helper in a `research/` script — a caption bar, a text label with
a halo, a dashed rule, a run-grouping, a crop-and-scale — check whether
`tools/page_visuals.py` already has it; if it does, import it. If it does
not and a second caller could want it (diagnose zooms and splitter sheets
both label boxes; both crop-and-scale), add it to `tools/page_visuals.py`
with pin tests in `tests/test_render.py`, then use it from the script.
A `research/` script keeps only its domain content: which component, which
numbers, which caption. A new primitive lands with three proofs: the pin
tests pass, every affected render is eye-verified after the move (self-read
the fresh sheets: captions, piece labels, cuts, drops all present), and
`make spike-maps` is green.

## The LAN server (already running — verify, don't start)

`spike-evidence`: `python3 -m http.server 8833 --bind 0.0.0.0
--directory research/spike-word-segmentation`, `detached: true`, ready
condition on port 8833. Check with `hub describe spike-evidence`; if it
is down, stop then start (never `restart` — that reuses the old spec and
can leave a 127.0.0.1-only bind). The docroot is
`research/spike-word-segmentation`, so a file at
`research/spike-word-segmentation/<rel>` is shown as
`http://192.168.1.251:8833/<rel>`.

## Which tool renders what (reuse — never ad-hoc)

| To show | Tool | Output |
|---|---|---|
| Expected-segmentation map + diagnose zooms | `make spike-maps` (runs `render_expected_map.py` + `diagnose_sites.py`, then proves every output is newer than the mapping — a stale render fails the target) | `gold/expected-map.png`, `diagnose/site_*.png` |
| A new disputed site | Add a `SITES` entry in `diagnose_sites.py` (the `SITES` table is the only place zoom windows live), then `make spike-maps` | `diagnose/<site>.png` |
| Splitter case sheets (raw component vs pieces/cuts/drops) | `.venv/bin/python research/spike-word-segmentation/render_split_cases.py` (live detector output, never hand-copied numbers) | `split-cases/case*.png` |
| Numbered-boxes VLM input for a section | `.venv/bin/python tools/spike_vlm_segments.py render --name <n>` | `evidence/<n>.png` |
| Word geometry (baselines/waistlines) on a region | `tools/page_visuals.py render_focus` / `render_geometry` | caller-chosen path |
| Row tints / minimal unions (library primitive) | `tools/render.py tint_row` / `render_rows` | caller-chosen path |

## Before presenting (mandatory)

1. Verb: SHOW, then confirm. Every claim about the page is an image; a
   table or row of numbers is never the answer by itself. Numbers appear
   only as labels ON the image.
2. A comparison between two states (the user's rows vs the library's, a
   before/after, two candidate placements) is ONE image with BOTH states
   side by side, the same window and scale — never two URLs the user must
   mentally diff, and never a description of the difference.
3. Draw the evidence the claim depends on: the user's lines, the word
   boxes, the numbers — whatever the question is about. If the claim is
   "the lines don't reach these words", the lines MUST be visible on the
   image.
4. Regenerate through the tool above — never present a file the current
   data didn't produce.
5. Self-read the fresh file (`read <path>?q=...` with a question that
   quotes the caption/labels back) and confirm overlays are present:
   ad-hoc crops twice shipped without overlays, and a double-downscaled
   pair shipped at 900x56px (2026-09-18) — unreadable. Also pixel-check
   at the delivered size: `review_image` shrinks everything; a ribbon
   window can end up a sliver. Check the FINAL file, not the pre-resize
   canvas.
6. Check the file is actually viewable: width ≤ 1000px and the whole page
   under ~1MB (2026-09-13: a 1580px contact sheet read as blank on the
   phone; a 3MB PNG page was too heavy to be a review). The review format
   is one file, not a page of files: review copies go through
   `tools/page_visuals.review_image` (900px JPEG q68 — the six splitter
   sheets total ~330KB vs 3MB as PNGs), stacked into a single contact JPG
   (`all_cases.jpg`, ~340KB) via `stack_sheets`, with the renderer
   asserting the budget (`assert total < 1_200_000`). One URL, one image,
   no HTML frame — an HTML multi-image page renders blank on Android
   Chrome (2026-09-13), while the same bytes as one JPG render fine.
7. Present the LAN URL (`http://192.168.1.251:8833/<rel>`), one per
   artifact, with one line each saying what it shows.

## Standing rules

- Render ids are never cross-checked off a picture (membership is owned
  by `tests/test_spike_gold.py` + `gold/expected-mapping.json`).
- Pictures are for the user's eyes; the test owns the facts.
