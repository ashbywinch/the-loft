"""The archive's one server — FastAPI (houses parity).

Serves the app (no-cache) and the contribution API. The move from the
hand-rolled http.server handler was forced by the auth bug class it kept
breeding: FastAPI decodes query parameters (the percent-encoded auth code),
parses cookies and JSON bodies, and issues redirects — every one of those
was hand-reimplemented wrong at least once.

The archive's data is the private layer (user): /data/* 401s
without a signed-in session; the app shell stays public so the gate loads.
The capture API (assess/save/delete) requires the session and mints the
narrator from it — never from a client-claimed name.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import socket
import subprocess
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from document.document import Document
from document.row_adjustments import RowAdjustments
from document.stages import PageStatus
from pipeline.api import auth
from pipeline.api.approval import ApprovalContext, DocumentFacts, approve_page
from pipeline.api.assess_request import AssessRequest
from pipeline.api.batch_drafts_answer import BatchDraftsAnswer
from pipeline.api.confirmation_answer import ConfirmationAnswer
from pipeline.api.confirmation_request import ConfirmationRequest
from pipeline.api.delete_request import DeleteRequest
from pipeline.api.device_poll_request import DevicePollRequest
from pipeline.api.error_answer import ErrorAnswer
from pipeline.api.health_answer import HealthAnswer
from pipeline.api.identify_answer import IdentifyAnswer
from pipeline.api.identify_decide_answer import IdentifyDecideAnswer, receipt
from pipeline.api.identify_decide_request import IdentifyDecideRequest
from pipeline.api.narrator import Narrator
from pipeline.api.page_processing_answer import PageProcessingAnswer
from pipeline.api.received_request import ReceivedRequest
from pipeline.api.review_decide_answer import ReviewDecideAnswer
from pipeline.api.review_decide_request import ReviewDecideRequest
from pipeline.api.review_item import ReviewItem
from pipeline.api.review_message_request import ReviewMessageRequest
from pipeline.api.review_start_answer import ReviewStartAnswer
from pipeline.api.review_start_request import ReviewStartRequest
from pipeline.api.review_text_answer import ReviewTextAnswer
from pipeline.api.review_text_request import ReviewTextRequest
from pipeline.api.rotate_page_request import RotatePageRequest
from pipeline.api.row_adjustments_answer import RowAdjustmentsAnswer
from pipeline.api.save_answer import SaveAnswer
from pipeline.api.save_request import SaveRequest
from pipeline.api.session_user import SessionUser
from pipeline.api.sync import (
    BATCH_ID,
    BatchReadings,
    Outbox,
    apply_row_adjustments,
    demote_stale_jobs,
    document_readiness,
    draft_payloads,
    identify_document,
    page_job_state,
    pages_pending,
    record_confirmation,
    reprocess_page_transcription,
    rotate_page,
    safe_page_name,
    set_page_job,
)
from pipeline.api.text_gzip import TextGZipMiddleware
from pipeline.artefacts import BatchArtefacts
from pipeline.identify import IdentificationError
from pipeline.model.ai_client import AIClient
from pipeline.registry import RegistryError, list_batches, load_batch
from pipeline.rows.rows import Rows
from tools import memory, review
from tools.archive import Archive, ArchiveError
from tools.decision_basis import DecisionBasis
from tools.loft_paths import LoftPaths
from tools.memory import ElicitationError, Knowledge
from tools.records import Item, Person, Place, ReviewContext, ReviewDecision, split_content
from tools.store import FileStore

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 1_000_000

TRANSCRIPTION_PREFIX_BYTES = 4096  # the first-chunk transcription read — enough to spot a mention, never the whole file


def _atomic_write(path: Path, data: Any) -> None:
    """Replace a derived file atomically (temp + rename) — never half-written.
    The projection's write path; a reader in 2060 must not meet a torn file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


@dataclass(frozen=True)
class ServerConfig:
    """The server's construction dependencies — the store, the model client,
    and the directories the app binds. The group travels together into
    build_app, create_server, and Server (docs/coding-standards.md: a group
    that travels together is a type)."""

    store: FileStore
    data_dir: Path
    client: AIClient | None
    app_dir: Path
    work_dir: Path | None = None
    outbox: Outbox | None = None
    registry_dir: Path | None = None


