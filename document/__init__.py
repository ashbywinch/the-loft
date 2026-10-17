"""The Document package: the model's document side.

One class per file, named after the class: the page and its chain of
collections (`Ink`, `Marks`, `Ruler`, `Words`, `Rows`), the geometry record
(`Rectangle`), the row record (`Row`), the correction's measurement
(`Verdict`), the page's `Transcript`, and the transcription that reads a page.
The pipeline's stage vocabulary (`stages.py` — the stages and a page's status
through them) and its JSON contracts (`schemas.py`) sit beside them.

A page is read by showing the model the page with its rows numbered and
asking for one transcript per row (see `transcript.py`); the model never sees
a file path, and the document side never opens one.
"""
