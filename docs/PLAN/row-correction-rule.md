# Row correction — how a drawn line edits a mostly-right page

Status: **LANDED** (`pipeline/rows/rows.py`, `document/rectangle.py`). The
screen that draws the lines is `docs/PLAN/row-review-ux.md`.

## The problem this fixes

The review screen exists so a reviewer can correct the machine's rows by
drawing a line along the writing that is one row. The first build of that
correction treated the drawn lines as **the whole annotation of the page**:
- a word was claimed if its centre fell within a *writing height* of the
  stroke's y-span, across the stroke's whole x range;
- claiming any word of a reading line **suppressed that line's draft row**,
  and its unclaimed words were apportioned to their neighbours (the
  fully-annotated page's rule);
- so one line drawn along one row could claim the row above or below
  wholesale, and the rows it touched lost the words the line never crossed.

The user's report (2026-11-02): *"I drew one line and then it decided to join
those words with other words not under the line. I drew another line and it
took the opportunity to remove row highlighting from the row immediately
above."*

## The rule

The draft rows (each reading line's words) are the base. A drawn line edits
them; it never re-groups the page.

1. **A stroke replaces a row it covers.** Two measures must agree: the
   stroke must *run across* the row (its x extent at least half the reading
   line's width), and it must cover at least half of the line's words inside
   that extent. Then it IS that line's row: every word of the line is
   claimed. A stroke that stops short of a row's last words still replaces
   it; a short stroke over part of a row does not. Tracing along a row that
   is already right changes nothing — verified: a stroke along page-01's row
   leaves all 41 tints exactly as they were.
2. **Otherwise it claims only the words it runs along.** Of the words whose
   box lies within the page's touch of the stroke (`0.38 × the writing
   height`, the detector's own `Ruler.touch`), a word is claimed only when
   its **centre** is within half a writing height of the stroke. That is the
   difference between a word lying along the line and a tall box from the
   row above or below that merely clips it.
3. **Every other word keeps its reading line's row.** A line that loses some
   of its words keeps the rest as its row — a partial correction leaves the
   row's other words exactly where they were. A line that loses all of them
   has no row left.
4. **Marks float free.** A small box (no taller than the writing) lying
   entirely above or below the stroke that draws its row, over a word of
   that row, is a mark in the leading (an asterisk): it is not a row's word.
   If it lies within a drawn row's writing (≥ half its height overlapping
   that row's words in x) it joins that row; otherwise it has no row.
5. **A word with no reading line** is apportioned by its neighbours: the
   line of a word it butts against, else the line of the nearest word on the
   same baseline, else no row.
6. **The nearest stroke wins** where two strokes claim one word (a double
   pass is one row; two strokes over one line split it between them by
   proximity).

## What a stroke can express

| The reviewer's intent | The stroke | Result |
|---|---|---|
| "this row is right" | traced along it | no change (rule 1) |
| "these two machine rows are one row" | over both | one row of both |
| "this machine row is two rows" | one stroke per visual row | each stroke takes its half; both name the line, words go to the nearer stroke |
| "this word belongs to the row above" | traced along the target row, through that word | the word joins it; its old row keeps the rest |
| a mark in the leading | not drawn | stays unrowed |

## Why not a halo

The old rule's tolerance was measured in writing heights and against the
stroke's *bounding box*: on page-01 (unit 40 px, word boxes 40 px tall, rows
as close as 11 px) a straight stroke along a row's centre passed within one
writing height of 82 neighbour words. The tolerance needed for a finger —
`0.38 × unit` — now applies to the *box*, and the centre test does the
disambiguation, so the same probe claims the row's own words and no others.

## Evidence

- `tests/pipeline/test_rows.py`: the gold page-01 fixture still reproduces
  the adjudicated rows and leaves exactly the asterisk without a row; new
  cases pin the local rule — a partial line leaves the rest of its row, a
  line does not claim the row 15 px below it, a second line leaves the row
  above alone, a line in the gutter claims nothing. The merge case is now a
  stroke through both rows' writing (the line is the row; a gutter stroke
  is not).
- Real page, mockup at 390×844: a line along a row → 41 rows, all 41 tints
  unchanged; a second line on the row above → all 41 tints still present;
  a line over part of the row below → 42 rows (that row splits), every
  other tint unchanged.

## Files

- `pipeline/rows/rows.py` — `_Claims` (claim, replace, discount, apportion).
- `document/rectangle.py` — `Rectangle.distance_to_segment`,
  `Rectangle.distance_to_point`, `point_segment_distance`.