# The route closures ARE the FastAPI registration idiom — DI'd deps are
# lucidlint: ignore closures explicit params, not hidden state
def build_app(
    config: ServerConfig,
    _env: Mapping[str, str] | None = None,
    _reprocess: Callable[[str, str], None] | None = None,
) -> FastAPI:
    """The FastAPI app with the store/client/dirs bound (DI for tests).
    ``_env`` overrides the process environment for the build-time checks
    (the session secret); None reads os.environ."""
    if not auth.session_secret(_env):
        # an empty signing key means forgeable sessions — and the sync write
        # seam rides the session: refuse to start
        raise RuntimeError("THE_LOFT_SESSION_SECRET is not set — refusing to start with forgeable sessions")
    archive = Archive(config.store)
    client = config.client
    data_dir = Path(config.data_dir)
    app_dir = Path(config.app_dir)
    work_dir = Path(config.work_dir) if config.work_dir else LoftPaths.WORK_DIR
    registry_dir = Path(config.registry_dir) if config.registry_dir else LoftPaths.REGISTRY_DIR
    outbox = config.outbox if config.outbox is not None else Outbox(LoftPaths.WORK_DIR.parent / "sync-outbox")

    app = FastAPI(title="The Loft", docs_url=None, redoc_url=None)
    # The phone pays for every byte of the projection, the module graph and
    # the map; compress the text responses (the archive's images are already
    # compressed). The app shell and data are still revalidated by ETag.
    app.add_middleware(TextGZipMiddleware, minimum_size=1024)

    def session_user(request: Request) -> SessionUser | None:
        return auth.session_user_from_cookie(request.cookies.get(auth.GoogleOAuth.COOKIE_NAME))

    def narrator(request: Request) -> Narrator | None:
        """The signed-in narrator — the verified session's person. The
        capture API never trusts a client-claimed name."""
        session = session_user(request)
        if not session:
            return None
        person_id = auth.person_for_email(archive, session.email)
        people = archive.get_identity("people") if person_id else None
        person = next((p for p in people.people if p.id == person_id), None) if people else None
        name = person.name if person else session.name
        return Narrator(email=session.email, name=name, person=person_id, who=name)

    def knowledge() -> Knowledge:
        return Knowledge.from_projection(
            people=_read_projection(filename="people.json", key="people"),
            places=_read_projection(filename="places.json", key="places"),
            themes=_read_projection(filename="themes.json", key="themes"),
            items=_read_projection(filename="index.json", key="items"),
        )

    def _read_projection(filename: str, key: str) -> list[dict[str, Any]]:
        path = data_dir / filename
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8")).get(key, [])

    def _projection_document(filename: str) -> dict[str, Any]:
        path = data_dir / filename
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def existing_ids() -> set[str]:
        ids = {it["id"] for it in _read_projection(filename="index.json", key="items")}
        ids |= set(archive.item_ids()) | archive.proposed_ids()
        return ids

    # -- auth --------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return HealthAnswer(ai=client is not None).to_dict()

    @app.get("/api/auth/login")
    def login() -> dict[str, Any]:
        return auth.login_url().to_dict()

    @app.get("/api/auth/me")
    def me(request: Request) -> dict[str, Any]:
        session = session_user(request)
        logger.info("auth: /me saw %s", "a session" if session else "no session")
        return auth.me_payload(archive, session).to_dict()

    @app.get("/api/bootstrap")
    def bootstrap(request: Request) -> Any:
        """The app's one boot read: identity + the projection files.

        The home used to pay one auth request and five data requests; the
        round trips, not the server work, were most of its load. One
        auth-gated response removes five of them. The transcriptions are
        not here: only Item/Search/Identify fetch that file.
        """
        session = session_user(request)
        if session is None:
            return JSONResponse(ErrorAnswer("sign in to read the archive").to_dict(), status_code=401)
        if not (data_dir / "index.json").is_file():
            # A missing projection is an operator error, not an empty archive:
            # the home must say so instead of "0 items".
            return JSONResponse(
                {"error": "the archive projection is not published", "detail": "run loft publish"},
                status_code=503,
            )
        return {
            "me": auth.me_payload(archive, session).to_dict(),
            "index": _projection_document("index.json"),
            "people": _projection_document("people.json"),
            "places": _projection_document("places.json"),
            "themes": _projection_document("themes.json"),
            "imports": _projection_document("imports.json"),
        }

    @app.post("/api/auth/logout")
    def logout() -> JSONResponse:
        response = JSONResponse({"ok": True})
        response.delete_cookie(auth.GoogleOAuth.COOKIE_NAME, path="/")
        return response

    @app.get("/api/auth/callback")
    def callback(code: str = "", state: str = "", error: str = "") -> RedirectResponse:
        """Google's OAuth callback — FastAPI decodes the percent-encoded
        query."""
        if error:
            return RedirectResponse(auth.callback_error_url(f"google:{error}"))
        user = auth.exchange_code(code, state) if code and state else None
        if user is None:
            return RedirectResponse(auth.callback_error_url("failed"))
        response = RedirectResponse(f"{auth.public_url()}/")
        _set_session_cookie(response, user)
        return response

    @app.get("/api/auth/device/start")
    def device_start() -> dict[str, Any]:
        return auth.start_device_grant().to_dict()

    @app.post("/api/auth/device/poll")
    def device_poll(body: Mapping[str, Any]) -> dict[str, Any]:
        """The device grant's poll (headless tools; the browser uses the web
        flow). The cookie rides the complete NAVIGATION, never this response
        — the phone's network rejects fetch-carried cookies."""
        answer = auth.poll_device_grant(DevicePollRequest.from_dict(body).state)
        if answer.status == "ok":
            return {"ok": True, "complete": True}
        logger.info("auth: device poll -> %s", answer.status)
        return {"ok": False, **answer.to_dict()}

    @app.get("/api/auth/device/complete")
    def device_complete(state: str = "") -> RedirectResponse:
        minted = auth.minted_session(state)
        if minted is None:
            return RedirectResponse(f"{auth.public_url()}/?auth_error=expired")
        response = RedirectResponse(f"{auth.public_url()}/")
        _set_session_cookie(response, minted)
        logger.info("auth: device complete — session cookie issued for %s", minted.email)
        return response

    def _set_session_cookie(response: JSONResponse | RedirectResponse, user: SessionUser) -> None:
        cookie = auth._make_session_cookie(user)
        response.set_cookie(
            auth.GoogleOAuth.COOKIE_NAME,
            cookie,
            max_age=int(auth.SESSION_MAX_AGE.total_seconds()),
            httponly=True,
            samesite="lax",
            path="/",
        )

    # -- the capture API (session required, narrator from the session) ------

    @app.post("/api/assess", response_model=None)
    def assess(request: Request, body: Mapping[str, Any]) -> dict[str, Any] | JSONResponse:
        mine = narrator(request)
        # the 401 auth gate IS the absent case — a stand-in would hide the boundary
        if mine is None:
            return JSONResponse(ErrorAnswer("sign in to tell a story").to_dict(), status_code=401)
        if client is None:
            return JSONResponse(ErrorAnswer("the AI isn't configured on this server").to_dict(), status_code=503)
        fields = AssessRequest.from_dict(body)
        assessment = memory.assess(
            client,
            anchor=fields.anchor,
            who=mine.who,
            account=fields.account,
            knowledge=knowledge(),
        )
        return {"ok": True, **assessment.to_dict()}

    @app.post("/api/save", response_model=None)
    def save(request: Request, body: Mapping[str, Any]) -> dict[str, Any] | JSONResponse:
        mine = narrator(request)
        if mine is None:
            return JSONResponse(ErrorAnswer("sign in to tell a story").to_dict(), status_code=401)
        fields = SaveRequest.from_dict(body)
        # typed answers to date questions arrive as pending facts (value
        # null) — the model asserts their value/precision, the library
        # validates; offline, the pending fact stays for a person to resolve
        facts = memory.resolve_pending_facts(client, fields.facts)
        built = memory.build_story(
            request=memory.StoryRequest(
                anchor=fields.anchor,
                who=mine.who,  # the verified session, never the client
                title=fields.title,
                account=fields.account,
                extractions=fields.extractions,
                facts=facts,
                status=fields.status,
                story_id=fields.story_id,
                chat=fields.chat,
            ),
            knowledge=knowledge(),
            existing_ids=existing_ids(),
        )
        # drafts are committed during dev (user): the archive
        # store holds the canonical sidecar, and the projection is refreshed
        # so the story renders in the app — idempotent, atomic. All archive
        # writes go through the archive library (docs/CONTRIBUTIONS.md). The
        # story text is primary content: it becomes a content file the
        # sidecar references, never a sidecar JSON field (archive-durability.md).
        split = split_content(built.story)
        archive.save_item(split.sidecar, content=split.content)
        for person in built.new_people:
            archive.propose_person(person)
        for place in built.new_places:
            archive.propose_place(place)
        _refresh_projection(built.story, built.new_people, built.new_places)
        return SaveAnswer(
            id=built.story.id,
            story=built.story.to_dict(),
            people=[person.to_dict() for person in built.new_people],
            places=[place.to_dict() for place in built.new_places],
        ).to_dict()

    @app.post("/api/delete", response_model=None)
    def delete(request: Request, body: Mapping[str, Any]) -> dict[str, Any] | JSONResponse:
        """Abandon: the draft is superseded with a tombstone — append-only,
        the files stay, the newest version says deleted (user)."""
        mine = narrator(request)
        if mine is None:
            return JSONResponse(ErrorAnswer("sign in to tell a story").to_dict(), status_code=401)
        try:
            fields = DeleteRequest.from_dict(body)
        except ValueError as exc:
            return JSONResponse(ErrorAnswer(str(exc)).to_dict(), status_code=400)
        archive.delete_item(fields.id, fields.reason)
        _drop_from_projection(fields.id)
        return {"ok": True}

    @app.post("/api/review/start", response_model=None)
    def review_start(request: Request, body: Mapping[str, Any]) -> dict[str, Any] | JSONResponse:
        """Begin a new walk of the review — the sessions' storage is
        attempt-separated: a fresh attempt starts only when
        the last is empty or finished, so a mid-walk re-render continues
        the same walk and the diagnosis never mixes attempts."""
        mine = narrator(request)
        if mine is None:
            return JSONResponse(ErrorAnswer("sign in to review the import").to_dict(), status_code=401)
        try:
            fields = ReviewStartRequest.from_dict(body)
        except ValueError as exc:
            return JSONResponse(ErrorAnswer(str(exc)).to_dict(), status_code=400)
        session_id = fields.session_id
        try:
            archive.start_review_attempt(session_id)
        except ArchiveError as e:
            return JSONResponse(ErrorAnswer(str(e)).to_dict(), status_code=404)
        # the lines already recorded in the current attempt — the app
        # records its rendered opening/claim only when they're new, so a
        # mid-walk re-render never duplicates the transcript
        session_record = archive.get_review_session(session_id)
        attempt = session_record.current_attempt() if session_record else None
        messages = attempt.messages if attempt else ()
        return ReviewStartAnswer(messages=[m.text for m in messages]).to_dict()

    @app.post("/api/review/message", response_model=None)
    def review_message(request: Request, body: Mapping[str, Any]) -> dict[str, Any] | JSONResponse:
        """Record one of the app's own rendered lines (the opening, the
        claim) so the transcript is exactly what the family saw (user:
        "when you load a given transcript, you see exactly what I saw")."""
        mine = narrator(request)
        if mine is None:
            return JSONResponse(ErrorAnswer("sign in to review the import").to_dict(), status_code=401)
        try:
            fields = ReviewMessageRequest.from_dict(body)
        except ValueError as exc:
            return JSONResponse(ErrorAnswer(str(exc)).to_dict(), status_code=400)
        try:
            archive.record_review_message(
                fields.session_id, fields.role, fields.text, datetime.now(UTC).date().isoformat()
            )
        except ArchiveError as e:
            return JSONResponse(ErrorAnswer(str(e)).to_dict(), status_code=404)
        return {"ok": True}

    @app.post("/api/review/decide", response_model=None)
    def review_decide(request: Request, body: Mapping[str, Any]) -> dict[str, Any] | JSONResponse:
        """The import review (user): one decision per proposed
        link — attested (→ confirmed, the reviewer's own verified word),
        estimated (→ estimated with the recorded basis {text, by, when}),
        pending (→ the import's guess stays proposed), delete (→ gone).
        The decision vocabulary is NOT the status vocabulary: "confirm" is
        a status, never an action."""
        mine = narrator(request)
        if mine is None:
            return JSONResponse(ErrorAnswer("sign in to review the import").to_dict(), status_code=401)
        try:
            fields = ReviewDecideRequest.from_dict(body)
        except ValueError as exc:
            return JSONResponse(ErrorAnswer(str(exc)).to_dict(), status_code=400)
        session_id = fields.session_id
        person_id = fields.person_id
        decision = fields.decision
        basis = fields.basis
        # the session must exist BEFORE anything mutates — a stale session id
        # must not change the archive and then fail
        if archive.get_review_session(session_id) is None:
            return JSONResponse(ErrorAnswer(f"no import session {session_id}").to_dict(), status_code=404)
        # the determination is always applied and recorded: the record's state is
        # whatever the latest one says, and the append-only chain keeps the
        # earlier ones — there is no staleness to detect (2026-10-21, user). The
        # name is read before the mutation because a delete answers with the gone
        # marker, which carries no name.
        people_table = archive.get_identity("people")
        pre_person = people_table.record(person_id) if people_table else None
        person_name = pre_person.name if pre_person else person_id
        try:
            record = archive.resolve_person(person_id, decision, basis)
        except ValueError as e:
            return JSONResponse(ErrorAnswer(str(e)).to_dict(), status_code=400)
        person_payload = record.to_dict() if record is not None else None
        # the review record — the decision and the confirmation message the
        # family saw, both persisted (the transcript is the messages)
        when = datetime.now(UTC).date().isoformat()
        queue = archive.review_queue()
        archive.record_review_decision(
            session_id,
            ReviewDecision(
                person_id=person_id,
                decision=decision,
                when=when,
                basis=basis,
                last=not queue.pending,
            ),
        )
        message = review.confirmation_message(person_name, decision, DecisionBasis.from_dict(basis) if basis else None)
        archive.record_review_message(session_id, "assistant", message, when)
        archive.refresh_import_status()  # the last pending person completes the session
        archive.publish(data_dir)
        # the accurate remaining count — the server's post-decision truth
        # (the client's projection is stale until reload; the count must
        # always be right, user)
        return ReviewDecideAnswer(person=person_payload, message=message, pending=len(queue.pending)).to_dict()

    @app.post("/api/review/text", response_model=None)
    def review_text(request: Request, body: Mapping[str, Any]) -> dict[str, Any] | JSONResponse:
        """The reviewer's free text vs the exact claim under review: the
        relevance check — on-topic (the answer addresses
        the proposed record and is recorded verbatim) or off-topic (the
        chat names the mismatch and steers back). The model never derives
        relationships — the reviewer's words are the record or nothing is."""
        mine = narrator(request)
        if mine is None:
            return JSONResponse(ErrorAnswer("sign in to review the import").to_dict(), status_code=401)
        try:
            fields = ReviewTextRequest.from_dict(body)
        except ValueError as exc:
            return JSONResponse(ErrorAnswer(str(exc)).to_dict(), status_code=400)
        session_id = fields.session_id
        person_id = fields.person_id
        text = fields.text
        # the session must exist BEFORE the costly model call — a stale id
        # must not run the investigation and then 500 in the recording
        if archive.get_review_session(session_id) is None:
            return JSONResponse(ErrorAnswer(f"no import session {session_id}").to_dict(), status_code=404)
        people = archive.get_identity("people")
        all_people = people.people if people else ()
        person = next((p for p in all_people if p.id == person_id), None)
        if person is None:
            return JSONResponse(ErrorAnswer(f"no person {person_id}").to_dict(), status_code=404)
        if client is None:
            return JSONResponse(ErrorAnswer("the AI isn't configured on this server").to_dict(), status_code=503)
        try:
            # the model sees the whole conversation — its own reasoning and
            # speech, verbatim — so a message that re-answers an earlier
            # question is recognised (user). The history is the
            # conversation BEFORE this line: the investigation appends the
            # line itself, so a history that already held it would double
            # the latest message for the model
            session_record = archive.get_review_session(session_id)
            current_attempt = session_record.current_attempt() if session_record else None
            history = current_attempt.messages if current_attempt else ()
            # the family's line joins the transcript the moment it arrives —
            # the model call must not gate the record (R7/R8: the words are
            # never lost, and the transcript equals what the family saw)
            when = datetime.now(UTC).date().isoformat()
            archive.record_review_message(session_id, "user", text, when)
            # the investigation needs the attested facts the Knowledge
            # conversion drops — the raw people (deaths, relations), the
            # recorded items' texts, and the family edges — typed as the
            # ReviewContext. The projection carries the
            # VERBATIM transcription when the item has one (the document
            # the family sees in the claim and the item page) — the
            # sidecar's story is the archival summary, a different text. The
            # people involvement is the structured match the tools need — the
            # prose never carries ids. The FULL text is read only for the
            # shortlist that can attest this person: the metadata pass (one
            # sidecar per item, no transcription reads) filters first — at
            # the 10,000-item design target, reading every transcription
            # per chat message would be thousands of disk reads. The
            # metadata pass itself is still a full-archive
            # sidecar scan per message — O(N) disk reads at that target;
            # deferred (user): fine at the current family-
            # archive scale (~100 items), revisit with a people→items
            # mention index before the 10,000-item target is real. The
            # name needles are lowered once and matched against lowered
            # text — OCR and captured text differ in case, and a
            # differently-cased mention must not hide the attesting
            # document
            needles = tuple(n.lower() for n in (person.name, person.name.split()[0]))
            items: list[ReviewItem] = []
            for item_id in archive.item_ids():
                item = archive.get_item(item_id)
                if item is None or item.status != "catalogued":
                    continue
                involved = person_id in [ref.id for ref in item.people_refs]
                story = str(item.raw.get("story") or "").strip()
                if involved or any(n in story.lower() for n in needles):
                    transcription = archive.read_content(item_id, "transcription.txt") or ""
                    item_text = transcription or story
                else:
                    # the metadata pass says "maybe" — settle with a bounded
                    # FIRST-CHUNK transcription read (4 KiB, never the whole
                    # file) before skipping: an item whose ONLY mention of
                    # the person lives in the verbatim text (a draft with no
                    # people refs yet) must still reach the model — the
                    # transcription is the evidence, never the summary
                    transcription = (
                        archive.read_content_prefix(item_id, "transcription.txt", TRANSCRIPTION_PREFIX_BYTES) or ""
                    )
                    if not any(n in transcription.lower() for n in needles):
                        continue
                    item_text = transcription
                if item_text:
                    items.append(
                        ReviewItem(
                            id=item_id,
                            title=item.title,
                            story=item_text,
                            # Rule L: a draft transcription is machine-read
                            # and unverified — its sentences are never the
                            # document's own words; the model must know
                            # which texts are drafts so it never quotes
                            # one as verified evidence
                            transcription_status=item.raw.get("transcription_status"),
                            people=[ref.id for ref in item.people_refs],
                        )
                    )
            result = review.investigate(
                client,
                text=text,
                person=person,
                who=mine.who,
                facts=ReviewContext(
                    people=all_people,
                    items=tuple(item.to_dict() for item in items),
                    relationships=tuple(r.to_dict() for r in people.relationships) if people else (),
                ),
                history=history,
            )
        except ElicitationError as e:
            return JSONResponse(ErrorAnswer(str(e)).to_dict(), status_code=422)
        # the transcript is the MESSAGES — what the family saw:
        # the user's words (recorded BEFORE the call, so an outage never
        # loses them) and the assistant's rendered
        # words, built here, shown verbatim by the app, and stored verbatim.
        # The assistant's line also carries its THINKING — the model's raw
        # verdict, verbatim — which goes back to the model on later calls.
        # The note never reaches the user (it had been leaking into the
        # steer's parens).
        contradiction = result.contradiction.found == "true"
        if contradiction:
            # the contradiction surfaces before anything else — an off-topic
            # verdict that also flags one must not let the steer hide it
            message = f"That doesn't match the records — {result.contradiction.detail}. Which is right?"
        elif result.relevant == "false":
            message = review.steer_message(person, result.note)
        else:
            # never persist an empty assistant line the family never saw
            message = review.assistant_message(result, person).strip() or "Thank you — that's noted."
        archive.record_review_message(
            session_id,
            "assistant",
            message,
            when,
            thinking=json.dumps([step.to_dict() for step in result.trace], ensure_ascii=False),
        )
        # the response carries ONLY what the UI consumes — the model's raw
        # output, its tool trace, and the prompt texts are the model's
        # internals, never the family's (R7).
        return ReviewTextAnswer(
            message=message,
            relevant=result.relevant,
            contradiction=result.contradiction.to_dict(),
            confidence=result.confidence,
            note=result.note,
            findings=[finding.to_dict() for finding in result.findings],
            question=result.question,
        ).to_dict()

    def _drop_from_projection(item_id: str) -> None:
        index_path = data_dir / "index.json"
        if not index_path.exists():
            return
        index = json.loads(index_path.read_text(encoding="utf-8"))
        before = len(index.get("items", []))
        index["items"] = [it for it in index.get("items", []) if it["id"] != item_id]
        if len(index["items"]) != before:
            _atomic_write(index_path, index)

    def _refresh_projection(
        story: Item,
        new_people: tuple[Person, ...],
        new_places: tuple[Place, ...],
    ) -> None:
        """The derived cache (app/data): merge the story and any proposed
        records. Idempotent by id — re-running a save never duplicates."""
        index_path = data_dir / "index.json"
        if index_path.exists():
            index = json.loads(index_path.read_text(encoding="utf-8"))
            items = [it for it in index.get("items", []) if it["id"] != story.id]
            items.append(story.to_dict())
            items.sort(key=lambda it: it["date"])
            index["items"] = items
            _atomic_write(index_path, index)
        _merge_records(filename="people.json", key="people", records=new_people)
        _merge_records(filename="places.json", key="places", records=new_places)

    def _merge_records(filename: str, key: str, records: tuple[Person | Place, ...]) -> None:
        if not records:
            return
        path = data_dir / filename
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {key: []}
        known = {r["id"] for r in data.get(key, [])}
        data[key] = data.get(key, []) + [r.to_dict() for r in records if r.id not in known]
        _atomic_write(path, data)

    # -- the static app + the data gate ------------------------------------

    @app.middleware("http")
    async def log_shell_request(request: Request, call_next: Any) -> Any:
        # The shell's client identity is the first thing to know when a phone
        # shows a blank page; the access log alone carries no User-Agent.
        if request.url.path == "/":
            logger.info(
                "shell: host=%r ua=%r platform=%r",
                request.headers.get("host"),
                request.headers.get("user-agent"),
                request.headers.get("sec-ch-ua-platform"),
            )
        return await call_next(request)

    @app.middleware("http")
    async def app_shell_no_cache(request: Request, call_next: Any) -> Any:
        # The app code must never be heuristically cached: StaticFiles sends
        # only ETag/Last-Modified, so a browser's heuristic can keep serving
        # a stale shell. The shell + code revalidate every
        # load; the data assets (the scans) keep the default caching.
        response = await call_next(request)
        if not request.url.path.startswith("/data/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.middleware("http")
    async def origin_guard(request: Request, call_next: Any) -> Any:
        # CSRF guard for the write APIs: a page on another origin must not
        # POST to the household server. The app's own fetches carry the
        # server's origin (or none, for curl); the auth endpoints are
        # exempt (the flow redirects cross-origin).
        if request.method == "POST" and not request.url.path.startswith("/api/auth/"):
            origin = request.headers.get("origin")
            if origin:
                host = request.headers.get("host", "")
                if origin.rstrip("/") not in (f"http://{host}", f"https://{host}"):
                    return JSONResponse({"ok": False, "error": "cross-origin write rejected"}, status_code=403)
        return await call_next(request)

    @app.middleware("http")
    async def gate_data(request: Request, call_next: Any) -> Any:
        # the archive's data is the private layer — a session is required
        # to read it (user: content gated behind sign-in). The
        # app shell stays public so the gate can load.
        if request.url.path.startswith("/data/"):
            session = auth.session_user_from_cookie(request.cookies.get(auth.GoogleOAuth.COOKIE_NAME))
            if session is None:
                return JSONResponse({"ok": False, "error": "sign in to read the archive"}, status_code=401)
        return await call_next(request)

    # -- sync (TECHSPEC/04 §17.5: the backend owns the write seam; the
    # frontend proposes, the backend records; the outbox is the catch-up) --

    @app.get("/api/sync/batches")
    def sync_batches(request: Request) -> Any:
        """Every adopted batch, newest first — the review surface's batch
        list (the batch label + status ride the registry record), each with
        the pages waiting in the "Check the rows" queue."""
        if session_user(request) is None:
            return JSONResponse(ErrorAnswer("sign in to read the batches").to_dict(), status_code=401)
        try:
            batches: list[dict[str, Any]] = []
            for batch in list_batches(registry_dir):
                record = batch.to_dict()
                readings = BatchReadings(work_dir, str(record["batch_id"]))
                record["pages_pending"] = pages_pending(readings, list(record.get("pages") or {}))
                ready, partial = document_readiness(
                    [list(boundary.get("pages") or []) for boundary in record.get("boundaries") or []], readings
                )
                record["documents_ready"] = ready
                record["documents_partial"] = partial
                batches.append(record)
            return {"batches": batches}
        except RegistryError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/api/sync/batch/{batch_id}/drafts")
    def sync_drafts(batch_id: str, request: Request) -> Any:
        """The machine drafts the review surface reads (guesses + boundaries
        + layout, docs/TECHSPEC/03-import-and-pipeline.md §16.16), with the registry's per-document
        review status merged in (the registry is the status' home — the
        guess stage's boundaries.json never changes after review).

        With ``doc`` + ``page`` the answer is the one page the row screen
        opened: the document's maps are cut to that page. The row screen
        needs one page, not every document and page in the batch."""
        if session_user(request) is None:
            return JSONResponse(ErrorAnswer("sign in to read the drafts").to_dict(), status_code=401)
        try:
            record = load_batch(batch_id, registry_dir)
            by_pages = {tuple(b.pages): b.status or Document.DRAFT for b in (record.boundaries or [])}
            # The transcription review shows only documents with a text
            # page, and only their TEXT pages (2026-08-17, user: "we just
            # don't need to show users any of the photos when they're
            # checking transcription"). A photo-only item has nothing to
            # transcribe — it belongs to the people/places identification
            # flow, which reads the same structure with no filter (the
            # photo docs stay "review" until that flow claims them). The
            # picture side of a two-sided item stays in the structure; the
            # review just does not page through it.
            documents: list[dict[str, Any]] = []
            for document in draft_payloads(batch_id, work_dir):
                texts = document.get("texts") or {}
                if not texts:
                    continue
                text_pages = [p for p in document.get("pages", []) if p in texts]
                readings = BatchReadings(work_dir, batch_id)
                # the transcription stage runs on checked rows: a page still
                # carrying draft rows is not reviewable words yet, and a
                # strip-era page has no reading to check at all
                # a printed page is ready when its direct read exists: it has
                # no rows to check: its stage-5 text exists
                pages_ready = [
                    p
                    for p in text_pages
                    if readings.page_status(p) in (PageStatus.ROWS_ADJUSTED, PageStatus.TRANSCRIPTS_PROPOSED)
                ]
                documents.append(
                    {
                        **document,
                        "pages": text_pages,
                        "status": by_pages.get(tuple(document.get("pages", [])), Document.DRAFT),
                        "pages_ready": pages_ready,
                        "ready": bool(text_pages) and len(pages_ready) == len(text_pages),
                    }
                )
            raw_doc = request.query_params.get("doc")
            raw_page = request.query_params.get("page")
            if raw_doc is not None or raw_page is not None:
                if raw_doc is None or raw_page is None:
                    return JSONResponse({"error": "doc and page must be provided together"}, status_code=400)
                try:
                    doc_number = int(raw_doc)
                    page_number = int(raw_page)
                except ValueError:
                    return JSONResponse({"error": "doc and page must be integers"}, status_code=400)
                if doc_number < 0 or doc_number >= len(documents):
                    return JSONResponse({"error": "no such document"}, status_code=400)
                chosen = documents[doc_number]
                document_pages: list[Any] = list(chosen.get("pages") or [])
                if page_number < 0 or page_number >= len(document_pages):
                    return JSONResponse({"error": "no such page"}, status_code=400)
                page_name = document_pages[page_number]
                checked_pages = sorted((chosen.get("adjusted_rows") or {}).keys())
                for key in ("texts", "layouts", "orientations", "row_adjustments", "adjusted_rows", "tints"):
                    value = chosen.get(key)
                    if isinstance(value, dict):
                        chosen[key] = {page_name: value[page_name]} if page_name in value else {}
                chosen["checked_pages"] = checked_pages
                documents = [chosen]
            return BatchDraftsAnswer(
                batch_id=batch_id,
                label=record.label,
                documents=documents,
                processing=page_job_state(batch_id, work_dir),
            ).to_dict()
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except RegistryError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/api/sync/batch/{batch_id}/page/{page}")
    def sync_page(batch_id: str, page: str, request: Request) -> Any:
        """The oriented page image the review surface renders (auth-gated
        like the drafts; batch id and page name become path segments —
        validated by the sync contract's guard)."""
        if session_user(request) is None:
            return JSONResponse(ErrorAnswer("sign in to read the pages").to_dict(), status_code=401)
        if not BATCH_ID.match(batch_id) or not safe_page_name(page):
            return JSONResponse({"error": "invalid batch or page name"}, status_code=400)
        artefacts = BatchArtefacts(work_dir, batch_id)
        source = artefacts.oriented(page)
        if not source.is_file():
            # a photo/drawing page skips orientation entirely (the grouping
            # scorer puts the postcard's picture side into its document —
            # the review surface must still see the image)
            record = load_batch(batch_id, registry_dir)
            source = record.path / page
            if not source.is_file():
                return JSONResponse({"error": "no such page"}, status_code=404)
        try:
            image = artefacts.view_image(page, source)
        # a corrupt or unreadable source still has to show; the log names
        # the page and the source itself is the visible fallback
        # lucidlint: ignore swallow the source image is the visible fallback
        except (OSError, ValueError):
            logger.exception("view image failed for %s/%s", batch_id, page)
            image = source
        return FileResponse(image)

    def _reprocess_page(batch_id: str, page: str) -> None:
        """Re-run a page's transcription in a background thread — the async
        half of the rotate and re-read routes (one way through the reprocess
        seam). The reprocess owns the page's job state itself: it clears it
        on success, marks it failed on error."""

        def _job() -> None:
            try:
                people = [
                    str(p["name"]) for p in _read_projection(filename="people.json", key="people") if p.get("name")
                ]
                places = [
                    str(p["name"]) for p in _read_projection(filename="places.json", key="places") if p.get("name")
                ]
                label = None
                with contextlib.suppress(RegistryError):
                    label = load_batch(batch_id, registry_dir).label
                reprocess_page_transcription(
                    batch_id,
                    page,
                    work_dir,
                    registry_dir=registry_dir,
                    people=people,
                    places=places,
                    label=label,
                )
            # The background thread's terminal handler — logger.exception
            # lucidlint: ignore swallow is the observable surface; the thread ends
            except Exception:
                logger.exception("reprocess failed for %s/%s", batch_id, page)

        threading.Thread(target=_job, daemon=True).start()

    @app.post("/api/sync/batch/{batch_id}/page/{page}/rotate")
    def sync_rotate_page(batch_id: str, page: str, request: Request, body: Mapping[str, Any] | None = None) -> Any:
        """The reviewer's orientation fix. The intent is the
        DESIRED cumulative rotation in quarter-turns — no image travels, the
        backend has it (the front and back end are different boxes). The
        fast rotation (image + box remap) applies synchronously; the slow
        re-transcription runs as the async job, the page marked
        "transcribing" in the drafts payload meanwhile — the surface greys
        the document with a note and the reviewer navigates on."""
        if session_user(request) is None:
            return JSONResponse(ErrorAnswer("sign in to fix pages").to_dict(), status_code=401)
        # 0 is a real intent: the reviewer's rotate-back to the ORIGINAL
        # orientation (the UI's % 4 range) — rejecting it defaulted to a
        # wrong +90 (bot review, 2026-08-16)
        quarters = RotatePageRequest.from_dict(body or {}).quarters
        try:
            rotated = rotate_page(batch_id, page, quarters, work_dir)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if not rotated:
            return PageProcessingAnswer(batch_id=batch_id, page=page, processing=False).to_dict()
        set_page_job(batch_id, page, "transcribing", work_dir)
        (_reprocess or _reprocess_page)(batch_id, page)
        return PageProcessingAnswer(batch_id=batch_id, page=page, processing=True).to_dict()

    @app.post("/api/sync/batch/{batch_id}/page/{page}/reread")
    def sync_reread_page(batch_id: str, page: str, request: Request) -> Any:
        """Retry a page's re-read after its last one failed (the reading
        model was unreachable): clear the failed state, mark transcribing,
        and re-run the reprocess over the CURRENT image. Orientation is
        untouched — this only re-runs OCR (2026-08-16, PRD VR10 AC14)."""
        if session_user(request) is None:
            return JSONResponse(ErrorAnswer("sign in to re-read pages").to_dict(), status_code=401)
        if not BATCH_ID.match(batch_id) or not safe_page_name(page):
            return JSONResponse({"error": "invalid batch or page name"}, status_code=400)
        set_page_job(batch_id, page, "transcribing", work_dir)
        (_reprocess or _reprocess_page)(batch_id, page)
        return PageProcessingAnswer(batch_id=batch_id, page=page, processing=True).to_dict()

    @app.post("/api/sync/batch/{batch_id}/page/{page}/row-adjustments")
    def sync_row_adjustments(batch_id: str, page: str, request: Request, body: Mapping[str, Any] | None = None) -> Any:
        """The reviewer's drawn row lines -> the page's corrected rows.

        The lines are the drawn indications (normalised polylines); the
        build (`tools/rows.py` rows.adjust) groups the page's PERSISTED
        words and the correction is written beside the reading (the lines
        and the rows they made), so a reopened page shows what the reviewer
        drew and what it produced. A page without persisted words (read
        before the read stage wrote them) is refused with the remedy —
        never a silent empty build."""
        if session_user(request) is None:
            return JSONResponse(ErrorAnswer("sign in to correct rows").to_dict(), status_code=401)
        if not BATCH_ID.match(batch_id) or not safe_page_name(page):
            return JSONResponse({"error": "invalid batch or page name"}, status_code=400)
        try:
            adjustments = RowAdjustments.from_dict(dict(body) if body else {})
            correction = apply_row_adjustments(batch_id, page, adjustments, work_dir, registry_dir=registry_dir)
        except (RegistryError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)  # client errors are 4xx, never 500
        return RowAdjustmentsAnswer(
            batch_id=batch_id,
            page=page,
            rows=Rows.to_dict(correction.rows)["rows"],
            violations=correction.violations,
            tints=correction.tints,
        ).to_dict()

    @app.post("/api/sync/approvals")
    def sync_approvals(payload: Mapping[str, Any], request: Request) -> Any:
        """The per-page approval: one page's text is agreed on its own; the
        document's item is minted as a draft from the approved pages and is
        catalogued when every text page is approved."""
        if session_user(request) is None:
            return JSONResponse(ErrorAnswer("sign in to approve pages").to_dict(), status_code=401)
        try:
            batch_id = str(payload["batch_id"])
            page = str(payload["page"])
            text = str(payload["text"])
            approval = approve_page(
                batch_id,
                page,
                text,
                context=ApprovalContext(archive, work_dir, registry_dir),
                facts=DocumentFacts(
                    title=str(payload.get("title", "")),
                    date=str(payload.get("date", "")),
                    date_precision=str(payload.get("date_precision", "")),
                    by=str(getattr(session_user(request), "email", "") or ""),
                ),
            )
        except (KeyError, TypeError, ValueError, RegistryError, ArchiveError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        archive.publish(data_dir)
        return {
            "batch_id": batch_id,
            "page": approval.page,
            "item_id": approval.item_id,
            "document_complete": approval.document_complete,
            "pages_approved": approval.pages_approved,
            "pages_total": approval.pages_total,
        }

    @app.post("/api/sync/confirmations")
    def sync_confirmations(payload: Mapping[str, Any], request: Request) -> Any:
        """The backend receiver: validate, record (the agreed document becomes
        its archive item; the registry records the review), re-publish the
        projection. The frontend never writes the archive."""
        if session_user(request) is None:
            return JSONResponse(ErrorAnswer("sign in to send confirmations").to_dict(), status_code=401)
        try:
            confirmation = ConfirmationRequest.from_dict(payload)
            item_id = record_confirmation(
                confirmation.batch_id,
                confirmation.doc_index,
                confirmation.boundary,
                confirmation.text,
                archive=archive,
                title=confirmation.title,
                date=confirmation.date,
                date_precision=confirmation.date_precision,
                registry_dir=registry_dir,
            )
        except (TypeError, ValueError, RegistryError, ArchiveError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)  # client errors are 4xx, never 500
        archive.publish(data_dir)
        return ConfirmationAnswer(
            batch_id=confirmation.batch_id, doc_index=confirmation.doc_index, item_id=item_id
        ).to_dict()

    # -- identification (stages 7-8) ---------------------------------------

    def _identification_pending(item: Item) -> int:
        """How many of the document's entities still wait on a decision — the
        proposed refs. A confirmed or guessed one is settled (left for later
        stays proposed: it still waits)."""
        return sum(1 for ref in item.people_refs + item.place_refs if ref.status == "proposed")

    def _identification_records(item: Item) -> tuple[tuple[Person, ...], tuple[Place, ...]]:
        """The records the document's refs name — the surface renders their
        names and the proposal's evidence beside each ref."""
        people_table = archive.get_identity("people")
        places_table = archive.get_identity("places")
        people: list[Person] = []
        places: list[Place] = []
        for ref in item.people_refs:
            person = people_table.record(ref.id) if people_table is not None else None
            if person is not None:
                people.append(person)
        for ref in item.place_refs:
            place = places_table.record(ref.id) if places_table is not None else None
            if place is not None:
                places.append(place)
        return tuple(people), tuple(places)

    def _identification_knowledge() -> Knowledge:
        """The pass resolves names against the ARCHIVE's tables, not the
        published projection: the projection is a cache, and a stale one
        would let the pass mint a second id for a record the archive holds."""
        people = archive.get_identity("people")
        places = archive.get_identity("places")
        return Knowledge(people=people.people if people else (), places=places.places if places else ())

    @app.post("/api/identify/document/{item_id}")
    def identify_item(item_id: str, request: Request) -> Any:
        """The stage-7 pass for one agreed document (once), then its stage-8
        state: the item's refs, the records they name, and the count still
        waiting. A document already read is never re-read — the whole point
        of the pass is that the review sees one reading, not a fresh draw
        each visit."""
        if session_user(request) is None:
            return JSONResponse(ErrorAnswer("sign in to identify the documents").to_dict(), status_code=401)
        item = archive.get_item(item_id)
        if item is None or item.type != "document":
            return JSONResponse(ErrorAnswer(f"no document {item_id}").to_dict(), status_code=404)
        if not item.identified:
            if client is None:
                return JSONResponse(
                    ErrorAnswer("the identification needs the AI — no model client is configured").to_dict(),
                    status_code=503,
                )
            try:
                identify_document(
                    item_id,
                    archive=archive,
                    client=client,
                    knowledge=_identification_knowledge(),
                )
            except IdentificationError as exc:
                return JSONResponse(ErrorAnswer(str(exc)).to_dict(), status_code=502)
            except ArchiveError as exc:
                return JSONResponse(ErrorAnswer(str(exc)).to_dict(), status_code=400)
            archive.publish(data_dir)
            item = archive.get_item(item_id) or item
        people, places = _identification_records(item)
        return IdentifyAnswer(item=item, people=people, places=places, pending=_identification_pending(item)).to_dict()

    @app.post("/api/identify/decide")
    def identify_decide(body: Mapping[str, Any], request: Request) -> Any:
        """One stage-8 determination: the mention on the document and the
        record in the identity table move together (the archive's seam), and
        the answer carries what remains."""
        if session_user(request) is None:
            return JSONResponse(ErrorAnswer("sign in to identify the documents").to_dict(), status_code=401)
        try:
            fields = IdentifyDecideRequest.from_dict(body)
        except (TypeError, ValueError) as exc:
            return JSONResponse(ErrorAnswer(str(exc)).to_dict(), status_code=400)
        pre: Person | Place | None = None
        if fields.kind == "person":
            people_table = archive.get_identity("people")
            pre = people_table.record(fields.entity_id) if people_table is not None else None
        else:
            places_table = archive.get_identity("places")
            pre = places_table.record(fields.entity_id) if places_table is not None else None
        name = pre.name if pre is not None else fields.entity_id
        basis = DecisionBasis.from_dict(fields.basis).to_dict() if fields.basis else None
        try:
            record = archive.decide_identification(
                fields.item_id, fields.kind, fields.entity_id, fields.decision, basis
            )
        except (KeyError, ValueError, ArchiveError) as exc:
            return JSONResponse(ErrorAnswer(str(exc)).to_dict(), status_code=400)
        if record is None:
            return JSONResponse(ErrorAnswer(f"no {fields.kind} {fields.entity_id}").to_dict(), status_code=404)
        archive.publish(data_dir)
        item = archive.get_item(fields.item_id)
        pending = _identification_pending(item) if item is not None else 0
        return IdentifyDecideAnswer(
            kind=fields.kind,
            entity=record.to_dict(),
            message=receipt(
                name,
                fields.decision,
                basis,
                confirmed=pre is not None and pre.status == "confirmed",
            ),
            pending=pending,
        ).to_dict()

    @app.get("/api/sync/pending")
    def sync_pending(request: Request) -> Any:
        """The catch-up: the backend pulls anything the real-time push missed."""
        if session_user(request) is None:
            return JSONResponse(ErrorAnswer("sign in to pull the outbox").to_dict(), status_code=401)
        return {"pending": [{"id": item_id, **payload} for item_id, payload in outbox.pending()]}

    @app.post("/api/sync/pending/received")
    def sync_received(body: Mapping[str, Any], request: Request) -> Any:
        """The website marks pulled items received — the outbox drains."""
        if session_user(request) is None:
            return JSONResponse(ErrorAnswer("sign in to drain the outbox").to_dict(), status_code=401)
        try:
            outbox.mark_received(ReceivedRequest.from_dict(body).ids)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return {"ok": True}

    @app.get("/data/{rest:path}")
    def projection_file(rest: str, request: Request) -> Any:
        """The projection the app reads — served from the server's OWN data
        directory, so `--data` means what it says (the app shell's static
        mount would otherwise serve `app/data` whatever the flag held)."""
        if session_user(request) is None:
            return JSONResponse({"ok": False, "error": "sign in to read the archive"}, status_code=401)
        root = data_dir.resolve()
        path = (root / rest).resolve()
        if root not in path.parents or not path.is_file():
            return JSONResponse({"ok": False, "error": "no such data file"}, status_code=404)
        return FileResponse(path)

    app.mount("/", StaticFiles(directory=str(app_dir), html=True), name="app")
    return app


def _hostname_i_addresses() -> list[str]:
    """`hostname -I` output split on whitespace, or [] when it fails."""
    try:
        return subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5).stdout.split()
    except (OSError, subprocess.TimeoutExpired):
        return []


def lan_addresses() -> list[str]:
    """Every non-loopback address this machine answers on.
    gethostbyname_ex misses hosts whose name doesn't resolve to the LAN
    interface — fall back to `hostname -I` (2026-08-05: this machine's
    hostname returned nothing)."""
    try:
        addresses = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        return [a for a in _hostname_i_addresses() if not a.startswith("127.")]
    if not any(not a.startswith("127.") for a in addresses):
        addresses = _hostname_i_addresses()
    return [a for a in addresses if not a.startswith("127.")]


def create_server(
    config: ServerConfig,
    host: str = "127.0.0.1",
    port: int = 8124,
    _reprocess: Callable[[str, str], None] | None = None,
) -> Any:
    """Build the uvicorn server with the given config (DI for tests).
    ``Server`` is the running noun; tests drive this one. ``_reprocess`` is
    the injectable reprocess seam (tests stub it to avoid the real model)."""
    app = build_app(config, _reprocess=_reprocess)
    return uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))


