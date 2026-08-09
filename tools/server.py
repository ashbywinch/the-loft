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
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from tools import auth, memory, review
from tools.ai_client import AIClient
from tools.archive import Archive, ArchiveError, split_content
from tools.memory import ElicitationError, Knowledge
from tools.records import Person, ReviewContext
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
        try:
            person = archive.resolve_person(person_id, decision, basis)
        except (KeyError, ValueError) as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        # the review record — every decision persists on the session's page,
        # and the resume point follows the queue (2026-08-09)
        queue = archive.review_queue()
        archive.record_review_exchange(
            session_id,
            {
                "kind": "decision",
                "person_id": person_id,
                "decision": decision,
                "basis": basis,
                "when": datetime.now(UTC).date().isoformat(),
                "last": not queue.pending,
            },
        )
        archive.refresh_import_status()  # the last pending person completes the session
        archive.publish(data_dir)
        return {"ok": True, "person": person}

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
        people = archive.get_identity("people") or {"people": []}
        all_people = tuple(Person.from_dict(p) for p in people["people"])
        person = next((p for p in all_people if p.id == person_id), None)
        if person is None:
            return JSONResponse({"ok": False, "error": f"no person {person_id}"}, status_code=404)
        if client is None:
            return JSONResponse({"ok": False, "error": "the AI isn't configured on this server"}, status_code=503)
        try:
            # the investigation needs the attested facts the Knowledge
            # conversion drops — the raw people (deaths, relations), the
            # recorded items' stories, and the family edges — typed as the
            # ReviewContext (2026-08-09)
            items: list[dict[str, Any]] = []
            for item_id in archive.item_ids():
                item = archive.get_item(item_id)
                if item and item.get("status") == "catalogued":
                    story = item.get("story") or item.get("transcription") or ""
                    if story:
                        items.append({"id": item_id, "title": item.get("title", ""), "story": story})
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
            )
        except ElicitationError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=422)
        archive.record_review_exchange(
            session_id,
            {"kind": "exchange", "role": "user", "text": text, "when": datetime.now(UTC).date().isoformat()},
        )
        # the assistant's side belongs in the record too — a transcript with
        # only the user's words can't be diagnosed (2026-08-09, user: "why
        # do you need me to tell you what the transcript says?")
        archive.record_review_exchange(
            session_id,
            {
                "kind": "assistant",
                "response": {
                    "relevant": result.get("relevant"),
                    "contradiction": result.get("contradiction"),
                    "confidence": result.get("confidence"),
                    "note": result.get("note"),
                    "findings": result.get("findings"),
                },
                "when": datetime.now(UTC).date().isoformat(),
            },
        )
        return {"ok": True, **result}

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
        except OSError, subprocess.TimeoutExpired:
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
