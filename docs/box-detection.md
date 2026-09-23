# Box detection — how a page's writing is found and boxed

Status: working (2026-09-10). The reader is `tools/reader.py`, the page's
scale is `tools/pagescale.py`, and the acceptance check is `tools/boxjig.py`.
Tests: `tests/test_reader.py` (synthetic pages) and `tests/test_pagescale.py`
(the scale). The design work and the user rulings behind it are in
`docs/PLAN/segment-review-stories.md`.

## What it does

Reads a scanned page and gives **every line of writing** a box that hugs that
line's ink at that line's slope. Where the reviewer has traced a line, the trace
defines that line and replaces the detector's box over the span it covers — the
detector boxes the page, the reviewer corrects it.

## The stages, and the invariant each holds

| stage | holds |
|---|---|
| ink mask | a pixel is ink when it is darker than the paper around it |
| artifacts | long thin ink (scan lines, rules) is deleted — a 1px scan line welds every line it crosses into one shape |
| shapes | connected components are words (letters, in print); specks relative to the writing are dropped |
| lines | the shapes' baselines cluster and fit into one baseline per line of writing |
| assign | **every shape belongs to exactly one line**; a shape spanning two lines is cut at the row where its nearest baseline changes |
| boxes | one box per line-run: that line's ink, split where a gap is a column break, bounded by the distance to the neighbouring baselines |
| strokes | a stroke **is** a line: it names the line it was drawn along; a trace replaces the detector's box over the span it defines |

Layer by layer check: the page's scale comes from `tools/pagescale.py` — the
writing's own height (the median height of its ink shapes) times the ratio
between line spacing and writing height, the ratio measured from the reviewer's
traces when enough exist. **No threshold is a page constant**: every distance is
a multiple of that ruler (`PageScale` in `tools/pagescale.py`).

## The measurements

On the first real letter (page-01, 44 traced lines), the current version:

| | assisted | detector alone |
|---|---|---|
| boxes | 62 | — |
| yellow lines mis-boxed | 1 | n/a |
| boxes holding two lines' words | 17 | — |
| a box spanning two yellow lines | 0 | n/a |
| words missed entirely | 1 | — |

The jig prints these and exits non-zero on a violation:

```
.venv/bin/python tools/reader.py
.venv/bin/python tools/boxjig.py /tmp/trace
```

`boxjig.py` needs the archive page and a stroked run, so it is a manual check
(like `make verify`), not part of `make test`; the synthetic tests are.

## The traps this work paid for

- **Page-wide thresholds chain.** Any threshold comparable to the noise merges
  neighbours transitively — 300px "lines" from a 60px pitch. Thresholds must be
  stated in the page's own scale and compared against a seed, never a growing
  set. Five attempts to estimate a page-wide pitch failed on the real letter
  (70/34/260/53/25px against a true ~63px); the writing's height is what the
  page does give you.
- **Mixed units.** Ink measured in working pixels and strokes in page pixels,
  both scaled once more, put boxes off the page — invisibly, until the jig
  printed corner coordinates beyond the page. `reader.py` states its coordinate
  boundary in the module docstring; the box builders are the only crossing.
- **Ink welding two lines.** A descender touching the next line's ascender makes
  one shape spanning both; the fitted lines say where the boundary is, so the
  shape is cut by row assignment.
- **A "faithful" refactor is not faithful.** Moving geometry onto `Shape`/`Line`
  changed the page three times: a streak rule tolerating four rows rather than
  three, a spread test using the raw offset instead of the perpendicular
  distance, and two non-overlapping fits compared at one centre instead of
  between them. Each was caught only by comparing numbers before and after.

## Not done here

- The detector's own corrections (the over-inclusion: boxes reaching into a
  neighbouring line, and the words it misses) — the counts above are its report
  card, and reducing them is the point of the work. Two measured attempts are
  recorded in the code with their before/after.
- The port into the review surface: the sketch that collects traces
  (`/tmp/trace_spike.py`) is a throwaway, never to be ported as-is.
