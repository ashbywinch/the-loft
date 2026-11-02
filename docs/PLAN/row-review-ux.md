# Row review — the phone screen (design record)

Status: **PROPOSED** for the screen; the renderer refactor in §5.1 is LANDED
(`document/row_tint.py`, `Row.tint_rects`, `join_band` moved), so the rules
the screen consumes are the pipeline's own. The screen was built and walked
as a mockup at 390×844 — a local working artefact, not in the repo: it serves
a real page and its OCR words, which never enter the public checkout. Its
`server.py` answers `POST /rows` with `RowTint` records built by the
pipeline's classes, and the page draws them in SVG, so the mockup carried no
colour or band code of its own.

The reviewer's own lines are **yellow, like a highlighter**, over the page; the
machine's rows are tinted in **different colours**, so the two layers and the
rows themselves are distinguishable. Clicking a drawn line removes it again.

Inputs: the reviewer's statement of purpose (below, verbatim); the existing
multicoloured row code (`pipeline/rows/render.py`, `pipeline/rows/rows.py`);
the correction seam (`pipeline/api/sync.py:apply_row_adjustments`, the
`row-adjustments` route at `pipeline/api/server.py:818`); the review surface
as it is today (`app/views/review.js`, `app/styles.css`); `docs/UI.md`;
`docs/ux-standards.md` (P2, P5, P8, P13, P16, P17); the real page
`adopt-20260813-201004/oriented/page-01.jpg` with its reading
(`ocr-guess/page-01.words.json`, 374 words on 41 reading lines).

---

## The purpose

> "It's solely for the user to correct the guessed lines by drawing their own
> alternative lines."

Everything on the screen serves that sentence. Two requirements follow, in
the reviewer's own words:

### 1. "To do this they need to actually see the current lines, so for a start we need to render them with the existing multicoloured line drawing code so they can be distinguished."

Today the screen draws no guessed rows at all: `.rv-bands` is populated only
from the *correction* (`review.js:1551`, `renderRowBands` at 1347), so a
fresh page has no bands; the guess appears only as 41 single-colour
`.rv-lb` boxes with no way to tell which words belong together. The fix is
§1 and §2: the same golden-ratio hue per row, the same word boxes joined by
the minimal band the pipeline already renders, over the page.

### 2. "Then we need to correct the lines using this new info and redraw for the user so they can continue."

Drawing a line on the page is the correction's only input. On lift the whole
drawn set goes to `apply_row_adjustments` → `Rows.from_traces(...).adjust()` →
the corrected rows come back → the screen redraws them, in their own colours,
replacing the set it showed. A drawn line stays until it is removed; when the
rows are right the reviewer finishes.

### What is on the screen

The page, the current rows rendered distinguishably, the draw interaction,
the redraw after a correction, the removal of a drawn line, and the finish.
Nothing else.

### What is not, and why

| Removed | Why it cannot serve the loop |
|---|---|
| Row-number chips (`.rv-rownum`) | 41 chips at a 15 px pitch overlap into a column of labels over the writing; the colour already names the row, and the row set changes on every correction, so a number is not an identity. |
| The words panel (`.rv-txpane`) | the row screen corrects rows, not text; a permanent half of a phone screen showing the reading competes with the page the reviewer must read ink from. |
| Violation prose | "line 2 merges reading lines [7, 8] into one row" is the library's sentence (rows.py:264), not the reviewer's; the corrected rows are the answer, and they are visible. |
| Onboarding copy ("Draw with one finger — move with two") | the page itself is the tool, and the first line demonstrates it; instructions over a letter are noise the reviewer must dismiss. |
| Line picking / a select-a-line mode | a line is claimed by drawing it; selecting one first is a second state to learn and a second way to be wrong. |
| Status history ("Rows checked · 1 line drawn") | the loop's state is what is on the page: the rows, the line, the finish. |

The transcription surface (stage 6) is unchanged by this record except that
its row tools leave it: the row work becomes this screen.

---

## 1. The colours and the bands — the pipeline's records, not a copy

The row tints are the pipeline's own data, and the refactor made that data
reusable without a raster copy:

| Rule | Where it lives now |
|---|---|
| a row's colour (a distinct hue per row, golden-ratio spacing, alpha 55) | `pipeline/rows/render.py:RenderStyle.colour` |
| the band joining two adjacent words | `document/rectangle.py:join_band` (moved beside the geometry it belongs to) |
| a row's tint geometry — its words' boxes and their joins | `document/row.py:Row.tint_rects` |
| one row's tint as data: colour + rectangles, wire `{"colour": [r, g, b, a], "rects": [{x0, y0, x1, y1}, …]}` | `document/row_tint.py:RowTint` |
| the pixels | `pipeline/rows/render.py:tint_row` — draws `RowTint.of(row, colour)` |

