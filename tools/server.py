"""The archive's one server — FastAPI (houses parity, 2026-08-06).

Serves the app (no-cache) and the contribution API. The move from the
hand-rolled http.server handler was forced by the auth bug class it kept
breeding: FastAPI decodes query parameters (the percent-encoded auth code),
parses cookies and JSON bodies, and issues redirects — every one of those
was hand-reimplemented wrong at least once.

The archive's data is the private layer (user, 2026-08-06): /data/* 401s
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
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from tools import auth, memory, review
from tools.ai_client import AIClient
from tools.archive import Archive, ArchiveError
from tools.loft_paths import REGISTRY_DIR, WORK_DIR
from tools.memory import ElicitationError, Knowledge
from tools.records import Person, ReviewContext, ReviewDecision, split_content
from tools.registry import RegistryError, list_batches, load_batch
from tools.store import FileStore
from tools.sync import (
    BATCH_ID,
    QUARTERS_PER_TURN,
    Outbox,
    demote_stale_jobs,
    draft_payloads,
    page_job_state,
    record_confirmation,
    reprocess_page_transcription,
    rotate_page,
    safe_page_name,
    set_page_job,
    validate_confirmation,
)

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
) -> FastAPI:
    """The FastAPI app with the store/client/dirs bound (DI for tests).
    ``_env`` overrides the process environment for the build-time checks
    (the session secret); None reads os.environ."""
    if not auth.session_secret(_env):
        # an empty signing key means forgeable sessions — and the sync write
        # seam rides the session (2026-08-14 review): refuse to start
        raise RuntimeError("THE_LOFT_SESSION_SECRET is not set — refusing to start with forgeable sessions")
    archive = Archive(config.store)
    client = config.client
    data_dir = Path(config.data_dir)
    app_dir = Path(config.app_dir)
    work_dir = Path(config.work_dir) if config.work_dir else WORK_DIR
    registry_dir = Path(config.registry_dir) if config.registry_dir else REGISTRY_DIR
    outbox = config.outbox if config.outbox is not None else Outbox(WORK_DIR.parent / "sync-outbox")

    app = FastAPI(title="The Loft", docs_url=None, redoc_url=None)

    def session_user(request: Request) -> dict[str, Any] | None:
        return auth.session_user_from_cookie(request.cookies.get(auth.COOKIE_NAME))

    def narrator(request: Request) -> dict[str, Any] | None:
        """The signed-in narrator — the verified session's person. The
        capture API never trusts a client-claimed name (2026-08-06)."""
        session = session_user(request)
        if not session:
            return None
        person_id = auth.person_for_email(archive, session.get("email"))
        person = None
        if person_id:
            people = archive.get_identity("people") or {"people": []}
            person = next((p for p in people["people"] if p["id"] == person_id), None)
        return {
            "email": session.get("email", ""),
            "name": person["name"] if person else session.get("name", ""),
            "person": person_id,
            "who": person["name"] if person else session.get("name", ""),
        }

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

    def existing_ids() -> set[str]:
        ids = {it["id"] for it in _read_projection(filename="index.json", key="items")}
        ids |= set(archive.item_ids()) | archive.proposed_ids()
        return ids

    # -- auth --------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "ai": client is not None}

    @app.get("/api/auth/login")
    def login() -> dict[str, Any]:
        return auth.login_url()

    @app.get("/api/auth/me")
    def me(request: Request) -> dict[str, Any]:
        session = session_user(request)
        logger.info("auth: /me saw %s", "a session" if session else "no session")
        return auth.me_payload(archive, session)

    @app.post("/api/auth/logout")
    def logout() -> JSONResponse:
        response = JSONResponse({"ok": True})
        response.delete_cookie(auth.COOKIE_NAME, path="/")
        return response

    @app.get("/api/auth/callback")
    def callback(code: str = "", state: str = "", error: str = "") -> RedirectResponse:
        """Google's OAuth callback — FastAPI decodes the percent-encoded
        query (the 4%2F0AXE… code that a raw parser mangled, 2026-08-06)."""
        if error:
            return RedirectResponse(auth.callback_error_url(f"google:{error}"))
        id_info = auth.exchange_code(code, state) if code and state else None
        if id_info is None:
            return RedirectResponse(auth.callback_error_url("failed"))
        response = RedirectResponse(f"{auth.public_url()}/")
        _set_session_cookie(response, id_info)
        return response

    @app.get("/api/auth/device/start")
    def device_start() -> dict[str, Any]:
        return auth.start_device_grant()

    @app.post("/api/auth/device/poll")
    def device_poll(body: dict[str, Any]) -> dict[str, Any]:
        """The device grant's poll (headless tools; the browser uses the web
        flow). The cookie rides the complete NAVIGATION, never this response
        — the phone's network rejects fetch-carried cookies (2026-08-06)."""
        result = auth.poll_device_grant(str(body.get("state", "")))
        if result.get("status") == "ok" and result.get("id_info"):
            return {"ok": True, "complete": True}
        logger.info("auth: device poll -> %s", result.get("status"))
        return {"ok": False, **{k: v for k, v in result.items() if k != "id_info"}}

    @app.get("/api/auth/device/complete")
    def device_complete(state: str = "") -> RedirectResponse:
        minted = auth.minted_session(state)
        if minted is None:
            return RedirectResponse(f"{auth.public_url()}/?auth_error=expired")
        response = RedirectResponse(f"{auth.public_url()}/")
        _set_session_cookie(response, minted)
        logger.info("auth: device complete — session cookie issued for %s", minted.get("email"))
        return response

    def _set_session_cookie(response: JSONResponse | RedirectResponse, id_info: dict[str, Any]) -> None:
        cookie = auth._make_session_cookie(
            str(id_info.get("email", "")).casefold(),
            str(id_info.get("name", "")),
            str(id_info.get("picture", "")),
        )
        response.set_cookie(
            auth.COOKIE_NAME,
            cookie,
            max_age=int(auth.SESSION_MAX_AGE.total_seconds()),
            httponly=True,
            samesite="lax",
            path="/",
        )

    # -- the capture API (session required, narrator from the session) ------

    @app.post("/api/assess", response_model=None)
    def assess(request: Request, body: dict[str, Any]) -> dict[str, Any] | JSONResponse:
        mine = narrator(request)
        # lucidlint: ignore special-case the 401 auth gate IS the absent case — a stand-in would hide the boundary
        if mine is None:
            return JSONResponse({"ok": False, "error": "sign in to tell a story"}, status_code=401)
        if client is None:
            return JSONResponse({"ok": False, "error": "the AI isn't configured on this server"}, status_code=503)
        assessment = memory.assess(
            client,
            anchor=body.get("anchor", {}),
            who=mine["who"],
            account=str(body.get("account", "")),
            knowledge=knowledge(),
        )
        return {"ok": True, **assessment}

    @app.post("/api/save", response_model=None)
    def save(request: Request, body: dict[str, Any]) -> dict[str, Any] | JSONResponse:
        mine = narrator(request)
        if mine is None:
            return JSONResponse({"ok": False, "error": "sign in to tell a story"}, status_code=401)
        # typed answers to date questions arrive as pending facts (value
        # null) — the model asserts their value/precision, the library
        # validates; offline, the pending fact stays for a person to resolve
        facts = memory.resolve_pending_facts(client, body.get("facts", []))
        story, new_people, new_places = memory.build_story(
            request=memory.StoryRequest(
                anchor=body.get("anchor", {}),
                who=mine["who"],  # the verified session, never the client
                title=str(body.get("title", "")),
                account=str(body.get("account", "")),
                extractions=body.get("extractions", []),
                facts=facts,
                status=str(body.get("status", "draft")),
                story_id=body.get("id"),
                chat=body.get("chat"),
            ),
            knowledge=knowledge(),
            existing_ids=existing_ids(),
        )
        # drafts are committed during dev (user, 2026-08-03): the archive
        # store holds the canonical sidecar, and the projection is refreshed
        # so the story renders in the app — idempotent, atomic. All archive
        # writes go through the archive library (docs/CONTRIBUTIONS.md). The
        # story text is primary content: it becomes a content file the
        # sidecar references, never a sidecar JSON field (TECH-SPEC §3).
        sidecar, content = split_content(story)
        archive.save_item(sidecar, content=content)
        for person in new_people:
            archive.propose_person(person)
        for place in new_places:
            archive.propose_place(place)
        _refresh_projection(story, new_people, new_places)
        return {"ok": True, "id": story["id"], "story": story, "people": new_people, "places": new_places}

    @app.post("/api/delete", response_model=None)
    def delete(request: Request, body: dict[str, Any]) -> dict[str, Any] | JSONResponse:
        """Abandon: the draft is superseded with a tombstone — append-only,
        the files stay, the newest version says deleted (user, 2026-08-03)."""
        mine = narrator(request)
        if mine is None:
            return JSONResponse({"ok": False, "error": "sign in to tell a story"}, status_code=401)
        item_id = str(body.get("id", ""))
        if not item_id:
            return JSONResponse({"ok": False, "error": "no id"}, status_code=400)
        archive.delete_item(item_id, str(body.get("reason", "abandoned")))
        _drop_from_projection(item_id)
        return {"ok": True}

    @app.post("/api/review/start", response_model=None)
    def review_start(request: Request, body: dict[str, Any]) -> dict[str, Any] | JSONResponse:
        """Begin a new walk of the review — the sessions' storage is
        attempt-separated (2026-08-09): a fresh attempt starts only when
        the last is empty or finished, so a mid-walk re-render continues
        the same walk and the diagnosis never mixes attempts."""
        mine = narrator(request)
        if mine is None:
            return JSONResponse({"ok": False, "error": "sign in to review the import"}, status_code=401)
        session_id = str(body.get("session_id", ""))
        if not session_id:
            return JSONResponse({"ok": False, "error": "session_id is required"}, status_code=400)
        try:
            archive.start_review_attempt(session_id)
        except ArchiveError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=404)
        # the lines already recorded in the current attempt — the app
        # records its rendered opening/claim only when they're new, so a
        # mid-walk re-render never duplicates the transcript (2026-08-10
        # review: "the persisted transcript then no longer equals what the
        # family saw")
        session_record = archive.get_review_session(session_id)
        attempt = session_record.current_attempt() if session_record else None
        messages = attempt.messages if attempt else ()
        return {"ok": True, "messages": [m.text for m in messages]}

    @app.post("/api/review/message", response_model=None)
    def review_message(request: Request, body: dict[str, Any]) -> dict[str, Any] | JSONResponse:
        """Record one of the app's own rendered lines (the opening, the
        claim) so the transcript is exactly what the family saw (2026-08-09,
        user: "when you load a given transcript, you see exactly what I
        saw")."""
        mine = narrator(request)
        if mine is None:
            return JSONResponse({"ok": False, "error": "sign in to review the import"}, status_code=401)
        session_id = str(body.get("session_id", ""))
        role = str(body.get("role", ""))
        text = str(body.get("text", ""))
        if not session_id or role not in ("user", "assistant") or not text.strip():
            return JSONResponse({"ok": False, "error": "session_id, role and text are required"}, status_code=400)
        try:
            archive.record_review_message(session_id, role, text, datetime.now(UTC).date().isoformat())
        except ArchiveError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=404)
        return {"ok": True}

    @app.post("/api/review/decide", response_model=None)
    def review_decide(request: Request, body: dict[str, Any]) -> dict[str, Any] | JSONResponse:
        """The import review (2026-08-09, user): one decision per proposed
        link — attested (→ confirmed, the reviewer's own verified word),
        estimated (→ estimated with the recorded basis {text, by, when}),
        pending (→ the import's guess stays proposed), delete (→ gone).
        The decision vocabulary is NOT the status vocabulary: "confirm" is
        a status, never an action."""
        mine = narrator(request)
        if mine is None:
            return JSONResponse({"ok": False, "error": "sign in to review the import"}, status_code=401)
        person_id = str(body.get("person_id", ""))
        decision = str(body.get("decision", ""))
        if not person_id or decision not in {"attested", "estimated", "pending", "delete"}:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "person_id and a valid decision (attested/estimated/pending/delete) are required",
                },
                status_code=400,
            )
        basis = body.get("basis")
        if basis is not None and not isinstance(basis, dict):
            return JSONResponse({"ok": False, "error": "basis must be an object"}, status_code=400)
        session_id = str(body.get("session_id", ""))
        if not session_id:
            return JSONResponse({"ok": False, "error": "session_id is required"}, status_code=400)
        # the session must exist BEFORE anything mutates — a stale session id
        # must not change the archive and then fail (2026-08-10 review:
        # resolve_person saved the person, then the session lookup raised,
        # returning 500 with the person already changed)
        if archive.get_review_session(session_id) is None:
            return JSONResponse({"ok": False, "error": f"no import session {session_id}"}, status_code=404)
        # the confirmation names the person — the resolve returns a
        # gone-marker for a delete, so the name comes from the table first
        people_table = archive.get_identity("people") or {"people": []}
        pre_person = next((p for p in people_table["people"] if p["id"] == person_id), None)
        person_name = (pre_person or {}).get("name", person_id)
        try:
            person, changed, was_proposed = archive.resolve_person(person_id, decision, basis)
        except (KeyError, ValueError) as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        # a stale decision on an already-resolved person is a state, not an
        # error — and it must not record a false confirmation ("removed"
        # when nothing was removed; 2026-08-11 review). Both flags come
        # from INSIDE the mutation lock: a concurrent decide cannot make a
        # stale pre-read look live, and a keep's exempted status is itself
        # reported by the mutation (was the person still proposed when the
        # lock was taken) — the pre-read status is gone entirely
        # (2026-08-11 review). A keep on a genuinely PROPOSED person is the
        # deliberate "leave for later" and is recorded.
        if not changed and (decision != "pending" or not was_proposed):
            message = f"{person_name} was already resolved — nothing changed."
            return {"ok": True, "person": person, "message": message}
        # the review record — the decision and the confirmation message the
        # family saw, both persisted (2026-08-09: the transcript is the
        # messages)
        when = datetime.now(UTC).date().isoformat()
        queue = archive.review_queue()
        archive.record_review_decision(
            session_id,
            ReviewDecision(
                person_id=person_id,
                decision=cast(Literal["attested", "estimated", "pending", "delete"], decision),
                when=when,
                basis=basis,
                last=not queue.pending,
            ),
        )
        message = review.confirmation_message(person_name, decision, basis)
        archive.record_review_message(session_id, "assistant", message, when)
        archive.refresh_import_status()  # the last pending person completes the session
        archive.publish(data_dir)
        # the accurate remaining count — the server's post-decision truth
        # (the client's projection is stale until reload; the count must
        # always be right, user 2026-08-16)
        return {"ok": True, "person": person, "message": message, "pending": len(queue.pending)}

    @app.post("/api/review/text", response_model=None)
    def review_text(request: Request, body: dict[str, Any]) -> dict[str, Any] | JSONResponse:
        """The reviewer's free text vs the exact claim under review
        (2026-08-09): the relevance check — on-topic (the answer addresses
        the proposed record and is recorded verbatim) or off-topic (the
        chat names the mismatch and steers back). The model never derives
        relationships — the reviewer's words are the record or nothing is."""
        mine = narrator(request)
        if mine is None:
            return JSONResponse({"ok": False, "error": "sign in to review the import"}, status_code=401)
        person_id = str(body.get("person_id", ""))
        text = str(body.get("text", ""))
        if not person_id or not text.strip():
            return JSONResponse({"ok": False, "error": "person_id and text are required"}, status_code=400)
        session_id = str(body.get("session_id", ""))
        if not session_id:
            return JSONResponse({"ok": False, "error": "session_id is required"}, status_code=400)
        # the session must exist BEFORE the costly model call — a stale id
        # must not run the investigation and then 500 in the recording
        # (2026-08-11 review; the decide endpoint fixed the same shape)
        if archive.get_review_session(session_id) is None:
            return JSONResponse({"ok": False, "error": f"no import session {session_id}"}, status_code=404)
        people = archive.get_identity("people") or {"people": []}
        all_people = tuple(Person.from_dict(p) for p in people["people"])
        person = next((p for p in all_people if p.id == person_id), None)
        if person is None:
            return JSONResponse({"ok": False, "error": f"no person {person_id}"}, status_code=404)
        if client is None:
            return JSONResponse({"ok": False, "error": "the AI isn't configured on this server"}, status_code=503)
        try:
            # the model sees the whole conversation — its own reasoning and
            # speech, verbatim — so a message that re-answers an earlier
            # question is recognised (2026-08-09, user). The history is the
            # conversation BEFORE this line: the investigation appends the
            # line itself, so a history that already held it would double
            # the latest message for the model (2026-08-11 review)
            session_record = archive.get_review_session(session_id)
            current_attempt = session_record.current_attempt() if session_record else None
            history = current_attempt.messages if current_attempt else ()
            # the family's line joins the transcript the moment it arrives —
            # the model call must not gate the record (R7/R8: the words are
            # never lost, and the transcript equals what the family saw —
            # 2026-08-11 review)
            when = datetime.now(UTC).date().isoformat()
            archive.record_review_message(session_id, "user", text, when)
            # the investigation needs the attested facts the Knowledge
            # conversion drops — the raw people (deaths, relations), the
            # recorded items' texts, and the family edges — typed as the
            # ReviewContext (2026-08-09). The projection carries the
            # VERBATIM transcription when the item has one (the document
            # the family sees in the claim and the item page) — the
            # sidecar's story is the archival summary, a different text
            # (2026-08-09, user: the model quoted the wrong part of the
            # document, because it was reading the summary). The people
            # involvement is the structured match the tools need — the
            # prose never carries ids. The FULL text is read only for the
            # shortlist that can attest this person: the metadata pass (one
            # sidecar per item, no transcription reads) filters first — at
            # the 10,000-item design target, reading every transcription
            # per chat message would be thousands of disk reads (2026-08-11
            # review). The metadata pass itself is still a full-archive
            # sidecar scan per message — O(N) disk reads at that target;
            # deferred (2026-08-11, user): fine at the current family-
            # archive scale (~100 items), revisit with a people→items
            # mention index before the 10,000-item target is real. The
            # name needles are lowered once and matched against lowered
            # text — OCR and captured text differ in case, and a
            # differently-cased mention must not hide the attesting
            # document (2026-08-11 review)
            needles = tuple(n.lower() for n in (person.name, person.name.split()[0]))
            items: list[dict[str, Any]] = []
            for item_id in archive.item_ids():
                item = archive.get_item(item_id)
                if not item or item.get("status") != "catalogued":
                    continue
                involved = person_id in [p.get("id") for p in item.get("people", []) if isinstance(p, dict)]
                story = str(item.get("story") or "").strip()
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
                    # (2026-08-11 review)
                    transcription = (
                        archive.read_content_prefix(item_id, "transcription.txt", TRANSCRIPTION_PREFIX_BYTES) or ""
                    )
                    if not any(n in transcription.lower() for n in needles):
                        continue
                    item_text = transcription
                if item_text:
                    items.append(
                        {
                            "id": item_id,
                            "title": item.get("title", ""),
                            "story": item_text,
                            # Rule L (2026-08-11 review): a draft
                            # transcription is machine-read and
                            # unverified — its sentences are never the
                            # document's own words; the model must know
                            # which texts are drafts so it never quotes
                            # one as verified evidence
                            "transcription_status": item.get("transcription_status"),
                            "people": [p.get("id") for p in item.get("people", []) if isinstance(p, dict)],
                        }
                    )
            result = review.investigate(
                client,
                text=text,
                person=person,
                who=mine["who"],
                facts=ReviewContext(
                    people=all_people,
                    items=tuple(items),
                    relationships=tuple(people.get("relationships", [])),
                ),
                history=history,
            )
        except ElicitationError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=422)
        # the transcript is the MESSAGES — what the family saw (2026-08-09):
        # the user's words (recorded BEFORE the call, so an outage never
        # loses them — 2026-08-11 review) and the assistant's rendered
        # words, built here, shown verbatim by the app, and stored verbatim.
        # The assistant's line also carries its THINKING — the model's raw
        # verdict, verbatim — which goes back to the model on later calls.
        # The note never reaches the user (it had been leaking into the
        # steer's parens).
        contradiction = result.get("contradiction", {}).get("found") == "true"
        if contradiction:
            # the contradiction surfaces before anything else — an off-topic
            # verdict that also flags one must not let the steer hide it
            # (2026-08-11 review)
            message = f"That doesn't match the records — {result['contradiction'].get('detail')}. Which is right?"
        elif result.get("relevant") == "false":
            message = review.steer_message(person, result.get("note") or "")
        else:
            # never persist an empty assistant line the family never saw
            # (2026-08-11 review)
            message = review.assistant_message(result, person).strip() or "Thank you — that's noted."
        archive.record_review_message(
            session_id, "assistant", message, when, thinking=json.dumps(result.get("trace"), ensure_ascii=False)
        )
        # the response carries ONLY what the UI consumes — the model's raw
        # output, its tool trace, and the prompt texts are the model's
        # internals, never the family's (R7; 2026-08-11 review: the full
        # result leaked raw/trace/prompt/final_prompt — and archive quotes
        # — to the browser on every message)
        return {
            "ok": True,
            "message": message,
            "relevant": result.get("relevant"),
            "contradiction": result.get("contradiction", {}),
            "confidence": result.get("confidence", ""),
            "note": result.get("note", ""),
            "findings": result.get("findings", []),
            "question": result.get("question", ""),
        }

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
        story: dict[str, Any],
        new_people: list[dict[str, Any]],
        new_places: list[dict[str, Any]],
    ) -> None:
        """The derived cache (app/data): merge the story and any proposed
        records. Idempotent by id — re-running a save never duplicates."""
        index_path = data_dir / "index.json"
        if index_path.exists():
            index = json.loads(index_path.read_text(encoding="utf-8"))
            items = [it for it in index.get("items", []) if it["id"] != story["id"]]
            items.append(story)
            items.sort(key=lambda it: it["date"])
            index["items"] = items
            _atomic_write(index_path, index)
        _merge_records(filename="people.json", key="people", records=new_people)
        _merge_records(filename="places.json", key="places", records=new_places)

    def _merge_records(filename: str, key: str, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        path = data_dir / filename
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {key: []}
        known = {r["id"] for r in data.get(key, [])}
        data[key] = data.get(key, []) + [r for r in records if r["id"] not in known]
        _atomic_write(path, data)

    # -- the static app + the data gate ------------------------------------

    @app.middleware("http")
    async def app_shell_no_cache(request: Request, call_next: Any) -> Any:
        # The app code must never be heuristically cached (2026-08-08: the
        # phone's browser served a stale index.html for hours — the
        # instrumentation deployed to the server never reached it, because
        # StaticFiles sends only ETag/Last-Modified and the browser's
        # heuristic kept the old shell). The shell + code revalidate every
        # load; the data assets (the scans) keep the default caching.
        response = await call_next(request)
        if not request.url.path.startswith("/data/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.middleware("http")
    async def origin_guard(request: Request, call_next: Any) -> Any:
        # CSRF guard for the write APIs (2026-08-03): a page on another
        # origin must not POST to the household server. The app's own
        # fetches carry the server's origin (or none, for curl); the auth
        # endpoints are exempt (the flow redirects cross-origin).
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
        # to read it (2026-08-06, user: content gated behind sign-in). The
        # app shell stays public so the gate can load.
        if request.url.path.startswith("/data/"):
            session = auth.session_user_from_cookie(request.cookies.get(auth.COOKIE_NAME))
            if session is None:
                return JSONResponse({"ok": False, "error": "sign in to read the archive"}, status_code=401)
        return await call_next(request)

    # -- sync (TECH-SPEC §16.15: the backend owns the write seam; the
    # frontend proposes, the backend records; the outbox is the catch-up) --

    @app.get("/api/sync/batches")
    def sync_batches(request: Request) -> Any:
        """Every adopted batch, newest first — the review surface's batch
        list (the batch label + status ride the registry record)."""
        if session_user(request) is None:
            return JSONResponse({"ok": False, "error": "sign in to read the batches"}, status_code=401)
        try:
            return {"batches": list_batches(registry_dir)}
        except RegistryError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/api/sync/batch/{batch_id}/drafts")
    def sync_drafts(batch_id: str, request: Request) -> Any:
        """The machine drafts the review surface reads (guesses + boundaries
        + layout, TECH-SPEC §16.16), with the registry's per-document
        review status merged in (the registry is the status' home — the
        guess stage's boundaries.json never changes after review)."""
        if session_user(request) is None:
            return JSONResponse({"ok": False, "error": "sign in to read the drafts"}, status_code=401)
        try:
            record = load_batch(batch_id, registry_dir)
            by_pages = {tuple(b.get("pages", [])): b.get("status", "review") for b in (record.get("boundaries") or [])}
            documents = [
                {
                    **document,
                    "status": by_pages.get(tuple(document.get("pages", [])), "review"),
                }
                for document in draft_payloads(batch_id, work_dir)
            ]
            return {
                "batch_id": batch_id,
                "label": record.get("label"),
                "documents": documents,
                "processing": page_job_state(batch_id, work_dir),
            }
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except RegistryError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/api/sync/batch/{batch_id}/page/{page}")
    def sync_page(batch_id: str, page: str, request: Request) -> Any:
        """The oriented page image the review surface renders (auth-gated
        like the drafts; batch id and page name become path segments —
        validated by the sync contract's guard, 2026-08-15)."""
        if session_user(request) is None:
            return JSONResponse({"ok": False, "error": "sign in to read the pages"}, status_code=401)
        if not BATCH_ID.match(batch_id) or not safe_page_name(page):
            return JSONResponse({"error": "invalid batch or page name"}, status_code=400)
        image = work_dir / batch_id / "oriented" / page
        if not image.is_file():
            return JSONResponse({"error": "no such page"}, status_code=404)
        return FileResponse(image)

    @app.post("/api/sync/batch/{batch_id}/page/{page}/rotate")
    def sync_rotate_page(batch_id: str, page: str, request: Request, body: dict[str, Any] | None = None) -> Any:
        """The reviewer's orientation fix (2026-08-16). The intent is the
        DESIRED cumulative rotation in quarter-turns — no image travels, the
        backend has it (the front and back end are different boxes). The
        fast rotation (image + box remap) applies synchronously; the slow
        re-transcription runs as the async job, the page marked
        "transcribing" in the drafts payload meanwhile — the surface greys
        the document with a note and the reviewer navigates on."""
        if session_user(request) is None:
            return JSONResponse({"ok": False, "error": "sign in to fix pages"}, status_code=401)
        quarters = 1
        # 0 is a real intent: the reviewer's rotate-back to the ORIGINAL
        # orientation (the UI's % 4 range) — rejecting it defaulted to a
        # wrong +90 (bot review, 2026-08-16)
        if body and isinstance(body.get("quarters"), int) and body["quarters"] in range(QUARTERS_PER_TURN):
            quarters = body["quarters"]
        try:
            rotated = rotate_page(batch_id, page, quarters, work_dir)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if not rotated:
            return {"ok": True, "batch_id": batch_id, "page": page, "processing": False}
        set_page_job(batch_id, page, "transcribing", work_dir)

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
                    label = load_batch(batch_id, registry_dir).get("label")
                reprocess_page_transcription(batch_id, page, work_dir, people=people, places=places, label=label)
            # The background thread's terminal handler — logger.exception
            # lucidlint: ignore swallow is the observable surface; the thread ends
            except Exception:
                logger.exception("reprocess failed for %s/%s", batch_id, page)

        threading.Thread(target=_job, daemon=True).start()
        return {"ok": True, "batch_id": batch_id, "page": page, "processing": True}

    @app.post("/api/sync/confirmations")
    def sync_confirmations(payload: dict[str, Any], request: Request) -> Any:
        """The backend receiver: validate, record (ocr-confirmed + registry),
        re-publish the projection. The frontend never writes the archive."""
        if session_user(request) is None:
            return JSONResponse({"ok": False, "error": "sign in to send confirmations"}, status_code=401)
        try:
            validate_confirmation(payload)
            text = payload.get("text") if payload.get("status") == "confirmed" else None
            record_confirmation(
                str(payload["batch_id"]),
                int(payload["doc_index"]),
                payload,
                text,
                work_dir=work_dir,
                registry_dir=registry_dir,
            )
        except (TypeError, ValueError, RegistryError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)  # client errors are 4xx, never 500
        archive.publish(data_dir)
        return {"ok": True, "batch_id": payload["batch_id"], "doc_index": payload["doc_index"]}

    @app.get("/api/sync/pending")
    def sync_pending(request: Request) -> Any:
        """The catch-up: the backend pulls anything the real-time push missed."""
        if session_user(request) is None:
            return JSONResponse({"ok": False, "error": "sign in to pull the outbox"}, status_code=401)
        return {"pending": [{"id": item_id, **payload} for item_id, payload in outbox.pending()]}

    @app.post("/api/sync/pending/received")
    def sync_received(ids: dict[str, Any], request: Request) -> Any:
        """The website marks pulled items received — the outbox drains."""
        if session_user(request) is None:
            return JSONResponse({"ok": False, "error": "sign in to drain the outbox"}, status_code=401)
        try:
            outbox.mark_received([str(item_id) for item_id in ids.get("ids", [])])
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return {"ok": True}

    app.mount("/", StaticFiles(directory=str(app_dir), html=True), name="app")
    return app


def lan_urls(port: int) -> list[str]:
    """Every non-loopback address this machine answers on, as http URLs.
    gethostbyname_ex misses hosts whose name doesn't resolve to the LAN
    interface — fall back to `hostname -I` (2026-08-05: this machine's
    hostname returned nothing)."""
    try:
        addresses = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        return _urls_from(_hostname_i_addresses(), port)
    if not any(not a.startswith("127.") for a in addresses):
        addresses = _hostname_i_addresses()
    return _urls_from(addresses, port)


def _hostname_i_addresses() -> list[str]:
    """`hostname -I` output split on whitespace, or [] when it fails."""
    try:
        return subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5).stdout.split()
    except (OSError, subprocess.TimeoutExpired):
        return []


def _urls_from(addresses: list[str], port: int) -> list[str]:
    return [f"http://{addr}:{port}" for addr in addresses if not addr.startswith("127.")]


def create_server(
    config: ServerConfig,
    host: str = "127.0.0.1",
    port: int = 8124,
) -> Any:
    """Build the uvicorn server with the given config (DI for tests).
    ``Server`` is the running noun; tests drive this one."""
    app = build_app(config)
    return uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))


class Server:
    """The archive's serving noun — one server, one serve().

    ``Server(...).serve()`` serves the app (no-cache) and the memory-capture
    API — FastAPI under uvicorn (2026-08-06, houses parity: the framework
    owns query decoding, cookie parsing, and redirects). ``create_server``
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

    def serve(self) -> None:
        """Run until interrupted — the surface the `loft serve` command starts."""
        # a previous run's reprocess threads died with the process — any page
        # left "transcribing" demotes to "failed" (its text is stale; the
        # warning shows, never a silent half-done page, 2026-08-16)
        demote_stale_jobs(WORK_DIR)
        app = build_app(self.config)
        if self.host == "0.0.0.0":
            for url in lan_urls(self.port):
                print(f"Serving {self.config.app_dir} at {url} (no-cache)")
        else:
            print(f"Serving {self.config.app_dir} on {self.host}:{self.port} (no-cache)")
        uvicorn.run(app, host=self.host, port=self.port, log_level="info")
