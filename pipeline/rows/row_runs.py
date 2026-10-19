"""The dropped rows, grouped into the contiguous runs they form.

`contiguous_runs` groups sorted row indices into bands: one run is one
ascending list of adjacent rows ([1, 2, 3] is rows 1..3), and a sheet draws one
band per run. The shape is a list of lists because that IS the wire its callers
read — a run indexes as a list (`run[0]`, `run[-1]`) — and naming it keeps the
nesting from being read as rows of something else.
"""

from __future__ import annotations

RowRuns = list[list[int]]
