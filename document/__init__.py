"""The Document package: the model's document side.

One class per file, named after the class: the page and its chain of
collections (`Ink`, `Marks`, `Ruler`, `Words`, `Rows`), the geometry record
(`Rectangle`), the row record (`Row`) with its trust stages, the reviewer's
drawn row lines (`RowAdjustments`), the boxes and page size the detector
composes (`Boxes`, `PageSize`), the correction's measurement (`Verdict`), the
page's `Transcript` with its per-row record (`RowTranscript` — the model's
answer segment, which owns that answer's wire), the transcription that reads
a page, and the `Document` artefact with its line record (`DocumentLine`).
Every one of them owns its own
wire format: `from_dict` reads the record and `to_dict` writes it, so the JSON
on disk and over the API is built and read inside the class that models it —
never by a loader beside it. The pipeline's stage vocabulary sits beside them
(`stages.py` — the stages and a page's status through them).

A page is read by showing the model the page with its rows numbered and
asking for one transcript per row (see `transcript.py`); the model never sees
a file path, and the document side never opens one.
"""