class Server:
    """The archive's serving noun — one server, one serve().

    ``Server(...).serve()`` serves the app (no-cache) and the memory-capture
    API — FastAPI under uvicorn (houses parity: the framework owns query
    decoding, cookie parsing, and redirects). ``create_server``
    stays the DI factory the tests drive.
    """

    def __init__(
        self,
        config: ServerConfig,
        host: str = "127.0.0.1",
        port: int = 8124,
    ) -> None:
        self.config = config
        self.host = host
        self.port = port

    def lan_urls(self) -> list[str]:
        """Every non-loopback address this machine answers on, as http
        URLs on this server's port."""
        return [f"http://{addr}:{self.port}" for addr in lan_addresses()]

    def serve(self) -> None:
        """Run until interrupted — the surface the `loft serve` command starts."""
        # a previous run's reprocess threads died with the process — any page
        # left "transcribing" demotes to "failed" (its text is stale; the
        # warning shows, never a silent half-done page, 2026-08-16)
        demote_stale_jobs(LoftPaths.WORK_DIR)
        app = build_app(self.config)
        if self.host == "0.0.0.0":
            for url in self.lan_urls():
                print(f"Serving {self.config.app_dir} at {url} (no-cache)")
        else:
            print(f"Serving {self.config.app_dir} on {self.host}:{self.port} (no-cache)")
        uvicorn.run(app, host=self.host, port=self.port, log_level="info")
