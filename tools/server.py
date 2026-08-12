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

import json
import logging
import os
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from tools import auth, memory, review
from tools.ai_client import AIClient
from tools.archive import Archive, ArchiveError, split_content
from tools.memory import ElicitationError, Knowledge
from tools.records import Person, ReviewContext, ReviewDecision
from tools.store import FileStore

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 1_000_000


def _atomic_write(path: Path, data: Any) -> None:
    """Replace a derived file atomically (temp + rename) — never half-written.
    The projection's write path; a reader in 2060 must not meet a torn file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def build_app(
    store: FileStore,
    data_dir: Path,
    client: AIClient | None,
    app_dir: Path,
) -> FastAPI:
    """The FastAPI app with the store/client/dirs bound (DI for tests)."""
    archive = Archive(store)
    data_dir = Path(data_dir)
    app_dir = Path(app_dir)

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
            people=_read_projection("people.json", "people"),
            places=_read_projection("places.json", "places"),
            themes=_read_projection("themes.json", "themes"),
            items=_read_projection("index.json", "items"),
        )

    def _read_projection(filename: str, key: str) -> list[dict[str, Any]]:
        path = data_dir / filename
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8")).get(key, [])

    def existing_ids() -> set[str]:
        ids = {it["id"] for it in _read_projection("index.json", "items")}
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
            max_age=30 * 24 * 3600,
            httponly=True,
            samesite="lax",
            path="/",
        )

    # -- the capture API (session required, narrator from the session) ------

    @app.post("/api/assess", response_model=None)
    def assess(request: Request, body: dict[str, Any]) -> dict[str, Any] | JSONResponse:
        mine = narrator(request)
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
            anchor=body.get("anchor", {}),
            who=mine["who"],  # the verified session, never the client
            title=str(body.get("title", "")),
            account=str(body.get("account", "")),
            extractions=body.get("extractions", []),
            facts=facts,
            knowledge=knowledge(),
            existing_ids=existing_ids(),
            status=str(body.get("status", "draft")),
            story_id=body.get("id"),
            chat=body.get("chat"),
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
        return {"ok": True, "person": person, "message": message}

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
                    transcription = archive.read_content_prefix(item_id, "transcription.txt", 4096) or ""
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
        _merge_records("people.json", "people", new_people)
        _merge_records("places.json", "places", new_places)

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

    app.mount("/", StaticFiles(directory=str(app_dir), html=True), name="app")
    return app


def _lan_urls(port: int) -> list[str]:
    """Every non-loopback address this machine answers on, as http URLs.
    gethostbyname_ex misses hosts whose name doesn't resolve to the LAN
    interface — fall back to `hostname -I` (2026-08-05: this machine's
    hostname returned nothing)."""
    try:
        addresses = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        addresses = []
    if not any(not a.startswith("127.") for a in addresses):
        import subprocess

        try:
            addresses = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5).stdout.split()
        except (OSError, subprocess.TimeoutExpired):
            addresses = []
    return [f"http://{addr}:{port}" for addr in addresses if not addr.startswith("127.")]


def create_server(
    store: FileStore,
    data_dir: Path,
    client: AIClient | None,
    app_dir: Path,
    host: str = "127.0.0.1",
    port: int = 8124,
) -> Any:
    """Build the uvicorn server with the given store/client/dirs (DI for
    tests). ``Server`` is the running noun; tests drive this one."""
    import uvicorn

    app = build_app(store, data_dir, client, app_dir)
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
        store: FileStore,
        data_dir: Path,
        client: AIClient | None,
        app_dir: Path,
        host: str = "127.0.0.1",
        port: int = 8124,
    ) -> None:
        self.store = store
        self.data_dir = Path(data_dir)
        self.client = client
        self.app_dir = Path(app_dir)
        self.host = host
        self.port = port

    def serve(self) -> None:
        """Run until interrupted — the surface the `loft serve` command starts."""
        import uvicorn

        app = build_app(self.store, self.data_dir, self.client, self.app_dir)
        if self.host == "0.0.0.0":
            for url in _lan_urls(self.port):
                print(f"Serving {self.app_dir} at {url} (no-cache)")
        else:
            print(f"Serving {self.app_dir} on {self.host}:{self.port} (no-cache)")
        uvicorn.run(app, host=self.host, port=self.port, log_level="info")
