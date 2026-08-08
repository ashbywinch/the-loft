"""The Loft Python tools — the object-model nouns, one CLI surface.

- ``archive`` / ``store`` — the append-only archive library and its store;
  ``Archive`` is the aggregate noun (publish / create-demo / capture).
- ``records`` — the typed model (Item, Person, Place, Theme, Relationship).
- ``memory`` — the narrator's capture flow (the UI's word: "Add a memory").
- ``gedcom_document`` — the GEDCOM 7 interchange format.
- ``projection`` — the derived app-facing surface (app/data).
- ``server`` — the archive's one server (serve + the memory-capture API).
- ``placeholders`` — the honest stand-in assets (paper/photo/object/avatar).
- ``demo_data`` — fictional demo content (never real names).
- ``document_capture`` — the scanned-document capture flows.
- ``ai_client`` — the LLM client.
- ``cli`` — the one operator surface, reached via the repo-root ``loft``
  wrapper; no per-module ``__main__`` shims (coding-standards.md, 2026-08-06).
"""

# The noun modules import lazily from cli.py and the Archive methods — this
# package init stays empty so importing tools.archive never pulls the heavy
# capture modules (memory's AI client, the document data).
