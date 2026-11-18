"""A lexical index over the archive's text — terms, not a query language.

The review's `search_items` asks one question: which recorded items mention
these words? A substring test cannot answer it — "walter 1917" is not a phrase
that appears in any document — and a model asked to search writes exactly that
kind of query.

SQLite's FTS5 answers it: every query word must appear (in any order), ranking
by relevance, case- and punctuation-insensitive. It lives here because
`loft/live` is the one package that speaks SQL (TECHSPEC §19.2).

The index is built in memory from the items in hand: the archive's text is
small (hundreds of kilobytes), so a rebuild costs microseconds and needs no
keeping-in-step with the store.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable

TERM = re.compile(r"[a-z0-9']+")

# Words a caller types as query SYNTAX. As literal terms they can never match,
# so a query written "walter and 1916" would fail on a document full of "and" —
# the operator is punctuation, and the caller's intent is the other words.
OPERATORS = frozenset({"and", "or", "not", "near"})


class TextIndex:
    """The archive's text as a searchable index: build it, then search terms."""

    def __init__(self, documents: Iterable[tuple[str, str]]) -> None:
        self._db = sqlite3.connect(":memory:")
        self._db.execute("CREATE VIRTUAL TABLE documents USING fts5(doc_id UNINDEXED, body)")
        self._db.executemany("INSERT INTO documents (doc_id, body) VALUES (?, ?)", documents)

    def search(self, query: str, *, limit: int = 5) -> list[tuple[str, float]]:
        """The documents mentioning EVERY word of the query, best first.

        The query is words: quotes, operators and word order are not syntax, so
        a caller cannot write a query the index fails to parse. A query with no
        words matches nothing.
        """
        terms = [term for term in TERM.findall(query.lower()) if term not in OPERATORS]
        if not terms:
            return []
        match = " ".join(f'"{term}"' for term in terms)
        rows = self._db.execute(
            "SELECT doc_id, bm25(documents) AS rank FROM documents WHERE documents MATCH ? ORDER BY rank LIMIT ?",
            (match, limit),
        ).fetchall()
        return [(str(doc_id), float(rank)) for doc_id, rank in rows]

    @staticmethod
    def terms(query: str) -> list[str]:
        """The words a query is searched by — the index's own tokenisation."""
        return [term for term in TERM.findall(query.lower()) if term not in OPERATORS]
