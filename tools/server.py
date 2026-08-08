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
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from tools import auth, memory
from tools.ai_client import AIClient
from tools.archive import Archive, split_content
from tools.memory import Knowledge
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

    @app.post("/api/people/confirm", response_model=None)
    def confirm_person(request: Request, body: dict[str, Any]) -> dict[str, Any] | JSONResponse:
        """The import's pending people (2026-08-07, user): confirm one —
        kept = confirmed, the person becomes family. The archive supersedes
        and the projection regenerates; the app merges the returned person."""
        mine = narrator(request)
        if mine is None:
            return JSONResponse({"ok": False, "error": "sign in to review the import"}, status_code=401)
        person_id = str(body.get("id", ""))
        if not person_id:
            return JSONResponse({"ok": False, "error": "no id"}, status_code=400)
        try:
            person = archive.confirm_person(person_id)
        except KeyError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=404)
        archive.refresh_import_status()  # the last pending person completes the session
        archive.publish(data_dir)
        return {"ok": True, "person": person}

    @app.post("/api/people/dismiss", response_model=None)
    def dismiss_person(request: Request, body: dict[str, Any]) -> dict[str, Any] | JSONResponse:
        """The import's pending people — dismiss one: dropped = gone, the
        person and their relationships leave the archive."""
        mine = narrator(request)
        if mine is None:
            return JSONResponse({"ok": False, "error": "sign in to review the import"}, status_code=401)
        person_id = str(body.get("id", ""))
        if not person_id:
            return JSONResponse({"ok": False, "error": "no id"}, status_code=400)
        try:
            archive.dismiss_person(person_id)
        except (KeyError, ValueError) as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        archive.refresh_import_status()  # the last pending person completes the session
        archive.publish(data_dir)
        return {"ok": True, "id": person_id}

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
