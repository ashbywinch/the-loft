"""The Document artefact: the pages one piece of writing runs over, and its writing.

A document is what the grouping stage opens and the transcription stage fills:
the pages it runs over, the boundary evidence that opened it (its `greeting` and
`signoff`), its state, and its writing line by line. The draft the pipeline
proposes and the record the review gate agreed are ONE type — the status is the
state (docs/PLAN/pipeline-stages-plan.md: draft is a state, not a second type).
A draft's stored value is ``"review"`` (the pipeline's word for it); the
reviewer's two decisions are the other states.

The artefact's own shape is the fields here; a document entry in the registry's
boundaries also carries the transport's keys (`batch_id`, `doc_index`, `text`,
`confirmed_at` — the confirmation payload is what gets recorded), which are the
transport's, not the artefact's. `DocumentLine` is the line record — what the
writing says, where it sits, and what it is — and lives beside `Document`
because the two change for one reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from document.word import Word

# The Document's states — the status is the state. A draft's stored value is
# "review" (the pipeline's word for it); the reviewer's two decisions are the
# other states.
DocumentStatus = Literal["review", "confirmed", "rejected"]
DOCUMENT_DRAFT: DocumentStatus = "review"
DOCUMENT_AGREED: DocumentStatus = "confirmed"
DOCUMENT_REJECTED: DocumentStatus = "rejected"

DOCUMENT_STATUSES: tuple[DocumentStatus, ...] = (DOCUMENT_DRAFT, DOCUMENT_AGREED, DOCUMENT_REJECTED)


@dataclass(frozen=True)
class DocumentLine:
    """One line of a Document's writing, in reading order: what it says, where
    it sits on its page, and what it is — body writing, an injection (naming
    the line it follows), or marginalia.

    `box` is the line's box on its page, page pixels ([x0, y0, x1, y1]), or
    None when no geometry anchors it; `box_source` says how the box was found
    ("reader" for a reading's own line). `words` are the line's word boxes,
    inline like a row's (a line never references another file's word ids).
    `conf` is the anchor's confidence where a reading scored one.
    """

    index: int
    page: str
    text: str
    box: list[float] | None
    orientation: int
    box_source: str
    words: list[Word]
    kind: str
    conf: float | None = None
    injection_after: int | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DocumentLine:
        """The line a document record describes: its words read inline, its
        optional confidence and injection target left unset when absent."""
        return cls(
            index=int(raw["index"]),
            page=str(raw["page"]),
            text=str(raw["text"]),
            box=raw.get("box"),
            orientation=int(raw.get("orientation", 0)),
            box_source=str(raw.get("box_source", "")),
            words=[Word.from_dict(record) for record in raw.get("words", [])],
            kind=str(raw.get("kind", "body")),
            conf=raw.get("conf"),
            injection_after=raw.get("injection_after"),
        )

    def to_dict(self) -> dict[str, Any]:
        """The line as its document record — the optional keys only when the
        line carries them."""
        out: dict[str, Any] = {
            "index": self.index,
            "page": self.page,
            "text": self.text,
            "box": self.box,
            "orientation": self.orientation,
            "box_source": self.box_source,
            "words": [word.to_dict() for word in self.words],
            "kind": self.kind,
        }
        if self.conf is not None:
            out["conf"] = self.conf
        if self.injection_after is not None:
            out["injection_after"] = self.injection_after
        return out


@dataclass(frozen=True)
class Document:
    """The Document artefact (stages 5 and 6): the document's pages, its
    writing line by line, and its state.

    `pages` and the boundary evidence the grouping scored (`greeting`,
    `signoff`) are what opened the document; `lines` is its writing, empty
    until the transcription stage fills it; `status` is the draft state on a
    draft entry, and the reviewer's decision once the gate has run.
    """

    pages: list[str]
    greeting: str | None = None
    signoff: str | None = None
    status: DocumentStatus = DOCUMENT_DRAFT
    lines: list[DocumentLine] = field(default_factory=list)
    # the confirmation's own keys, when this document came in as one: the
    # registry's boundary entry records the payload it was confirmed by
    # (batch_id, doc_index, text, confirmed_at), so the record carries them
    # and writes them back only when they were there
    batch_id: str | None = None
    doc_index: int | None = None
    text: str | None = None
    confirmed_at: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Document:
        """The document an artefact record describes — a registry boundary
        entry reads as its draft state until the gate has decided otherwise,
        and a confirmation payload carries its own keys through."""
        status = str(raw.get("status", DOCUMENT_DRAFT))
        if status not in DOCUMENT_STATUSES:
            raise ValueError(f"document status {status!r} is not one of {list(DOCUMENT_STATUSES)}")
        doc_index = raw.get("doc_index")
        return cls(
            pages=[str(page) for page in raw.get("pages") or []],
            greeting=raw.get("greeting"),
            signoff=raw.get("signoff"),
            status=status,  # type: ignore[arg-type]  # validated against the vocabulary above
            lines=[DocumentLine.from_dict(line) for line in raw.get("lines") or []],
            batch_id=raw.get("batch_id"),
            doc_index=int(doc_index) if doc_index is not None else None,
            text=raw.get("text"),
            confirmed_at=raw.get("confirmed_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        """The document as its artefact record — the keys it does not carry
        (a draft's lines, a confirmation's own keys) are left out."""
        out: dict[str, Any] = {
            "pages": list(self.pages),
            "greeting": self.greeting,
            "signoff": self.signoff,
            "status": self.status,
        }
        if self.lines:
            out["lines"] = [line.to_dict() for line in self.lines]
        for key, value in (
            ("batch_id", self.batch_id),
            ("doc_index", self.doc_index),
            ("text", self.text),
            ("confirmed_at", self.confirmed_at),
        ):
            if value is not None:
                out[key] = value
        return out