So the pipeline paints `RowTint`'s rectangles into its overlays, and the review
screen draws **the same rectangles** as SVG: one path per row, the rectangles
as subpaths, `fill` = the record's `rgb(r g b)`, `fill-opacity` =
`alpha / 255`. One path per row (not per rectangle) because `render_rows`
composites one overlay: overlapping subpaths of one path fill once, at the
alpha, exactly as the pipeline's pixels do — per-rectangle alpha would double
the tint over every join.

The reviewer's own lines are the only thing the app computes itself: yellow,
highlighter-wide, `#fad21e` — `render_rows`' stroke colour.

No raster crosses the wire. A JS port of the colour/band rules was rejected
(two copies drift); a server-rendered PNG was rejected too (a second raster
pipeline and a cache to invalidate). The records are the reuse.

## 2. Where the rows come from

The drafts payload gains **`tints[page]`**: the tints of the rows the screen
shows — the correction when one exists, else the reading's rows — each built
by the pipeline:

```python
rows = Rows.from_words(words, PageSize(reading.width, reading.height)).adjust(RowAdjustments(drawn))
tints[page] = [RowTint.of(row, RenderStyle().colour(index)).to_dict() for index, row in enumerate(rows)]
```

The correction's answer carries `tints` for the corrected rows, so after a
drawn line the screen repaints from the answer without recomputing anything.
The row count is `len(tints)`; a page with no persisted words has no `tints`,
shows its note ("no word boxes to correct — re-read the page") and the finish
is disabled.

Cost: one record per row carrying its words' boxes and joins — page-01 is
41 rows, 42 KB of JSON (374 box records), gzipped far less.

---

## 3. The loop

There are no modes and no state strip. The screen is always the same thing —
the page, the machine's rows in their colours, and the reviewer's lines in
yellow — and what changes is those two things.

```
the guessed rows, each its own tinted colour
        │  draw one line along a wrong row (one finger, anywhere on the paper)
        ▼
the yellow line is on the page; the correction is posted
        │  the server answers: Rows.from_traces(...).adjust()
        ▼
the rows redrawn: the line's row is the row it crossed, every other row unchanged (`docs/PLAN/row-correction-rule.md`)
        │  draw another line          → post, redraw
        │  click the yellow line      → it goes away; the rest re-apply
        │  no lines left              → the guessed rows are back
        ▼
finish  → the page leaves the row queue; the next page opens
```

- **The reviewer's line is yellow, like a highlighter**: the pipeline's stroke
  yellow (`#fad21e`, `render.py`), wide (11 screen px) and translucent
  (≈0.62, multiply), so it lies over the paper as a marker and never reads as
  one of the row tints.
- **The rows are different colours**, one hue per row (the golden-ratio
  spacing of `RenderStyle.colour`), so neighbouring rows are told apart.
- **Clicking a drawn line removes it.** It is a tap (a stroke shorter than 24
  page px) within 26 screen px of the line; the remaining lines re-apply and
  the rows redraw.

The wire is unchanged: `rowAdjustmentBody(session.strokes, size)` → normalised
`{lines: [[[x, y], …], …]}` (whole set every time) → `POST
/api/sync/batch/<batch>/page/<page>/row-adjustments` → `apply_row_adjustments`
writes `<page>.row-adjustments.json` and `<page>.rows-adjusted.json` and
returns `{rows, violations}` → `session.rows = rows` → repaint.

Two consequences worth stating:

- **A line is the reviewer's, and stays.** It is kept as drawn (the artefact
  is the record) and drawn back on reopen (`strokesFromAdjustments`).
- **Colours name rows in the current set.** A merge removes a row, so every
  row below it moves one hue step. The set changed — the colour says which
  row is which *now*, which is what the reviewer is looking at. No attempt is
  made to keep a row's colour across corrections; the pipeline has no row
  identity across corrections either.

A line that claims no word leaves the rows unchanged and stays on the page
so it can be removed or drawn again. A refused request (no persisted words,
malformed body) leaves the rows and the line as they were; the bar states
the failure in one line.

---

## 4. The phone layout — 390×844, portrait

```
┌──────────────────────────────────────────────┐ 48  .rv-topbar: ← Review
│                                              │
│  the page, as large as the writing           │
│  41 rows, each its own hue, over the ink     │ 731  .rv-imgpane > .rv-imgbox
│  (one finger draws; two pan and pinch)       │      > .rv-layer
│                                              │
├──────────────────────────────────────────────┤ 65  .rv-rowbar
│ [              Rows are right              ] │      the one primary, 366×44
└──────────────────────────────────────────────┘
```

Measured in the mockup at 390×844 (the deliverable's size):

| | value |
|---|---|
| the shell | 390 × 844, `scrollWidth` 390, `scrollHeight` 844 — nothing to scroll to reach the page or the finish |
| top bar | 48 (back only; no title, no chips) |
| the page pane | 731 (flex 1) |
| the bar | 65 on screen; the finish is 366 × 44 at the thumb |
| the view | the writing's width: 1454 px + 40 px air over 390 → **scale 0.254** |
| the writing on screen | 370 × 600 px — **all 41 rows at once**, ≈14.6 px pitch |
| the page on screen | 647 × 1180 (its blank margins cropped left and right) |
| a whole-page fit, for comparison | scale 0.153 → 8.9 px pitch — no room to draw between rows |

```
.rv-rows
├─ .rv-topbar                       ← Review
├─ .rv-imgpane > .rv-imgbox
│   └─ .rv-layer                    page px, one CSS transform
│       ├─ img.rv-page
│       ├─ svg.rv-bands > g.rv-tint > path.rv-band   one path per row
│       └─ svg.rv-draw > polyline.rv-stroke          one line per drawing
└─ .rv-rowbar > button.rv-btn.rv-btn--primary
```

- The view is `widthFitRect(paneW, paneH, rowsRect)` over the union of the
  rows' bands (review.js:1303) — the writing's width, not the page's — so a
  drawn line can span a whole row and claim all of its words.
- **Portrait is the design.** The material is a portrait letter; the screen
  is a portrait phone. A wide window shows the same column at 430 px, centred.
- **The page is the draw tool.** There is no draw button and no mode: one
  finger on the paper draws, two fingers pan and pinch. Nothing on the screen
  covers the ink.
- **The finish is the only control**, full width in the bottom bar, inside
  the thumb's arc (`docs/ux-standards.md`: targets ≥ 44 px).
- **Removal is a tap** on a drawn line — the same finger, no second control.
- Every colour is a fill over the page; there is no border, number, label or
  panel over the writing.

---

## 5. Implementation plan

Each step is shippable on its own; nothing below changes `Rows.adjust`,
`Rows.validate` or the correction's wire.

### 5.1 The renderer's records (refactor)

| Where | Change |
|---|---|
| `document/rectangle.py` | **+** `join_band(left, right)` — moved here from `render.py`, beside the geometry it joins |
| `document/row.py` | **+** `Row.tint_rects()` — the words' boxes in x order, then the band joining each neighbouring pair |
| `document/row_tint.py` (new) | **+** `RowTint(colour, rects)` with `of(row, colour)`, `to_dict` (`{"colour": [r, g, b, a], "rects": […]}`) and `from_dict` — one row's tint as data, the wire the app draws |
| `pipeline/rows/render.py` | `tint_row(draw, row, colour)` draws `RowTint.of(row, colour).rects`; the local `join_band` goes (imported from `document.rectangle`); `render_rows` and `render_map` call the new signature |
| `tests/document/test_row_tint.py` (new) | `tint_rects` = words + joins in order (a single word is its own tint); the record round-trips; `render_rows` paints exactly the record's rectangles at the record's colour |

### 5.2 `pipeline/api/sync.py`

| Where | Change |
|---|---|
| `PageReviewState` (462–470) | **+** `tints: dict[str, Any]` |
| `_page_review_state` (473–515) | for each page with `readings.words_path(page)`, build the rows it will show (the correction when one exists, else `Rows.from_words(...).rows()`) and record `[RowTint.of(row, RenderStyle().colour(i)).to_dict() …]`; skip a page without words |
| `draft_payloads` (518–570) | **+** `"tints": state.tints` in the document record |
| `apply_row_adjustments` (399) / `RowCorrection` | **+** `tints` on the answer — the corrected rows' records, so the screen repaints from it |

`Rows.adjust`, `Rows.validate` and the correction's request are unchanged.

### 5.3 `app/views/review.js`

| Where | Change |
|---|---|
| imports | **+** nothing: the colours arrive in the payload's tint records |
| `openViewer` (1460) | `session.tints = doc.tints?.[page] \|\| []` replaces `session.adjustedRows` (1551) and `session.rowChecked` (1554); the `.rv-bands` SVG (1559–1561) becomes `<svg class="rv-tints"><g class="rv-tint"></g></svg>` |
| `openViewer` gains `lines` (default `true`) | the row screen passes `false`: the `.rv-lb` overlay (1493–1527), the box click-to-edit handler (1811–1834) and the per-line read rotation are skipped; the transcription surface keeps them |
| `openViewer`'s fit (1620–1647) | the row screen's view is `widthFitRect(pane.clientWidth, pane.clientHeight, rowsRect(session.tints))` — `rowsRect` (new, exported) unions the records' rectangles — instead of `initialView`, so every row is on screen at a drawable pitch |
| `renderRowBands` (1347) → `paintRowTints(container, session.tints)` | one `<path>` per tint: its rectangles as subpaths, `fill` = `rgb(r g b)`, `fill-opacity` = `alpha / 255`; the `.rv-rownum` span (1358) is deleted |
| `syncRowAdjustments` (1369) | on success `paintRowTints(container, payload.tints)` (1383/1392); on failure keep the drawn lines and state it once |
| `onDown` (1746), `onMove` (1685), `onUp` (1715) | delete `session.drawRows` (1549) and its toggle (1562–1568): one pointer always starts a stroke, the one-finger pan branch (1693–1699) goes, two fingers pinch/pan as today; `onUp`'s line-or-tap logic is unchanged |
| `rowDeleteTolerance` (1230) | **deleted**: `onUp` calls `strokeAt(session.strokes, stroke[0], 22 / paneScale(session))` — a 22 screen-px finger target at any zoom (the page-px floor was 3 screen px at the row view) |
| row-tools block (1562–1599), `setRowStatus` (1412), `rowToolsNote` (1404) | **deleted** — no toolbar on the page |
| `renderRowSurface(main, session)` (new) | builds `.rv-rows` = `.rv-topbar` (back) + `.rv-imgpane > .rv-imgbox` + `.rv-rowbar` with the one `.rv-btn.rv-btn--primary`; calls `openViewer(session, imgBox)`; never builds `.rv-txpane` or `.rv-lb` |
| `finishRows(session)` (new) | posts `rowAdjustmentBody(session.strokes, session.imgSize)`; on success advances to the next page with rows pending; on failure the primary says so and nothing is lost |
| `render` (400) | `ctx.name === "rows"` → `renderRowSurface`; `#/rows/<batch>/<doc>/<page>` |
| `renderBatchList` (479–493) | the "Rows to check" card links to the first pending page's document and page instead of the batch's document list |

`app/app.js` `ROUTES` gains `rows: review`; `app/router.js` `PARENTS` gains
`rows: "review"`. The transcription surface keeps its own view (`.rv-split`,
`.rv-txpane`) — it simply no longer carries row tools.

### 5.4 `app/styles.css`

| Selector | Change |
|---|---|
| `.rv-rows` (new) | the screen root: `height: 100%; display: flex; flex-direction: column` |
| `.rv-imgpane` (1730) | on `.rv-rows`: `flex: 1 1 auto; border-right: 0` — the page gets the whole middle |
| `.rv-tints` (new) | `position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none` — the tint records' paths, scaled with the layer |
| `.rv-tint path` (new) | `stroke: none`; the fill and its opacity are inline, from the record |
| `.rv-stroke` (2130) | **the highlighter**: `stroke: #fad21e; stroke-width: calc(11 * var(--rv-inv, 1) * 1px); opacity: .62; mix-blend-mode: multiply` — 11 screen px at any zoom, the pipeline's stroke yellow; `renderView` (1435) sets `--rv-inv` = 1/scale on `.rv-layer` |
| `.rv-rowbar` (new) | `flex: 0 0 auto; padding: 10px 12px calc(10px + env(safe-area-inset-bottom)); background: var(--card); border-top: 1px solid var(--line)` |
| `.rv-rowbar .rv-btn--primary` (new) | `flex: 1; min-height: var(--control-h)` |
| `.rv-rowband`, `.rv-rownum` (2146–2164) | **deleted** |
| `.rv-rowtools`, `__status`, `__draw`, `__clear`, `__right`, `.is-busy`, `.is-failed` (2165–2201) | **deleted** |
| `.rv-rotate`, `@keyframes rv-hint` (1696–1718) and the element in `renderSurface` (886–890) | **deleted** |
| `.rv-zoom`, `.rv-zoom-btn` (2253–2276) | **deleted** |
| the portrait hide block (2203–2219) | **deleted** — portrait is the design |

`docs/UI.md` records `.rv-rows`, `.rv-tints`, `.rv-rowbar` as the screen's
components.

### 5.5 Tests

1. `tests/document/test_row_tint.py` (new): `Row.tint_rects` = the words plus
   their joins in order (a single word is its own tint); `RowTint` round-trips
   through its wire record; `render_rows` paints exactly the record's
   rectangles at the record's colour.
2. `tests/pipeline/test_server.py`: the drafts payload's `tints[page]` for
   page-01 has 41 distinct colours, each row's rects equal
   `Row.tint_rects()`, and the correction's answer carries the corrected rows'
   `tints` (40 for the demo line).
3. `app/tests/views/review.test.js`: the `rowToolsNote` tests (1385–1388)
   and `rowDeleteTolerance`'s (1347–1349) go with their functions; add
   `paintRowTints` (one path per tint, `fill` = `rgb(r g b)`, one
   `fill-opacity` per row) and the 26-screen-px tap tolerance at scales 0.15,
   0.27 and 0.58.
4. The walk (P13/P16, 390×844, the real batch): the guessed rows in their
   colours → draw one line → the corrected set replaces them → tap the line
   → the guessed rows return → draw again → finish → the next page opens.
   Screenshots: the rows, a drawn line, the corrected rows.

---

## 6. Acceptance

- At 390×844 the page and the finish are on screen with no scrolling
  (`scrollHeight === innerHeight`), the finish inside the thumb's reach.
- The guessed rows are visible before anything is drawn, in the pipeline's
  colours; adjacent rows differ by 0.618 of the hue wheel and are
  distinguishable at the row view's ≈14.6 px pitch.
- A drawn line is yellow over the paper (the pipeline's `#fad21e`, highlighter
  width and translucency) and the redrawn corrected set is visible
  (41 rows → 40 rows on the mockup's line; the same result `Rows.adjust`
  gives for that line).
- Clicking the drawn line removes it and the rows redraw; no other control.
- For the same rows, the screen's tint paths and `render_rows`' image are the
  same geometry at the same colour — `RowTint` is both, by construction
  (pinned by `tests/document/test_row_tint.py`).
- The row screen's DOM has no `.rv-rownum`, no `.rv-txpane`, no
  `.rv-rowtools`, no `.rv-lb`; `grep -rn "rv-rownum\|rv-rowtools\|rv-rotate\|rv-zoom" app/` returns nothing.
- No image route: `grep -rn "rows.png\|row_overlay" app/ pipeline/` returns nothing; the app's row layer is SVG built from the payload's tint records.
- `app/` and `pipeline/` diffs are exactly the rows in §5.

---

## 7. Decisions

| Decision | Why | Refused alternative |
|---|---|---|
| The tint is a record (`RowTint`: colour + rectangles), drawn twice | the pipeline paints it, the screen draws it — one geometry, one colour; no copy of either rule in JS, and no raster over the wire | a JS port (two formulas drift); a server-rendered PNG (a second raster pipeline, a cache to invalidate) |
| Colour by position in reading order | that is the enumerate `render_rows` uses; the hue re-spacing IS the visible fact that the row set changed | a stable colour per row identity — the app has no such identity across corrections, and inventing one lies |
| The tint is one group at 55/255, one path per row | matches PIL's opaque overlay composited once; per-shape alpha doubles every overlap | per-shape `rgba` — visibly darker overlaps, diverging from the export |
| The rows and their tints come from the server (`tints[page]`) | the app has no words to group; `Rows.adjust`/`Row.tint_rects` already are the one definition of a page's rows | a JS grouping rule — two definitions of one page's rows, drifting |
| One finger draws; no mode | the given interaction, and no mode means no invisible state and no toolbar over the ink | a `Draw` toggle — a state to learn and the last design's toolbar covered the paper |
| The page is the tool; the finish is the only button | every pixel of paper is the reference, and the one control is the flow's end | a toolbar, a zoom pair, a words button — the last design's screen |
| Tap a drawn line to remove it | one finger, no second control, no destructive bulk action | a clear-all button — destroys the reviewer's work with one press, and undo then becomes mandatory |
| No numbers, no prose, no instructions | none of them serves "see the rows, draw a line, see the correction" | keeping them "for clarity" — the screen's job disappears under its chrome |
