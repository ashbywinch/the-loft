"""Tests for the capture server: the API contract, append-only writes through
the store, and the projection refresh. The handler is exercised through the
real HTTP stack on an ephemeral port — no network, no AI."""

from __future__ import annotations

import io
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any, override

import pytest
from PIL import Image

from loft.live.import_identity import sync_from_archive
from loft.live.memory import MemoryLiveStore
from pipeline.api.server import ServerConfig, create_server
from pipeline.api.sync import Outbox
from pipeline.registry import load_batch
from tools.archive import Archive
from tools.memory import ElicitationError
from tools.records import Item, validate_identity
from tools.store import ImmutableStoreError, MemoryStore


def make_app_data(tmp_path: Path) -> Path:
    # the served app shell (public) + its data/ (gated) — the real app's shape
    _ = (tmp_path / "index.html").write_text("<!DOCTYPE html><html><body>the loft</body></html>", encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    _ = (data / "index.json").write_text(
        json.dumps(
            {
                "generated": "2026-08-03",
                "items": [
                    {
                        "id": "letter-1963-05-14",
                        "title": "A week in the flat",
                        "date": "1963-05-14",
                        "date_precision": "exact",
                        "type": "letter",
                        "status": "catalogued",
                        "assets": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    _ = (data / "people.json").write_text(
        json.dumps({"people": [{"id": "p-alex", "name": "Alex Hale", "aliases": ["Alex"]}]}),
        encoding="utf-8",
    )
    _ = (data / "places.json").write_text(
        json.dumps({"places": [{"id": "pl-marlock", "name": "Marlock"}]}),
        encoding="utf-8",
    )
    _ = (data / "themes.json").write_text(
        json.dumps({"themes": [{"id": "t-the-boats", "title": "The boats"}]}),
        encoding="utf-8",
    )
    return data


class ServerFixture:
    def __init__(
        self,
        data_dir: Path,
        store: MemoryStore,
        client: Any | None = None,
        _reprocess: Any | None = None,
        registry_dir: Path | None = None,
        live: MemoryLiveStore | None = None,
    ) -> None:
        self.store: MemoryStore = store
        self.live = live
        self.data_dir: Path = data_dir
        self._reprocess: Any | None = _reprocess
        # the session secret before any app build — the server refuses to
        # start without it (forgeable sessions otherwise)
        import os

        os.environ.setdefault("THE_LOFT_SESSION_SECRET", "test-secret")
        # the sync surfaces are bound to tmp dirs, never the real workspace
        # (the endpoints must not touch the home disk in tests)
        self.work_dir: Path = data_dir.parent / "work"
        self.outbox: Outbox = Outbox(data_dir.parent / "outbox")
        self.registry_dir: Path = registry_dir or data_dir.parent / "registry"
        # the identity seam: the archive's people carry the
        # verified Google accounts; the capture API resolves the narrator
        # from the session, never from the client
        from tools.archive import Archive

        self.archive = Archive(store)
        self.archive.save_identity(
            "people",
            validate_identity(
                "people",
                {
                    "people": [
                        {"id": "p-alex", "name": "Alex Hale", "email": "alex@example.com"},
                        {"id": "p-other", "name": "Other", "email": "other@example.com"},
                    ],
                    "relationships": [],
                },
            ),
        )
        # the sync confirmation receiver re-publishes — the store must be
        # publishable (places/themes present), not just people
        self.archive.save_identity(
            "places", validate_identity("places", {"places": [{"id": "pl-marlock", "name": "Marlock"}]})
        )
        self.archive.save_identity("themes", validate_identity("themes", {"themes": []}))
        # the server refuses to start without a session secret (forgeable
        # sessions) — the test secret must be set BEFORE create_server, not
        # after (the dev shell exports the secret; CI has none)
        import os

        os.environ.setdefault("THE_LOFT_SESSION_SECRET", "test-secret")
        self.server = create_server(
            ServerConfig(
                store,
                data_dir,
                client=client,
                app_dir=data_dir.parent,
                work_dir=self.work_dir,
                outbox=self.outbox,
                registry_dir=self.registry_dir,
                live=live,
            ),
            host="127.0.0.1",
            port=0,
            _reprocess=_reprocess,
        )
        self.thread: threading.Thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        # uvicorn assigns the ephemeral port at startup — wait for it
        import time

        for _ in range(100):
            sockets = getattr(self.server, "servers", None)
            if sockets and sockets[0].sockets:
                self.port: int = sockets[0].sockets[0].getsockname()[1]
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("uvicorn did not bind a port")
        # a signed-in session for the capture API — the verified Google account
        from pipeline.api import auth
        from pipeline.api.session_user import SessionUser

        user = SessionUser("alex@example.com", "Alex Hale", "")
        self.cookie = f"{auth.GoogleOAuth.COOKIE_NAME}={auth._make_session_cookie(user)}"

    def post(self, path: str, body: dict[str, Any], cookie: str | None = None) -> tuple[int, dict[str, Any]]:
        headers = {"Content-Type": "application/json"}
        if cookie is not None:
            headers["Cookie"] = cookie
        elif path.startswith("/api/auth/"):
            pass  # the auth endpoints need no session
        else:
            headers["Cookie"] = self.cookie  # the capture API requires the session
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def get(self, path: str, cookie: str | None = None) -> tuple[int, bytes]:
        headers = {"Cookie": cookie} if cookie else {}
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def close(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


@pytest.fixture
def server(tmp_path: Path) -> Iterator[ServerFixture]:
    fixture = ServerFixture(make_app_data(tmp_path), MemoryStore())
    yield fixture
    fixture.close()


@pytest.fixture
def live_server(tmp_path: Path) -> Iterator[ServerFixture]:
    """B1's flipped host: the identity surface writes through the live store,
    and the compatibility exporter keeps the archive's old tables current."""
    live = MemoryLiveStore(app_version="test")
    fixture = ServerFixture(make_app_data(tmp_path), MemoryStore(), live=live)
    sync_from_archive(live, fixture.archive)
    yield fixture
    fixture.close()
    live.close()


def test_the_projection_is_served_from_the_servers_own_data_dir(server: ServerFixture) -> None:
    """`--data` is what the browser reads: the app shell's static mount would
    otherwise serve `app/data` regardless of the flag. Traversal is refused."""
    status, raw = server.get("/data/index.json", cookie=server.cookie)
    assert status == 200
    assert json.loads(raw.decode("utf-8"))["items"][0]["id"] == "letter-1963-05-14"
    status, _ = server.get("/data/../server.py", cookie=server.cookie)
    assert status == 404
    status, _ = server.get("/data/index.json")  # no session
    assert status == 401


def test_bootstrap_requires_a_session(server: ServerFixture) -> None:
    status, _ = server.get("/api/bootstrap")
    assert status == 401


def test_bootstrap_refuses_an_unpublished_projection(server: ServerFixture) -> None:
    """A missing app/data is an operator error, not an empty archive."""
    (server.data_dir / "index.json").unlink()
    status, raw = server.get("/api/bootstrap", cookie=server.cookie)
    assert status == 503
    assert b"not published" in raw


def test_bootstrap_returns_identity_and_projection(server: ServerFixture) -> None:
    """One auth-gated request carries what the home used to fetch in six."""
    status, raw = server.get("/api/bootstrap", cookie=server.cookie)
    assert status == 200
    body = json.loads(raw.decode("utf-8"))
    assert body["me"]["authenticated"] is True
    assert body["index"]["items"][0]["id"] == "letter-1963-05-14"
    assert body["people"]["people"][0]["id"] == "p-alex"
    assert body["places"]["places"][0]["id"] == "pl-marlock"
    assert "themes" in body and "imports" in body


def test_text_responses_are_gzipped(server: ServerFixture) -> None:
    """The projection and the module graph are text; the phone pays for them."""
    (server.data_dir / "big.json").write_text(json.dumps({"items": ["x" * 4000]}), encoding="utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/data/big.json",
        headers={"Cookie": server.cookie, "Accept-Encoding": "gzip"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.headers.get("Content-Encoding") == "gzip"
        assert len(response.read()) < 4_000


def test_binary_assets_are_not_gzipped(server: ServerFixture) -> None:
    """JPEG scans are already compressed; a second pass costs CPU and gains nothing."""
    assets = server.data_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "scan.jpg").write_bytes(b"x" * 4096)
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/data/assets/scan.jpg",
        headers={"Cookie": server.cookie, "Accept-Encoding": "gzip"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.headers.get("Content-Encoding") is None


def test_health(server: ServerFixture) -> None:
    status, body = server.get("/api/health")
    assert status == 200
    assert json.loads(body) == {"ok": True, "ai": False}


def test_assess_requires_the_ai(server: ServerFixture) -> None:
    status, body = server.post("/api/assess", {"anchor": {}, "who": "", "account": "x"})
    assert status == 503
    assert body["ok"] is False


def test_save_writes_sidecar_and_refreshes_projection(server: ServerFixture) -> None:
    """A saved contribution lands in the append-only store as a draft and the
    projection is refreshed (drafts are committed during dev)."""
    status, body = server.post(
        "/api/save",
        {
            "anchor": {"kind": "item", "id": "letter-1963-05-14", "name": "A week in the flat"},
            "who": "Alex",
            "title": "The damp winter",
            "account": "The flat was damp that winter, in 1963.",
            "extractions": [
                {"kind": "place", "name": "Marlock", "match": "pl-marlock", "bucket": "proposed", "reason": ""}
            ],
            "facts": [{"kind": "event_date", "text": "in 1963", "value": "1963", "precision": "year"}],
            "status": "catalogued",  # a completed, reviewed flow — verified in the review
        },
    )
    assert status == 200, body
    story_id = body["id"]
    assert story_id.startswith("story-")

    # the sidecar exists exactly once, with the canonical shape
    sidecar_path = f"assets/{story_id}/item.json"
    assert server.store.exists(sidecar_path)
    sidecar = json.loads(server.store.read(sidecar_path))
    assert sidecar["status"] == "catalogued"
    assert sidecar["told_by"] == "p-alex"
    assert sidecar["comment_on"] == "letter-1963-05-14"
    assert sidecar["date"] == "1963" and sidecar["date_precision"] == "year"
    # the operator verified the AI's guesses in the review — the kept link is confirmed
    assert {"id": "pl-marlock", "status": "confirmed"} in sidecar["places"]
    # the story is primary content: a content file the sidecar references,
    # never a sidecar JSON field
    assert "story" not in sidecar
    assert server.store.read(f"assets/{story_id}/story.txt") == "The flat was damp that winter, in 1963."

    # the projection gained the story, atomically merged, idempotent by id —
    # the projection embeds the text (derived), the archive never does
    index = json.loads((server.data_dir / "index.json").read_text(encoding="utf-8"))
    ids = [it["id"] for it in index["items"]]
    assert story_id in ids
    assert len(ids) == len(set(ids))
    published = next(it for it in index["items"] if it["id"] == story_id)
    assert published["story"] == "The flat was damp that winter, in 1963."


def test_save_is_append_only_through_the_store(server: ServerFixture) -> None:
    # an attempt to write the same sidecar twice must fail the immutable store
    server.store.write_new("assets/story-x/item.json", "{}")
    with pytest.raises(ImmutableStoreError):
        server.store.write_new("assets/story-x/item.json", "{}")


def test_save_attributes_to_the_session_narrator(server: ServerFixture) -> None:
    """The narrator is the verified session person — a client-claimed 'who'
    is ignored (user: google auth, no name claims)."""
    status, body = server.post(
        "/api/save",
        {
            "anchor": {"kind": "place", "id": "pl-marlock", "name": "Marlock"},
            "who": "A Stranger",  # the client's claim — the server ignores it
            "title": "T",
            "account": "We visited Marlock.",
            "extractions": [],
            "facts": [{"kind": "event_date", "text": "in 1963", "value": "1963", "precision": "year"}],
            "status": "draft",
        },
    )
    assert status == 200, body
    assert body["people"] == []  # no stranger minted — the narrator is p-alex
    story_id = body["id"]
    sidecar = json.loads(server.store.read(f"assets/{story_id}/item.json"))
    assert sidecar["told_by"] == "p-alex"  # the verified session, never the claim


def test_unknown_endpoint_404(server: ServerFixture) -> None:
    status, _ = server.post("/api/nope", {})
    assert status in (404, 405)  # FastAPI answers 405 for a known path, unknown verb


def test_bad_json_rejected(server: ServerFixture) -> None:
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/api/save",
        data=b"not json",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5)
        raise AssertionError("expected HTTPError")
    except urllib.error.HTTPError as e:
        assert e.code in (400, 422)


def test_save_without_ai_keeps_a_pending_typed_date_answer_null(server: ServerFixture) -> None:
    """An offline save (no AI client) leaves a typed date answer pending —
    the value stays null for a person's word (docs/CHAT-UX.md)."""
    status, body = server.post(
        "/api/save",
        {
            "anchor": {"kind": "theme", "id": "t-the-boats", "name": "The boats"},
            "who": "Alex",
            "title": "The summer",
            "account": "Q: When were you born?\\nA: 31 July 1979",
            "extractions": [],
            "facts": [
                {
                    "kind": "dob",
                    "entity": None,
                    "text": "31 July 1979",
                    "value": None,
                    "precision": None,
                    "status": "confirmed",
                },
                {"kind": "event_date", "text": "in 1963", "value": "1963", "precision": "year"},
            ],
            "status": "catalogued",
        },
    )
    assert status == 200, body
    story_id = body["id"]
    sidecar = json.loads(server.store.read(f"assets/{story_id}/item.json"))
    # the pending dob stayed pending — no fabricated value
    dob_facts = [f for f in sidecar["facts"] if f["kind"] == "dob"]
    assert dob_facts[0]["value"] is None
    assert dob_facts[0]["status"] == "confirmed"
    # the story is dated by its events date, never the recording day
    assert sidecar["date"] == "1963"


def test_draft_auto_saves_supersede_in_place(server: ServerFixture) -> None:
    """The client's draft auto-saves keep ONE story id: each save supersedes
    the previous version (append-only — item.json, item-2.json, … the newest
    wins) and the projection holds a single entry (user: a reboot mid-chat
    loses at most the last few words)."""
    payload: dict[str, Any] = {
        "anchor": {"kind": "theme", "id": "t-the-boats", "name": "The boats"},
        "who": "Alex",
        "title": "The trips",
        "account": "We went to Marlock.",
        "extractions": [],
        "facts": [{"kind": "event_date", "text": "in 1963", "value": "1963", "precision": "year"}],
        "status": "draft",
        "chat": {
            "who": "Alex",
            "stage": "story",
            "entries": [{"kind": "initial", "text": "We went to Marlock."}],
            "questions": [],
            "questionIndex": 0,
            "facts": [{"kind": "event_date", "text": "in 1963", "value": "1963", "precision": "year"}],
            "extractions": [],
        },
    }
    first_status, first = server.post("/api/save", payload)
    assert first_status == 200
    story_id = first["id"]
    # the narrator keeps talking — the next auto-save carries the same id
    payload["id"] = story_id
    payload["account"] = "We went to Marlock. And Mum came too."
    payload["chat"]["entries"] = [
        {"kind": "initial", "text": "We went to Marlock."},
        {"kind": "add", "text": "And Mum came too."},
    ]
    second_status, second = server.post("/api/save", payload)
    assert second_status == 200
    assert second["id"] == story_id

    # append-only: both versions exist; the newest wins
    assert server.store.exists(f"assets/{story_id}/item.json")
    assert server.store.exists(f"assets/{story_id}/item-2.json")
    latest = json.loads(server.store.read(f"assets/{story_id}/item-2.json"))
    assert "story" not in latest  # primary content is a file, never a field
    assert latest["chat"]["entries"][1]["text"] == "And Mum came too."
    # the story content versions with its sidecar: v1 -> story.txt, v2 -> story-2.txt
    assert server.store.read(f"assets/{story_id}/story.txt") == "We went to Marlock."
    assert server.store.read(f"assets/{story_id}/story-2.txt") == "We went to Marlock. And Mum came too."
    # the projection has exactly one entry for the story
    index = json.loads((server.data_dir / "index.json").read_text(encoding="utf-8"))
    assert [it["id"] for it in index["items"]].count(story_id) == 1


def test_delete_tombstones_a_draft_and_drops_it_from_the_projection(server: ServerFixture) -> None:
    """Abandon: the draft is superseded with a tombstone (append-only — the
    files stay, the newest version says deleted) and vanishes from the
    projection (user)."""
    status, body = server.post(
        "/api/save",
        {
            "anchor": {"kind": "theme", "id": "t-the-boats", "name": "The boats"},
            "who": "Alex",
            "title": "A half-told memory",
            "account": "We went to Marlock.",
            "extractions": [],
            "facts": [{"kind": "event_date", "text": "in 1963", "value": "1963", "precision": "year"}],
            "status": "draft",
        },
    )
    assert status == 200
    story_id = body["id"]

    del_status, del_body = server.post(
        "/api/delete",
        {"id": story_id, "reason": "abandoned by the narrator"},
    )
    assert del_status == 200, del_body
    assert del_body["ok"] is True

    # the sidecar chain grew a tombstone — the newest version says deleted
    from tools.archive import Archive

    arc = Archive(server.store)
    versions = arc._sidecar_versions(story_id)
    latest = json.loads(server.store.read(arc._sidecar_path(story_id, max(versions))))
    assert latest["status"] == "deleted"
    # and the projection no longer holds it
    index = json.loads((server.data_dir / "index.json").read_text(encoding="utf-8"))
    assert all(it["id"] != story_id for it in index["items"])


def test_write_apis_reject_a_foreign_origin(server: ServerFixture) -> None:
    """CSRF guard: a web page on another origin must not be able to POST to
    the household capture server."""
    from urllib.request import Request

    req = Request(
        f"http://127.0.0.1:{server.port}/api/save",
        data=json.dumps(
            {
                "anchor": {"kind": "theme", "id": "t-the-boats", "name": "The boats"},
                "who": "Alex",
                "title": "T",
                "account": "x",
                "extractions": [],
                "facts": [{"kind": "event_date", "text": "in 1963", "value": "1963", "precision": "year"}],
                "status": "draft",
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json", "Origin": "https://evil.example"},
        method="POST",
    )
    with pytest.raises(Exception) as exc:
        urllib.request.urlopen(req, timeout=5)
    assert getattr(exc.value, "code", None) == 403

    # no Origin (curl, the server's own app) still works
    status, body = server.post(
        "/api/save",
        {
            "anchor": {"kind": "theme", "id": "t-the-boats", "name": "The boats"},
            "who": "Alex",
            "title": "T",
            "account": "x",
            "extractions": [],
            "facts": [{"kind": "event_date", "text": "in 1963", "value": "1963", "precision": "year"}],
            "status": "draft",
        },
    )
    assert status == 200, body


def test_data_files_require_a_session(server: ServerFixture) -> None:
    """The archive's data is the private layer (user: content gated behind
    sign-in) — a session is required to read people.json, and the app shell
    stays public so the gate can load."""
    status, body = server.get("/data/people.json")
    assert status == 401
    assert b"sign in" in body
    status, body = server.get("/data/people.json", cookie=server.cookie)
    assert status == 200
    assert b"Alex Hale" in body
    status, _ = server.get("/")  # the shell loads for the sign-in screen
    assert status == 200


def test_auth_callback_decodes_the_percent_encoded_code(server: ServerFixture) -> None:
    """Google returns the auth code percent-encoded (4%2F0AXE…) — the
    callback must decode it before the token exchange, or Google answers
    'Malformed auth code' (the invalid_grant)."""

    # an unregistered state fails cleanly BEFORE the exchange — this pins
    # the decode path by driving the callback with a real encoded shape
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        @override
        def redirect_request(self, *args, **kwargs):  # noqa: ARG002
            return None

    opener = urllib.request.build_opener(NoRedirect)
    try:
        resp = opener.open(f"http://127.0.0.1:{server.port}/api/auth/callback?state=nope&code=4%2F0AXEQxIB", timeout=5)
        status = resp.status
    except urllib.error.HTTPError as e:
        status = e.code
    assert status in (302, 307)  # redirected (auth_error), never a crash


def _seed_pending(server: ServerFixture) -> None:
    """A mini people table with a proposed person wired to a confirmed one —
    the import's pending state."""
    server.archive.save_identity(
        "people",
        validate_identity(
            "people",
            {
                "people": [
                    {"id": "p-alex", "name": "Alex Hale"},
                    {"id": "p-robert", "name": "Quentin Whitlock"},
                    {"id": "p-judith", "name": "Pearl Whitlock", "status": "proposed"},
                ],
                "relationships": [{"a": "p-robert", "b": "p-judith", "kind": "spouse"}],
            },
        ),
    )
    # the confirm/dismiss endpoints republish the projection, which needs the
    # whole identity set — a realistic archive
    server.archive.save_identity("places", validate_identity("places", {"places": []}))
    server.archive.save_identity("themes", validate_identity("themes", {"themes": []}))
    server.archive.save_identity("orgs", validate_identity("orgs", {"orgs": []}))
    server.archive.save_identity(
        "imports",
        validate_identity(
            "imports",
            {"imports": [{"id": "import-documents", "title": "The document import", "status": "pending"}]},
        ),
    )


def test_decide_attested_flips_proposed_to_confirmed(server: ServerFixture) -> None:
    """Attested = the reviewer's own verified word — the status drops, the
    import's relation text stays untouched."""
    _seed_pending(server)
    status, body = server.post(
        "/api/review/decide", {"session_id": "import-documents", "person_id": "p-judith", "decision": "attested"}
    )
    assert status == 200
    assert body["ok"] is True
    assert "status" not in body["person"]  # confirmed records omit the status key
    # the response carries the server's accurate remaining count — the
    # client's projection is stale until reload, so the count comes from
    # here (user: the count must always be accurate)
    assert body["pending"] == 0  # the seed's only proposed person is now decided
    table = server.archive.get_identity("people")
    assert table is not None
    person = table.record("p-judith")
    assert person is not None
    assert "status" not in person.to_dict()  # a confirmed record omits the status key
    assert person.relation == ""  # the attested path never rewrites the relation


def test_decide_estimated_records_the_basis_verbatim(server: ServerFixture) -> None:
    """Estimated = the reviewer's own words, named + dated."""
    _seed_pending(server)
    basis = {"text": "Grandma used to say this was the case.", "by": "Alex", "when": "2026-08-09"}
    status, body = server.post(
        "/api/review/decide",
        {"session_id": "import-documents", "person_id": "p-judith", "decision": "estimated", "basis": basis},
    )
    assert status == 200
    assert body["person"]["status"] == "estimated"
    assert body["person"]["basis"] == basis
    table = server.archive.get_identity("people")
    assert table is not None
    person = table.record("p-judith")
    assert person is not None and person.basis == basis


def test_decide_estimated_requires_a_basis(server: ServerFixture) -> None:
    _seed_pending(server)
    status, body = server.post(
        "/api/review/decide", {"session_id": "import-documents", "person_id": "p-judith", "decision": "estimated"}
    )
    assert status == 400
    assert "basis" in body["error"]


def test_decide_pending_keeps_the_imports_guess(server: ServerFixture) -> None:
    """Pending = the import's guess stays proposed, nothing changes."""
    _seed_pending(server)
    status, body = server.post(
        "/api/review/decide", {"session_id": "import-documents", "person_id": "p-judith", "decision": "pending"}
    )
    assert status == 200
    assert body["person"]["status"] == "proposed"  # unchanged
    table = server.archive.get_identity("people")
    assert table is not None
    person = table.record("p-judith")
    assert person is not None and person.status == "proposed"


def test_decide_requires_a_session(server: ServerFixture) -> None:
    _seed_pending(server)
    status, _ = server.post(
        "/api/review/decide",
        {"session_id": "import-documents", "person_id": "p-judith", "decision": "attested"},
        cookie="",
    )
    assert status == 401
    table = server.archive.get_identity("people")
    assert table is not None
    person = table.record("p-judith")
    assert person is not None and person.status == "proposed"  # untouched


def test_decide_rejects_an_unknown_decision(server: ServerFixture) -> None:
    _seed_pending(server)
    status, _ = server.post(
        "/api/review/decide", {"session_id": "import-documents", "person_id": "p-judith", "decision": "maybe"}
    )
    assert status == 400


def test_text_requires_the_ai(server: ServerFixture) -> None:
    """The free-text relevance check needs the model."""
    _seed_pending(server)
    status, body = server.post(
        "/api/review/text",
        {"session_id": "import-documents", "person_id": "p-judith", "text": "Grandma used to say so."},
    )
    assert status == 503  # no AI client on this server
    assert "AI isn't configured" in body["error"]


def test_text_requires_a_session(server: ServerFixture) -> None:
    _seed_pending(server)
    status, _ = server.post(
        "/api/review/text",
        {"session_id": "import-documents", "person_id": "p-judith", "text": "I think so."},
        cookie="",
    )
    assert status == 401


def test_text_unknown_person_404s(server: ServerFixture) -> None:
    _seed_pending(server)
    status, _ = server.post(
        "/api/review/text", {"session_id": "import-documents", "person_id": "p-nope", "text": "I think so."}
    )
    assert status == 404


def test_text_requires_person_and_text(server: ServerFixture) -> None:
    _seed_pending(server)
    status, _ = server.post(
        "/api/review/text", {"session_id": "import-documents", "person_id": "p-judith", "text": "  "}
    )
    assert status == 400


def test_decide_delete_removes_the_person_and_their_relationships(server: ServerFixture) -> None:
    _seed_pending(server)
    status, body = server.post(
        "/api/review/decide", {"session_id": "import-documents", "person_id": "p-judith", "decision": "delete"}
    )
    assert status == 200
    assert body["person"]["gone"] is True
    table = server.archive.get_identity("people")
    assert table is not None
    assert all(p.id != "p-judith" for p in table.people)
    assert all(r.a != "p-judith" and r.b != "p-judith" for r in table.relationships)
    assert any(p.id == "p-robert" for p in table.people)  # the confirmed person stays


def test_decide_delete_applies_to_an_already_confirmed_person(server: ServerFixture) -> None:
    """Every determination is applied to the record as it stands: a delete
    removes whoever is in the table, confirmed or not, and the determination is
    recorded — the family changed their mind, and the append-only chain keeps
    both determinations (2026-10-21, user)."""
    _seed_pending(server)
    status, body = server.post(
        "/api/review/decide", {"session_id": "import-documents", "person_id": "p-robert", "decision": "delete"}
    )
    assert status == 200
    assert body["ok"] is True
    assert body["person"]["gone"] is True
    assert body["message"] == "Done — Quentin Whitlock is not recorded after all."
    table = server.archive.get_identity("people")
    assert table is not None and not table.has("p-robert")
    session = server.archive.get_review_session("import-documents")
    assert session is not None
    attempt = session.current_attempt()
    assert attempt is not None
    assert [d.decision for d in attempt.decisions] == ["delete"]  # recorded


def test_decide_pending_on_an_already_confirmed_person_is_recorded(server: ServerFixture) -> None:
    """A "leave for later" on an already-confirmed person changes nothing in the
    record and is still the family's determination: it is recorded, and the
    confirmed person stays."""
    _seed_pending(server)
    status, body = server.post(
        "/api/review/decide", {"session_id": "import-documents", "person_id": "p-robert", "decision": "pending"}
    )
    assert status == 200
    assert body["ok"] is True
    assert body["person"]["id"] == "p-robert"  # the confirmed person stays
    table = server.archive.get_identity("people")
    assert table is not None and table.record("p-robert") is not None
    session = server.archive.get_review_session("import-documents")
    assert session is not None
    attempt = session.current_attempt()
    assert attempt is not None
    assert [d.decision for d in attempt.decisions] == ["pending"]  # recorded


def test_decide_a_second_delete_on_a_removed_person_is_recorded_too(server: ServerFixture) -> None:
    """A second delete (double-tap, two devices) for a person already REMOVED
    from the table: the record cannot change — nobody is there — and the
    determination is recorded like any other, never a 400 ("no person") for a
    deletion that already succeeded."""
    _seed_pending(server)
    status, body = server.post(
        "/api/review/decide", {"session_id": "import-documents", "person_id": "p-judith", "decision": "delete"}
    )
    assert status == 200
    assert body["person"]["gone"] is True
    status2, body2 = server.post(
        "/api/review/decide", {"session_id": "import-documents", "person_id": "p-judith", "decision": "delete"}
    )
    assert status2 == 200
    assert body2["ok"] is True
    assert body2["person"] is None  # the person is gone — no record returned
    session = server.archive.get_review_session("import-documents")
    assert session is not None
    attempt = session.current_attempt()
    assert attempt is not None
    assert [d.decision for d in attempt.decisions] == ["delete", "delete"]


def test_deciding_the_last_proposed_person_completes_the_session(server: ServerFixture) -> None:
    _seed_pending(server)
    status, _ = server.post(
        "/api/review/decide", {"session_id": "import-documents", "person_id": "p-judith", "decision": "attested"}
    )
    assert status == 200
    imports = server.archive.get_identity("imports")
    assert imports is not None
    assert imports.imports[0].status == "reviewed"  # nothing left pending — the session is done


# -- B1: the identity surface writes through the live store -----------------


def test_a_live_decision_writes_one_change_and_the_compat_table(live_server: ServerFixture) -> None:
    _seed_pending(live_server)
    status, body = live_server.post(
        "/api/review/decide", {"session_id": "import-documents", "person_id": "p-judith", "decision": "attested"}
    )
    assert status == 200
    assert "status" not in body["person"]  # the old wire shape, not the DB disposition
    assert body["pending"] == 0
    live = live_server.live
    assert live is not None
    stored = live.people.require("p-judith")
    assert stored.status == "confirmed"
    assert stored.version == 2
    events = live.events_for("p-judith")
    assert [event["event_type"] for event in events] == ["created", "superseded"]
    assert len({event["change_id"] for event in events[1:]}) == 1  # one change for the determination
    assert live.verify_chain() == ()
    table = live_server.archive.get_identity("people")
    assert table is not None
    exported = table.record("p-judith")
    assert exported is not None and exported.status == "confirmed"


def test_a_live_estimated_decision_exports_the_old_status_and_basis(live_server: ServerFixture) -> None:
    _seed_pending(live_server)
    basis = {"text": "Grandma used to say this was the case.", "by": "Alex", "when": "2026-08-09"}
    status, body = live_server.post(
        "/api/review/decide",
        {"session_id": "import-documents", "person_id": "p-judith", "decision": "estimated", "basis": basis},
    )
    assert status == 200
    assert body["person"]["status"] == "estimated"  # the rendering the old readers expect
    assert body["person"]["basis"] == basis
    live = live_server.live
    assert live is not None
    assert live.people.require("p-judith").basis == {"basis": "recollection", "confidence": "possible", **basis}
    table = live_server.archive.get_identity("people")
    assert table is not None
    exported = table.record("p-judith")
    assert exported is not None and exported.status == "estimated" and exported.basis == basis


def test_a_live_delete_removes_the_person_and_their_edges(live_server: ServerFixture) -> None:
    _seed_pending(live_server)
    status, body = live_server.post(
        "/api/review/decide", {"session_id": "import-documents", "person_id": "p-judith", "decision": "delete"}
    )
    assert status == 200
    assert body["person"]["gone"] is True
    live = live_server.live
    assert live is not None
    assert live.people.get("p-judith") is None
    assert live.relationships.get("rel-p-robert-p-judith-spouse") is None
    table = live_server.archive.get_identity("people")
    assert table is not None
    assert all(person.id != "p-judith" for person in table.people)
    assert all(edge.a != "p-judith" and edge.b != "p-judith" for edge in table.relationships)


def test_a_live_decision_needs_the_session(live_server: ServerFixture) -> None:
    _seed_pending(live_server)
    status, _ = live_server.post(
        "/api/review/decide",
        {"session_id": "import-documents", "person_id": "p-judith", "decision": "attested"},
        cookie="",
    )
    assert status == 401
    live = live_server.live
    assert live is not None
    assert live.people.get("p-judith") is None  # the refusal wrote nothing, not even the catch-up


def test_a_live_decision_rejects_a_stale_session_before_any_mutation(live_server: ServerFixture) -> None:
    _seed_pending(live_server)
    status, _ = live_server.post(
        "/api/review/decide", {"session_id": "import-nope", "person_id": "p-judith", "decision": "attested"}
    )
    assert status == 404
    live = live_server.live
    assert live is not None
    assert live.people.get("p-judith") is None  # the refusal wrote nothing, not even the catch-up


def test_a_live_review_turn_persists_in_the_service(live_server: ServerFixture) -> None:
    _seed_pending(live_server)
    status, _ = live_server.post("/api/review/start", {"session_id": "import-documents"})
    assert status == 200
    status, _ = live_server.post(
        "/api/review/message", {"session_id": "import-documents", "role": "user", "text": "I think so."}
    )
    assert status == 200
    live = live_server.live
    assert live is not None
    session = live.reviews.session("import-documents")
    assert session is not None
    assert session.attempts[0].messages[0].text == "I think so."
    table = live_server.archive.get_identity("imports")
    assert table is not None
    assert table.imports[0].attempts[0].messages[0].text == "I think so."


def test_a_live_save_writes_one_change_and_the_compat_sidecar(live_server: ServerFixture) -> None:
    status, body = live_server.post(
        "/api/save",
        {
            "anchor": {"kind": "item", "id": "letter-1963-05-14", "name": "A week in the flat"},
            "who": "Alex",
            "title": "The damp winter",
            "account": "The flat was damp that winter, in 1963.",
            "extractions": [
                {"kind": "place", "name": "Marlock", "match": "pl-marlock", "bucket": "proposed", "reason": ""}
            ],
            "facts": [{"kind": "event_date", "text": "in 1963", "value": "1963", "precision": "year"}],
            "status": "catalogued",
        },
    )
    assert status == 200, body
    story_id = body["id"]
    live = live_server.live
    assert live is not None
    assert live.items.require(story_id).version == 1
    assert [event["event_type"] for event in live.events_for(story_id, entity_kind="item")] == ["created"]
    assert live.items.content(story_id, "story") is not None
    sidecar = json.loads(live_server.store.read(f"assets/{story_id}/item.json"))
    assert sidecar["status"] == "catalogued"
    assert "story" not in sidecar  # the text is a content file, not a JSON field
    assert {"kind": "story", "file": "story.txt", "caption": "The story, verbatim"} in sidecar["assets"]


def test_a_live_save_queues_a_new_person_through_the_service(live_server: ServerFixture) -> None:
    """B3b: the capture surface's new person is one `Change` (a `proposed` row)
    and the old queue file the projection and the old readers list."""
    status, body = live_server.post(
        "/api/save",
        {
            "anchor": {"kind": "item", "id": "letter-1963-05-14", "name": "A week in the flat"},
            "who": "Alex",
            "title": "The damp winter",
            "account": "Grandma came that winter, in 1963.",
            "extractions": [{"kind": "person", "name": "Grandma", "match": None, "bucket": "proposed", "reason": ""}],
            "facts": [{"kind": "event_date", "text": "in 1963", "value": "1963", "precision": "year"}],
            "status": "catalogued",
        },
    )
    assert status == 200, body
    live = live_server.live
    assert live is not None
    minted = [person for person in body["people"] if person["name"] == "Grandma"]
    assert minted, body
    person_id = minted[0]["id"]
    stored = live.people.require(person_id)
    assert stored.status == "proposed"
    queued = json.loads(live_server.store.read(f"proposed/people/{person_id}.json"))
    assert queued["name"] == "Grandma" and queued["status"] == "proposed"
    table = live_server.archive.get_identity("people")
    assert table is not None and table.record(person_id) is not None


def test_a_live_delete_tombstones_through_the_service(live_server: ServerFixture) -> None:
    status, body = live_server.post(
        "/api/save",
        {
            "anchor": {"kind": "item", "id": "letter-1963-05-14", "name": "A week in the flat"},
            "who": "Alex",
            "title": "A half-told memory",
            "account": "We went to Marlock.",
            "extractions": [],
            "facts": [{"kind": "event_date", "text": "in 1963", "value": "1963", "precision": "year"}],
            "status": "draft",
        },
    )
    assert status == 200, body
    story_id = body["id"]
    live = live_server.live
    assert live is not None
    status, deleted = live_server.post("/api/delete", {"id": story_id, "reason": "abandoned by the narrator"})
    assert status == 200, deleted
    assert live.items.require(story_id).status == "deleted"
    assert live_server.archive.get_item(story_id) is None
    tombstone = json.loads(live_server.store.read(f"assets/{story_id}/item-2.json"))
    assert tombstone["status"] == "deleted" and tombstone["reason"] == "abandoned by the narrator"


def test_a_live_decision_catches_up_a_proposal_the_old_path_wrote(live_server: ServerFixture) -> None:
    _seed_pending(live_server)
    live = live_server.live
    assert live is not None
    # the identify pass (still on the file path in B1) adds a proposal
    live_server.archive.save_identity(
        "people",
        validate_identity(
            "people",
            {
                "people": [
                    {"id": "p-alex", "name": "Alex Hale"},
                    {"id": "p-robert", "name": "Quentin Whitlock"},
                    {"id": "p-judith", "name": "Pearl Whitlock", "status": "proposed"},
                    {"id": "p-harriet", "name": "Harriet Wells", "status": "proposed"},
                ],
                "relationships": [{"a": "p-robert", "b": "p-judith", "kind": "spouse"}],
            },
        ),
    )
    assert live.people.get("p-harriet") is None
    status, body = live_server.post(
        "/api/review/decide", {"session_id": "import-documents", "person_id": "p-harriet", "decision": "attested"}
    )
    assert status == 200
    assert live.people.require("p-harriet").status == "confirmed"


def test_review_reads_the_transcription_not_the_summary(server: ServerFixture) -> None:
    """(user: "extremely bad at identifying the relevant part of the
    document to quote when explaining the attestation"): the review's facts
    must carry the VERBATIM transcription — the text the family sees in the
    claim and the item page — never the sidecar's archival summary."""
    _seed_pending(server)
    seen: dict[str, str] = {}

    class FakeChat:
        def chat(self, system: str, user: str, *, thinking: bool = False) -> str:  # noqa: ARG002 — the harness signature
            seen["user"] = user
            return (
                '{"relevant": true, "contradiction": {"found": false, "detail": ""}, '
                '"confidence": "think_so", "note": "fine", "findings": [], "question": ""}'
            )

    # a second server over the same store, with the model client injected
    # (DI) — the fixture's server deliberately runs clientless
    server2 = ServerFixture(server.data_dir, server.store, client=FakeChat())
    try:
        _seed_pending(server2)  # the second init re-seeded the people table
        server2.archive.save_item(
            Item.from_dict(
                {
                    "id": "doc-2001-email",
                    "title": "The 2001 email",
                    "date": "2001-02-07",
                    "date_precision": "exact",
                    "type": "letter",
                    "status": "catalogued",
                    "people": [{"id": "p-judith", "status": "confirmed"}],
                }
            ),
            # the summary (the sidecar's story field) and the transcription
            # (the verbatim capture) are DIFFERENT texts — the review must
            # read the transcription. The sidecar has no story at all here,
            # and the prompt still must find the item
            content={
                "transcription": (
                    "The family archive has grown dusty over the years. "
                    "The notes my aunt left say that Pearl Whitlock was the one who kept the photographs."
                )
            },
        )
        status, body = server2.post(
            "/api/review/text",
            {"session_id": "import-documents", "person_id": "p-judith", "text": "Grandma used to say so."},
        )
        assert status == 200
        # the response carries ONLY the UI's fields — the model's raw
        # output, tool trace, and prompt texts never reach the browser
        # (R7)
        assert set(body) == {"ok", "message", "relevant", "contradiction", "confidence", "note", "findings", "question"}
        # the model's prompt carries the transcription's own words — never
        # the summary, and never a bare "no documents" note
        assert "Pearl Whitlock was the one who kept the photographs" in seen["user"]
        # AND the reviewer's own words — the loop must never overwrite the
        # request's text with an item's content
        assert "Grandma used to say so." in seen["user"]
        imports = server2.archive.get_identity("imports")
        assert imports is not None
        session = next(s for s in imports.imports if s.id == "import-documents")
        messages = session.attempts[-1].messages
        user_lines = [m.text for m in messages if m.role == "user"]
        # the transcript holds the user's words verbatim, EXACTLY ONCE —
        # the record-before-the-call fix must not double them on the
        # success path
        assert user_lines == ["Grandma used to say so."]
    finally:
        server2.close()


def test_review_reads_transcription_only_mentions(server: ServerFixture) -> None:
    """The metadata pre-filter must NOT drop an item whose only mention of
    the person lives in the verbatim transcription (a draft with no people
    refs and no story yet) — the bounded first-chunk read settles the
    shortlist, so the model can still attest from the document's own words.
    The sidecar story alone must never be the item's only window."""
    _seed_pending(server)
    seen: dict[str, str] = {}

    class FakeChat:
        def chat(self, system: str, user: str, *, thinking: bool = False) -> str:  # noqa: ARG002
            seen["user"] = user
            return (
                '{"relevant": true, "contradiction": {"found": false, "detail": ""}, '
                '"confidence": "think_so", "note": "fine", "findings": [], "question": ""}'
            )

    server2 = ServerFixture(server.data_dir, server.store, client=FakeChat())
    try:
        _seed_pending(server2)
        server2.archive.save_item(
            Item.from_dict(
                {
                    "id": "doc-draft-letter",
                    "title": "A draft letter",
                    "date": "2001-02-07",
                    "date_precision": "exact",
                    "type": "letter",
                    "status": "catalogued",
                    "transcription_status": "draft",
                    # NO people refs, NO sidecar story — the only mention of the
                    # person is inside the transcription text itself
                }
            ),
            content={"transcription": "The letter says Pearl was the one who kept the photographs."},
        )
        status, _ = server2.post(
            "/api/review/text",
            {"session_id": "import-documents", "person_id": "p-judith", "text": "Grandma used to say so."},
        )
        assert status == 200
        # the document's own words reached the model — the draft's prose
        # named the person, and the bounded read did not skip it
        assert "Pearl was the one who kept the photographs" in seen["user"]
    finally:
        server2.close()


def test_review_shortlist_matches_mentions_case_insensitively(server: ServerFixture) -> None:
    """The shortlist filter matches the person's name case-insensitively
    against story/transcription — an item whose only mention is lowercased
    (OCR text, an uppercase heading) must not be silently dropped, or the
    document becomes invisible to the investigation. The needles and the
    compared text are lowercased."""
    _seed_pending(server)
    seen: dict[str, str] = {}

    class FakeChat:
        def chat(self, system: str, user: str, *, thinking: bool = False) -> str:  # noqa: ARG002
            seen["user"] = user
            return (
                '{"relevant": true, "contradiction": {"found": false, "detail": ""}, '
                '"confidence": "think_so", "note": "fine", "findings": [], "question": ""}'
            )

    server2 = ServerFixture(server.data_dir, server.store, client=FakeChat())
    try:
        _seed_pending(server2)
        server2.archive.save_item(
            Item.from_dict(
                {
                    "id": "doc-lowercase-letter",
                    "title": "A letter",
                    "date": "2001-02-07",
                    "date_precision": "exact",
                    "type": "letter",
                    "status": "catalogued",
                    "transcription_status": "draft",
                    # NO people refs, NO sidecar story — and the only textual
                    # mention of the person is lowercased
                }
            ),
            content={"transcription": "the notes say pearl was the one who kept the photographs."},
        )
        status, _ = server2.post(
            "/api/review/text",
            {"session_id": "import-documents", "person_id": "p-judith", "text": "Grandma used to say so."},
        )
        assert status == 200
        # the lowercased mention still reached the model — the document is
        # not hidden by the case of its own words
        assert "pearl was the one who kept the photographs" in seen["user"]
    finally:
        server2.close()


def test_decide_rejects_a_stale_session_before_any_mutation(server: ServerFixture) -> None:
    """The session is validated before any mutation: a stale session_id gets
    a 404 and the person is untouched."""
    _seed_pending(server)
    status, body = server.post(
        "/api/review/decide",
        {"session_id": "import-nope", "person_id": "p-judith", "decision": "attested"},
    )
    assert status == 404
    assert "no import session" in body["error"]
    table = server.archive.get_identity("people")
    assert table is not None
    person = table.record("p-judith")
    assert person is not None and person.status == "proposed"  # untouched


def test_review_text_keeps_the_words_when_the_model_call_fails(server: ServerFixture) -> None:
    """The family's line joins the transcript the moment it arrives — an AI
    outage (ElicitationError) must not lose their words; the transcript
    equals what the family saw (R7/R8). The failure returns 422 but the
    record stands."""
    _seed_pending(server)

    class FailingChat:
        def chat(self, system: str, user: str, *, thinking: bool = False) -> str:  # noqa: ARG002
            raise ElicitationError("the model is down")

    server2 = ServerFixture(server.data_dir, server.store, client=FailingChat())
    try:
        _seed_pending(server2)
        status, body = server2.post(
            "/api/review/text",
            {"session_id": "import-documents", "person_id": "p-judith", "text": "Grandma used to say so."},
        )
        assert status == 422
        assert "model is down" in body["error"]
        imports = server2.archive.get_identity("imports")
        assert imports is not None
        session = next(s for s in imports.imports if s.id == "import-documents")
        messages = session.attempts[-1].messages
        user_line = next(m.text for m in messages if m.role == "user")
        assert user_line == "Grandma used to say so."  # never lost to the outage
    finally:
        server2.close()


def test_start_returns_the_lines_already_recorded_in_the_attempt(server: ServerFixture) -> None:
    """The start response carries the current attempt's recorded lines, so
    the app records only what's new — the transcript never duplicates the
    opening or a claim."""
    _seed_pending(server)
    archive = server.archive
    archive.record_review_message("import-documents", "assistant", "Thanks for coming back.", "2026-08-10")
    archive.record_review_message("import-documents", "assistant", "Next: Pearl Whitlock.", "2026-08-10")
    status, body = server.post("/api/review/start", {"session_id": "import-documents"})
    assert status == 200
    assert body["messages"] == ["Thanks for coming back.", "Next: Pearl Whitlock."]


def _seed_sync_batch(fixture: ServerFixture, batch_id: str = "adopt-0001") -> None:
    """A batch with a guess the drafts endpoint serves, and a registry record
    the confirmation receiver updates."""
    import json as _json

    guess = fixture.work_dir / batch_id / "ocr-guess"
    guess.mkdir(parents=True)
    (guess / "p1.txt").write_text("Chère Maman.", encoding="utf-8")
    (guess / "boundaries.json").write_text(
        _json.dumps([{"pages": ["p1.jpg"], "greeting": "Chère Maman.", "signoff": None}]), encoding="utf-8"
    )
    fixture.registry_dir.mkdir(parents=True)
    (fixture.registry_dir / f"{batch_id}.json").write_text(
        _json.dumps(
            {
                "batch_id": batch_id,
                "path": str(fixture.data_dir),
                "status": "review",
                "boundaries": None,
                "pages": {"p1.jpg": "hash-1", "p2.jpg": "hash-2"},
            }
        ),
        encoding="utf-8",
    )


def test_sync_drafts_requires_a_session(server: ServerFixture) -> None:
    status, _ = server.get("/api/sync/batch/adopt-0001/drafts")
    assert status == 401


def test_sync_drafts_serves_the_guessed_texts(server: ServerFixture) -> None:
    import json as _json

    _seed_sync_batch(server)
    status, raw = server.get("/api/sync/batch/adopt-0001/drafts", cookie=server.cookie)
    assert status == 200
    body = _json.loads(raw.decode("utf-8"))
    assert body["documents"][0]["texts"]["p1.jpg"] == "Chère Maman."
    assert body["documents"][0]["greeting"] == "Chère Maman."


def test_sync_drafts_page_scope_returns_one_page(server: ServerFixture) -> None:
    """The row screen opens one page; it gets that page, not the batch's
    whole drafts payload (381 KB was a 12-second client parse on a phone)."""
    import json as _json

    _seed_sync_batch(server)
    guess = server.work_dir / "adopt-0001" / "ocr-guess"
    (guess / "p2.txt").write_text("Another page.", encoding="utf-8")
    for page in ("p1", "p2"):
        (guess / f"{page}.row-adjustments.json").write_text(_json.dumps({"lines": []}), encoding="utf-8")
        (guess / f"{page}.rows-adjusted.json").write_text(_json.dumps({"rows": []}), encoding="utf-8")
    (guess / "boundaries.json").write_text(
        _json.dumps([{"pages": ["p1.jpg", "p2.jpg"], "greeting": "Chère Maman.", "signoff": None}]),
        encoding="utf-8",
    )
    status, raw = server.get("/api/sync/batch/adopt-0001/drafts?doc=0&page=0", cookie=server.cookie)
    assert status == 200
    body = _json.loads(raw.decode("utf-8"))
    assert len(body["documents"]) == 1
    document = body["documents"][0]
    assert document["pages"] == ["p1.jpg", "p2.jpg"]
    assert document["texts"] == {"p1.jpg": "Chère Maman."}
    assert document["greeting"] == "Chère Maman."
    # the whole batch's checked set survives the one-page cut
    assert document["checked_pages"] == ["p1.jpg", "p2.jpg"]
    status, _ = server.get("/api/sync/batch/adopt-0001/drafts?doc=0&page=99", cookie=server.cookie)
    assert status == 400


def test_sync_drafts_hides_photo_only_documents(server: ServerFixture) -> None:
    """The transcription review shows only documents with a text page,
    and only their TEXT pages (user): a standalone photo has nothing to
    transcribe — it belongs to the people/places identification flow, which
    reads the same structure unfiltered. A two-sided item's picture side
    stays in the structure but the review pages through only its text side."""
    import json as _json

    guess = server.work_dir / "adopt-0001" / "ocr-guess"
    guess.mkdir(parents=True)
    (guess / "back.txt").write_text("Chère Maman.", encoding="utf-8")
    (guess / "boundaries.json").write_text(
        _json.dumps(
            [
                {"pages": ["photo1.jpg"], "greeting": None, "signoff": None},
                {"pages": ["front.jpg", "back.jpg"], "greeting": "Chère Maman.", "signoff": None},
            ]
        ),
        encoding="utf-8",
    )
    server.registry_dir.mkdir(parents=True)
    (server.registry_dir / "adopt-0001.json").write_text(
        _json.dumps(
            {
                "batch_id": "adopt-0001",
                "path": str(server.data_dir),
                "status": "review",
                "boundaries": [
                    {"pages": ["photo1.jpg"], "status": "review"},
                    {"pages": ["front.jpg", "back.jpg"], "status": "review"},
                ],
            }
        ),
        encoding="utf-8",
    )
    status, raw = server.get("/api/sync/batch/adopt-0001/drafts", cookie=server.cookie)
    assert status == 200
    body = _json.loads(raw.decode("utf-8"))
    docs = body["documents"]
    assert [d["pages"] for d in docs] == [["back.jpg"]]


def test_sync_drafts_rejects_a_traversal_batch_id(server: ServerFixture) -> None:
    _seed_sync_batch(server)
    # the raw-slash form dies at the router (404); every encoded form
    # reaches the endpoint and the _BATCH_ID regex rejects it (400) — the
    # endpoint validation is the real defense for all of them
    status, _ = server.get("/api/sync/batch/..%252F..%252Fregistry/drafts", cookie=server.cookie)
    assert status == 400


def test_sync_confirmations_requires_a_session(server: ServerFixture) -> None:
    status, _ = server.post("/api/sync/confirmations", {"batch_id": "adopt-0001"}, cookie="")
    assert status == 401


def test_sync_confirmations_mint_the_archive_item(server: ServerFixture) -> None:
    """An agreed document becomes an archive item: the title and date the
    reviewer gave, and the corrected text as the item's transcription. The
    registry's boundary carries the item it became."""
    _seed_sync_batch(server)
    status, body = server.post(
        "/api/sync/confirmations",
        {
            "batch_id": "adopt-0001",
            "doc_index": 1,
            "pages": ["p1.jpg"],
            "text": "Chère Maman.",
            "status": "confirmed",
            "confirmed_at": "2026-08-14T00:00:00Z",
            "title": "A letter to Maman",
            "date": "1963-05-14",
            "date_precision": "exact",
        },
    )
    assert status == 200
    assert body["ok"] is True and body["item_id"] == "doc-1963-05-14"
    import json as _json

    record = _json.loads((server.registry_dir / "adopt-0001.json").read_text(encoding="utf-8"))
    assert record["boundaries"][0]["status"] == "confirmed"
    assert record["boundaries"][0]["item_id"] == "doc-1963-05-14"
    item = _json.loads(server.store.read("assets/doc-1963-05-14/item.json"))
    assert item["title"] == "A letter to Maman" and item["date"] == "1963-05-14"
    assert server.store.read("assets/doc-1963-05-14/transcription.txt") == "Chère Maman."


def test_sync_confirmations_rejects_a_bad_shape(server: ServerFixture) -> None:
    status, body = server.post(
        "/api/sync/confirmations",
        {"batch_id": "adopt-0001", "doc_index": 1, "pages": [], "text": "x"},
    )
    assert status == 400


def test_sync_confirmations_supersede_the_item_on_re_agreement(server: ServerFixture) -> None:
    """Re-agreeing the same document (a corrected text) supersedes its item —
    one item per document, never a second one."""
    _seed_sync_batch(server)
    payload = {
        "batch_id": "adopt-0001",
        "doc_index": 1,
        "pages": ["p1.jpg"],
        "text": "Chère Maman.",
        "status": "confirmed",
        "confirmed_at": "2026-08-14T00:00:00Z",
        "title": "A letter to Maman",
        "date": "1963-05-14",
        "date_precision": "exact",
    }
    first, body = server.post("/api/sync/confirmations", payload)
    assert first == 200 and body["item_id"] == "doc-1963-05-14"
    corrected = {**payload, "text": "Chère Maman, nous sommes arrivés."}
    second, body = server.post("/api/sync/confirmations", corrected)
    assert second == 200 and body["item_id"] == "doc-1963-05-14"
    assert server.store.read("assets/doc-1963-05-14/transcription-2.txt") == "Chère Maman, nous sommes arrivés."
    assert [i for i in server.store.list("assets") if i.startswith("assets/doc-1963-05-14/")].count(
        "assets/doc-1963-05-14/item.json"
    ) == 1
    assert server.store.list("assets").count("assets/doc-1963-05-14-2/item.json") == 0


def test_sync_confirmations_ignore_a_client_supplied_item_id(server: ServerFixture) -> None:
    """The item id comes from the registry alone: a request carrying one must
    neither adopt another document's item nor mint a document under a chosen
    id."""
    _seed_sync_batch(server)
    payload = {
        "batch_id": "adopt-0001",
        "doc_index": 1,
        "pages": ["p1.jpg"],
        "text": "Chère Maman.",
        "status": "confirmed",
        "confirmed_at": "2026-08-14T00:00:00Z",
        "title": "A letter to Maman",
        "date": "1963-05-14",
        "date_precision": "exact",
        "item_id": "doc-1900-01-01",
    }
    status, body = server.post("/api/sync/confirmations", payload)
    assert status == 200
    assert body["item_id"] == "doc-1963-05-14"  # the document's own, never the client's
    assert not [i for i in server.store.list("assets") if i.startswith("assets/doc-1900-01-01/")]


def test_sync_confirmations_need_the_documents_own_facts(server: ServerFixture) -> None:
    """A document cannot become an item without a title and a date, so an
    agreement without them is refused, with the reason — never an untitled
    item in the archive."""
    _seed_sync_batch(server)
    for missing in ({"title": ""}, {"date": ""}, {"date_precision": "sometimes"}):
        payload = {
            "batch_id": "adopt-0001",
            "doc_index": 1,
            "pages": ["p1.jpg"],
            "text": "Chère Maman.",
            "status": "confirmed",
            "confirmed_at": "2026-08-14T00:00:00Z",
            "title": "A letter",
            "date": "1963-05-14",
            "date_precision": "exact",
            **missing,
        }
        status, body = server.post("/api/sync/confirmations", payload)
        assert status == 400, (missing, body)
    assert (server.registry_dir / "adopt-0001.json").is_file()


def test_sync_batches_requires_a_session(server: ServerFixture) -> None:
    status, _ = server.get("/api/sync/batches")
    assert status == 401


def test_sync_batches_lists_the_adopted_batches(server: ServerFixture) -> None:
    import json as _json

    _seed_sync_batch(server)
    (server.registry_dir / "adopt-0002.json").write_text(
        _json.dumps({"batch_id": "adopt-0002", "status": "review", "arrived_at": "2026-08-15T00:00:00Z"}),
        encoding="utf-8",
    )
    status, raw = server.get("/api/sync/batches", cookie=server.cookie)
    assert status == 200
    body = _json.loads(raw.decode("utf-8"))
    ids = [b["batch_id"] for b in body["batches"]]
    assert ids == ["adopt-0002", "adopt-0001"]  # newest first


def test_sync_batches_lists_the_pages_waiting_on_a_row_check(server: ServerFixture) -> None:
    """A page waits on a person only once its draft rows exist: a read page
    with no recorded check is in the queue, a checked page has left it, and a
    page the read stage has not reached is the machine's, not a person's."""
    import json as _json

    _seed_sync_batch(server)
    record_path = server.registry_dir / "adopt-0001.json"
    record = _json.loads(record_path.read_text(encoding="utf-8"))
    record["pages"]["p3.jpg"] = "hash-3"  # never read: no draft rows, so no person waits
    record_path.write_text(_json.dumps(record), encoding="utf-8")
    guess = server.work_dir / "adopt-0001" / "ocr-guess"
    for page in ("p1", "p2"):
        (guess / f"{page}.rows.json").write_text(_json.dumps({"page": f"{page}.jpg"}), encoding="utf-8")
        (guess / f"{page}.words.json").write_text(_json.dumps({"words": []}), encoding="utf-8")
    (guess / "p1.row-adjustments.json").write_text(_json.dumps({"lines": []}), encoding="utf-8")
    (guess / "p1.rows-adjusted.json").write_text(_json.dumps({"rows": []}), encoding="utf-8")
    status, raw = server.get("/api/sync/batches", cookie=server.cookie)
    assert status == 200
    body = _json.loads(raw.decode("utf-8"))
    assert body["batches"][0]["pages_pending"] == ["p2.jpg"]  # p1 is checked, p3 has no reading


def test_sync_batches_refuses_a_missing_workspace(tmp_path: Path) -> None:
    """The review workspace is an operator error when it is absent — an
    unmounted Loft disk must not read as "no review work" (the review hub
    would show only the import/identify queues and silently lose the rows)."""
    fixture = ServerFixture(make_app_data(tmp_path), MemoryStore(), registry_dir=tmp_path / "not-mounted" / "registry")
    try:
        status, raw = fixture.get("/api/sync/batches", cookie=fixture.cookie)
        assert status == 503
        assert b"not available" in raw
    finally:
        fixture.close()


def test_sync_page_requires_a_session(server: ServerFixture) -> None:
    status, _ = server.get("/api/sync/batch/adopt-0001/page/p1.jpg")
    assert status == 401


def test_sync_page_serves_the_view_image(server: ServerFixture) -> None:
    _seed_sync_batch(server)
    oriented = server.work_dir / "adopt-0001" / "oriented"
    oriented.mkdir(parents=True)
    Image.new("RGB", (2600, 4000), (200, 180, 150)).save(oriented / "p1.jpg", "JPEG")
    status, raw = server.get("/api/sync/batch/adopt-0001/page/p1.jpg", cookie=server.cookie)
    assert status == 200
    assert raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
    with Image.open(io.BytesIO(raw)) as view:
        # the boxes still live in the page's own pixel space
        assert view.size == (2600, 4000)


def test_sync_page_rejects_unknown_and_unsafe_names(server: ServerFixture) -> None:
    _seed_sync_batch(server)
    status, _ = server.get("/api/sync/batch/adopt-0001/page/nope.jpg", cookie=server.cookie)
    assert status == 404
    status, _ = server.get("/api/sync/batch/adopt-0001/page/..%252Fetc%252Fpasswd", cookie=server.cookie)
    assert status == 400  # the endpoint's own guard rejects every encoded form that reaches it
    status, _ = server.get("/api/sync/batch/..%252Fregistry/page/p1.jpg", cookie=server.cookie)
    assert status == 400


def test_sync_pending_requires_a_session(server: ServerFixture) -> None:
    status, _ = server.get("/api/sync/pending")
    assert status == 401


def test_sync_pending_catch_up_round_trip(server: ServerFixture) -> None:
    import json as _json

    item_id = server.outbox.add(
        {
            "batch_id": "adopt-0001",
            "doc_index": 1,
            "pages": ["p1.jpg"],
            "text": "Chère Maman.",
            "status": "confirmed",
            "confirmed_at": "2026-08-14T00:00:00Z",
            "title": "A letter to Maman",
            "date": "1963-05-14",
            "date_precision": "exact",
        }
    )
    status, raw = server.get("/api/sync/pending", cookie=server.cookie)
    assert status == 200
    body = _json.loads(raw.decode("utf-8"))
    assert [p["id"] for p in body["pending"]] == [item_id]
    status, _ = server.post("/api/sync/pending/received", {"ids": [item_id]})
    assert status == 200
    assert server.outbox.pending() == []


def test_sync_confirmations_rejects_a_traversal_batch_id(server: ServerFixture) -> None:
    # the batch_id arrives in the JSON body — the router cannot help here;
    # the write path's own validation must reject it before anything lands
    status, _ = server.post(
        "/api/sync/confirmations",
        {
            "batch_id": "../registry",
            "doc_index": 1,
            "pages": ["p1.jpg"],
            "text": "x",
            "status": "confirmed",
            "confirmed_at": "2026-08-14T00:00:00Z",
        },
    )
    assert status == 400
    assert not (server.registry_dir / "ocr-confirmed").exists()  # nothing written outside the workspace


def test_sync_confirmations_rejects_a_non_numeric_doc_index(server: ServerFixture) -> None:
    _seed_sync_batch(server)
    status, _ = server.post(
        "/api/sync/confirmations",
        {
            "batch_id": "adopt-0001",
            "doc_index": "one",
            "pages": ["p1.jpg"],
            "text": "x",
            "status": "confirmed",
            "confirmed_at": "2026-08-14T00:00:00Z",
        },
    )
    assert status == 400


def test_sync_confirmations_rejects_a_non_scalar_doc_index(server: ServerFixture) -> None:
    """int(doc_index) raises TypeError for non-scalars — a 400 like the
    ValueError case, never a 500."""
    _seed_sync_batch(server)
    status, _ = server.post(
        "/api/sync/confirmations",
        {
            "batch_id": "adopt-0001",
            "doc_index": ["1"],
            "pages": ["p1.jpg"],
            "text": "x",
            "status": "confirmed",
            "confirmed_at": "2026-08-14T00:00:00Z",
        },
    )
    assert status == 400


def test_serve_app_factory_builds_from_the_environment(tmp_path: Path) -> None:
    """The uvicorn factory for --reload (make serve always auto-reloads): the
    server's configuration travels via the environment the CLI set, so the
    reloader's subprocess can rebuild the app fresh on every source
    change."""
    app_data = make_app_data(tmp_path)
    (tmp_path / "archive").mkdir()

    from tools.cli import serve_app

    app = serve_app(
        _env={
            "THE_LOFT_SESSION_SECRET": "test-secret",
            "LOFT_ARCHIVE": str(tmp_path / "archive"),
            "LOFT_DATA": str(app_data),
            "LOFT_APP": str(tmp_path),
        }
    )
    assert any(getattr(route, "path", None) == "/api/health" for route in app.routes)


def test_sync_rotate_accepts_the_desired_zero(server: ServerFixture) -> None:
    """A rotate-back intent (the desired cumulative 0) must not default to
    an unintended +90 (bot review, 2026-08-16)."""
    import json as _json

    from PIL import Image

    from pipeline.detection import Detection
    from pipeline.layout import build_layout

    _seed_sync_batch(server)
    oriented = server.work_dir / "adopt-0001" / "oriented"
    oriented.mkdir(parents=True)
    Image.new("RGB", (100, 200), "white").save(oriented / "p1.jpg")
    build_layout(
        "p1.jpg",
        100,
        200,
        "Chère Maman.",
        [Detection(box=[0, 100, 50, 120], text="noise", score=0.4, words=[])],
    ).write(server.work_dir / "adopt-0001" / "ocr-guess" / "p1.layout.json")
    status, body = server.post("/api/sync/batch/adopt-0001/page/p1.jpg/rotate", {"quarters": 0})
    assert status == 200
    assert body["processing"] is False  # the desired 0 with nothing rotated is a no-op, never a +90
    layout = _json.loads((server.work_dir / "adopt-0001" / "ocr-guess" / "p1.layout.json").read_text(encoding="utf-8"))
    assert layout.get("rotation", 0) == 0  # the layout carries no rotation until a rotate applies one


def test_sync_reread_retries_a_failed_re_read_without_reorienting(tmp_path: Path) -> None:
    """PRD VR10 AC14 — a failed re-read can be retried without touching the
    orientation: the reread route clears the failed state, marks the page
    transcribing, and re-runs the reprocess over the CURRENT image. The
    reprocess is stubbed so the test never calls the reading model."""
    import json as _json

    from PIL import Image

    from pipeline.api.sync import page_job_state, set_page_job
    from pipeline.detection import Detection
    from pipeline.layout import build_layout

    fixture = ServerFixture(make_app_data(tmp_path), MemoryStore(), _reprocess=lambda b, p: None)
    _seed_sync_batch(fixture)
    oriented = fixture.work_dir / "adopt-0001" / "oriented"
    oriented.mkdir(parents=True)
    Image.new("RGB", (100, 200), "white").save(oriented / "p1.jpg")
    layout_path = fixture.work_dir / "adopt-0001" / "ocr-guess" / "p1.layout.json"
    build_layout(
        "p1.jpg",
        100,
        200,
        "Chère Maman.",
        [Detection(box=[0, 100, 50, 120], text="noise", score=0.4, words=[])],
    ).write(layout_path)
    set_page_job("adopt-0001", "p1.jpg", "failed", fixture.work_dir)
    status, body = fixture.post("/api/sync/batch/adopt-0001/page/p1.jpg/reread", {})
    assert status == 200
    assert body["processing"] is True
    # the failed state is cleared to transcribing (the re-read is in flight)
    assert page_job_state("adopt-0001", fixture.work_dir)["p1.jpg"] == "transcribing"
    # a reread never re-orients — the rotation is untouched
    layout = _json.loads(layout_path.read_text(encoding="utf-8"))
    assert layout.get("rotation", 0) == 0


_ROW_PAGE_READING: dict[str, Any] = {
    "page": "p1.jpg",
    "width": 600,
    "height": 1600,
    "rotation": 0,
    "revision": 1,
    "lines": [{"index": 0, "text": "one two", "box": [50, 400, 550, 500], "words": []}],
}
_ROW_PAGE_WORDS: dict[str, Any] = {
    "words": [
        {"x0": 60, "y0": 420, "x1": 160, "y1": 470, "line": 0, "baseline": 470, "waistline": 420},
        {"x0": 200, "y0": 420, "x1": 300, "y1": 470, "line": 0, "baseline": 470, "waistline": 420},
    ]
}


def _seed_row_page(fixture: ServerFixture, batch_id: str = "adopt-0001", status: str = "review") -> None:
    """A registered batch with one page's reading and words, ready to be
    corrected: the rows reading (dims + one line) and the words the build
    groups. The batch record is real — a correction requeues it."""
    import json as _json

    fixture.registry_dir.mkdir(parents=True, exist_ok=True)
    (fixture.registry_dir / f"{batch_id}.json").write_text(
        _json.dumps(
            {
                "batch_id": batch_id,
                "path": str(fixture.data_dir.parent / "scans" / batch_id),
                "status": status,
                "arrived_at": "2026-10-27T12:00:00+00:00",
                "pages": {"p1.jpg": "hash-1"},
                "fingerprint": ["hash-1"],
            }
        ),
        encoding="utf-8",
    )

    guess = fixture.work_dir / batch_id / "ocr-guess"
    guess.mkdir(parents=True, exist_ok=True)
    (guess / "p1.rows.json").write_text(_json.dumps(_ROW_PAGE_READING), encoding="utf-8")
    (guess / "p1.words.json").write_text(_json.dumps(_ROW_PAGE_WORDS), encoding="utf-8")


def _seed_live_row_page(fixture: ServerFixture) -> None:
    """The row page in the work tree AND the live store — B4a's flipped host."""
    from loft.live.page_row import PageState

    _seed_row_page(fixture)
    live = fixture.live
    assert live is not None
    with live.change(actor="import") as change:
        change.pages.save(
            PageState(
                page_id="adopt-0001/p1.jpg",
                image_asset_id="adopt-0001/p1.jpg",
                sha256="hash-1",
                revision=1,
                rotation=0,
                category="writing",
                status="rows_pending",
            ),
            reading={**_ROW_PAGE_READING, "words": _ROW_PAGE_WORDS["words"]},
        )


def test_a_live_row_adjustment_writes_one_change_and_the_work_files(live_server: ServerFixture) -> None:
    """B4a: the drawn line is one `Change` (the correction blob, the page's
    revision moved), and the compatibility exporter writes the two work files
    the surface and the worker read — the answer's rows are the file's."""
    import json as _json

    _seed_live_row_page(live_server)
    status, body = live_server.post(
        "/api/sync/batch/adopt-0001/page/p1.jpg/row-adjustments",
        {"lines": [[[0.05, 0.278], [0.55, 0.278]]]},
    )
    assert status == 200, body
    live = live_server.live
    assert live is not None
    page = live.pages.get("adopt-0001/p1.jpg")
    assert page is not None and page.revision == 2
    assert [event["event_type"] for event in live.events_for("adopt-0001/p1.jpg", entity_kind="page")] == [
        "created",
        "superseded",
    ]
    assert live.pages.adjustment("adopt-0001/p1.jpg") is not None
    # the reading and its rows are untouched: the correction is the drawn blob
    reading = live.pages.reading("adopt-0001/p1.jpg")
    assert reading is not None and reading.rows == 1
    guess = live_server.work_dir / "adopt-0001" / "ocr-guess"
    drawn = _json.loads((guess / "p1.row-adjustments.json").read_text())
    assert drawn["lines"] == [[[0.05, 0.278], [0.55, 0.278]]]
    assert _json.loads((guess / "p1.rows-adjusted.json").read_text())["rows"] == body["rows"]


def test_a_live_row_adjustment_on_a_page_outside_the_store_is_a_conflict(live_server: ServerFixture) -> None:
    """A batch adopted after the import has work files but no page row: the
    correction has nowhere to write, and the route says so — never a 500."""
    _seed_row_page(live_server)  # the work tree only
    status, body = live_server.post(
        "/api/sync/batch/adopt-0001/page/p1.jpg/row-adjustments",
        {"lines": [[[0.05, 0.278], [0.55, 0.278]]]},
    )
    assert status == 409, body
    assert "page" in body["error"]


def test_a_document_is_ready_for_transcription_only_after_its_row_check(server: ServerFixture) -> None:
    """The transcription stage sits after the row check: the batches answer
    says which documents may be reviewed as words, and a page still carrying
    draft rows (or never read — the strip-era pages) is before the gate."""
    import json as _json

    _seed_row_page(server)
    (server.registry_dir / "adopt-0001.json").write_text(
        _json.dumps(
            {
                "batch_id": "adopt-0001",
                "path": str(server.data_dir),
                "status": "review",
                "arrived_at": "2026-10-27T12:00:00+00:00",
                "pages": {"p1.jpg": "hash-1"},
                "fingerprint": ["hash-1"],
                "boundaries": [{"pages": ["p1.jpg"], "greeting": None, "signoff": None}],
            }
        ),
        encoding="utf-8",
    )
    guess = server.work_dir / "adopt-0001" / "ocr-guess"
    (guess / "p1.txt").write_text("one two", encoding="utf-8")
    (guess / "boundaries.json").write_text(
        _json.dumps([{"pages": ["p1.jpg"], "greeting": "", "signoff": None}]), encoding="utf-8"
    )
    status, raw = server.get("/api/sync/batches", cookie=server.cookie)
    assert status == 200
    assert _json.loads(raw.decode("utf-8"))["batches"][0]["documents_ready"] == []
    status, raw = server.get("/api/sync/batch/adopt-0001/drafts", cookie=server.cookie)
    assert _json.loads(raw.decode("utf-8"))["documents"][0]["ready"] is False

    # the reviewer's check (even with no drawn lines) is what opens the gate
    status, _ = server.post("/api/sync/batch/adopt-0001/page/p1.jpg/row-adjustments", {"lines": []})
    assert status == 200
    status, raw = server.get("/api/sync/batches", cookie=server.cookie)
    body = _json.loads(raw.decode("utf-8"))["batches"][0]
    assert body["documents_ready"] == [0] and body["documents_partial"] == []
    status, raw = server.get("/api/sync/batch/adopt-0001/drafts", cookie=server.cookie)
    doc = _json.loads(raw.decode("utf-8"))["documents"][0]
    assert doc["ready"] is True and doc["pages_ready"] == ["p1.jpg"]


def test_a_categorised_page_that_no_later_stage_has_touched_is_classified(server: ServerFixture) -> None:
    """The categorisation is the first stage: its entry is the page's status
    until orient (or the printed read) moves it on — a photo ends here."""
    import json as _json

    _seed_row_page(server)
    (server.work_dir / "adopt-0001" / "classify.json").write_text(
        _json.dumps({"p1.jpg": {"kind": "photo", "confidences": {"photo": 0.9}}}), encoding="utf-8"
    )
    (server.work_dir / "adopt-0001" / "ocr-guess" / "p1.rows.json").unlink()  # no reading: nothing later ran
    (server.work_dir / "adopt-0001" / "ocr-guess" / "p1.words.json").unlink()
    from document.stages import PageStatus
    from pipeline.api.sync import BatchReadings

    readings = BatchReadings(server.work_dir, "adopt-0001")
    assert readings.page_status("p1.jpg") is PageStatus.CLASSIFIED


def test_a_printed_page_is_ready_for_review_without_a_row_check(server: ServerFixture) -> None:
    """A printed page is read directly (no rows): its marker makes it ready, so
    the transcription review holds it without a row check ever being recorded."""
    import json as _json

    _seed_two_page_document(server)
    guess = server.work_dir / "adopt-0001" / "ocr-guess"
    (guess / "p1.printed.json").write_text(_json.dumps({"page": "p1.jpg", "chars": 12}), encoding="utf-8")
    (guess / "p2.printed.json").write_text(_json.dumps({"page": "p2.jpg", "chars": 11}), encoding="utf-8")
    (guess / "p1.txt").write_text("printed one", encoding="utf-8")
    (guess / "p2.txt").write_text("printed two", encoding="utf-8")
    status, raw = server.get("/api/sync/batches", cookie=server.cookie)
    body = _json.loads(raw.decode("utf-8"))["batches"][0]
    assert body["documents_ready"] == [0] and body["documents_partial"] == []
    status, raw = server.get("/api/sync/batch/adopt-0001/drafts", cookie=server.cookie)
    doc = _json.loads(raw.decode("utf-8"))["documents"][0]
    assert doc["pages_ready"] == ["p1.jpg", "p2.jpg"] and doc["ready"] is True


def test_a_partly_checked_document_is_reviewable_page_by_page(server: ServerFixture) -> None:
    """The transcript stage runs per page: one checked page of a two-page
    document opens that page for review, its sibling still waits on the check,
    and the batches answer names the document as partly checked (the surface
    refuses a whole-document confirmation until every page is past it)."""
    import json as _json

    _seed_two_page_document(server)
    status, raw = server.get("/api/sync/batches", cookie=server.cookie)
    body = _json.loads(raw.decode("utf-8"))["batches"][0]
    assert body["documents_ready"] == [] and body["documents_partial"] == []  # nothing checked

    # check the first page only
    status, _ = server.post("/api/sync/batch/adopt-0001/page/p1.jpg/row-adjustments", {"lines": []})
    assert status == 200
    status, raw = server.get("/api/sync/batches", cookie=server.cookie)
    body = _json.loads(raw.decode("utf-8"))["batches"][0]
    assert body["documents_partial"] == [0] and body["documents_ready"] == []
    status, raw = server.get("/api/sync/batch/adopt-0001/drafts", cookie=server.cookie)
    doc = _json.loads(raw.decode("utf-8"))["documents"][0]
    assert doc["pages_ready"] == ["p1.jpg"] and doc["ready"] is False


def _seed_two_page_document(fixture: ServerFixture, batch_id: str = "adopt-0001") -> None:
    """One document over two pages, both read (rows + words), neither checked."""
    import json as _json

    _seed_row_page(fixture, batch_id)
    guess = fixture.work_dir / batch_id / "ocr-guess"
    rows = _json.loads((guess / "p1.rows.json").read_text())
    rows["page"] = "p2.jpg"
    (guess / "p2.rows.json").write_text(_json.dumps(rows), encoding="utf-8")
    words = _json.loads((guess / "p1.words.json").read_text())
    for word in words["words"]:
        word["x0"] += 400
        word["x1"] += 400
    (guess / "p2.words.json").write_text(_json.dumps(words), encoding="utf-8")
    (guess / "p2.txt").write_text("three four", encoding="utf-8")
    (guess / "p1.txt").write_text("one two", encoding="utf-8")
    (guess / "boundaries.json").write_text(
        _json.dumps([{"pages": ["p1.jpg", "p2.jpg"], "greeting": "", "signoff": None}]), encoding="utf-8"
    )
    (fixture.registry_dir / f"{batch_id}.json").write_text(
        _json.dumps(
            {
                "batch_id": batch_id,
                "path": str(fixture.data_dir),
                "status": "review",
                "arrived_at": "2026-10-27T12:00:00+00:00",
                "pages": {"p1.jpg": "hash-1", "p2.jpg": "hash-2"},
                "fingerprint": ["hash-1", "hash-2"],
                "boundaries": [{"pages": ["p1.jpg", "p2.jpg"], "greeting": None, "signoff": None}],
            }
        ),
        encoding="utf-8",
    )


def test_sync_drafts_carries_the_rows_tints(server: ServerFixture) -> None:
    """The row screen's tints come with the drafts: the machine's rows built
    from the page's own words, as RowTint records (the colour and the
    rectangles each row is painted as). The screen draws these; it never
    re-derives a colour or a join band."""
    import json as _json

    _seed_sync_batch(server)
    guess = server.work_dir / "adopt-0001" / "ocr-guess"
    (guess / "p1.rows.json").write_text(
        _json.dumps(
            {
                "page": "p1.jpg",
                "width": 600,
                "height": 1600,
                "rotation": 0,
                "revision": 1,
                "lines": [{"index": 0, "text": "one two", "box": [50, 400, 550, 500], "words": []}],
            }
        ),
        encoding="utf-8",
    )
    (guess / "p1.words.json").write_text(
        _json.dumps(
            {
                "words": [
                    {"x0": 60, "y0": 420, "x1": 160, "y1": 470, "line": 0, "baseline": 470, "waistline": 420},
                    {"x0": 200, "y0": 420, "x1": 300, "y1": 470, "line": 0, "baseline": 470, "waistline": 420},
                ]
            }
        ),
        encoding="utf-8",
    )
    status, raw = server.get("/api/sync/batch/adopt-0001/drafts", cookie=server.cookie)
    assert status == 200
    tints = _json.loads(raw.decode("utf-8"))["documents"][0]["tints"]["p1.jpg"]
    assert len(tints) == 1, "one reading line, one tint"
    assert tints[0]["colour"][3] == 55, "the pipeline's tint alpha"
    assert tints[0]["rects"][:2] == [
        {"x0": 60.0, "y0": 420.0, "x1": 160.0, "y1": 470.0},
        {"x0": 200.0, "y0": 420.0, "x1": 300.0, "y1": 470.0},
    ]
    assert len(tints[0]["rects"]) == 3, "two word boxes and the band joining them"


def test_row_adjustments_requires_a_session(server: ServerFixture) -> None:
    status, _ = server.post("/api/sync/batch/adopt-0001/page/p1.jpg/row-adjustments", {"lines": []}, cookie="")
    assert status == 401


def test_row_adjustments_rejects_a_malformed_body(server: ServerFixture) -> None:
    """The lines are validated at the seam: a body that is not polylines of
    [x, y] pairs is a 4xx, never a 500 and never a silent empty build."""
    _seed_row_page(server)
    status, body = server.post("/api/sync/batch/adopt-0001/page/p1.jpg/row-adjustments", {"lines": [[[0.1, 0.2], "x"]]})
    assert status == 400
    assert "polyline" in body["error"]


def test_row_adjustments_builds_and_persists_the_correction(server: ServerFixture) -> None:
    """The drawn line -> the page's rows (rows.adjust over the persisted
    words), persisted as the wire contract beside the lines that made
    them; the response carries the same rows the file holds."""
    import json as _json

    _seed_row_page(server)
    # one drawn line across both words (normalised: y 0.29 of 1600 ≈ the row)
    status, body = server.post(
        "/api/sync/batch/adopt-0001/page/p1.jpg/row-adjustments",
        {"lines": [[[0.05, 0.278], [0.55, 0.278]]]},
    )
    assert status == 200
    rows = body["rows"]
    assert len(rows) == 1 and len(rows[0]["word_boxes"]) == 2  # one row, both words
    assert rows[0]["id"] == "seg-1" and rows[0]["number"] == 1
    assert rows[0]["band"] == {"x0": 60.0, "y0": 420.0, "x1": 300.0, "y1": 470.0}  # the words' exact union
    guess = server.work_dir / "adopt-0001" / "ocr-guess"
    assert _json.loads((guess / "p1.rows-adjusted.json").read_text())["rows"] == rows  # the file IS the response
    drawn = _json.loads((guess / "p1.row-adjustments.json").read_text())
    assert drawn["lines"] == [[[0.05, 0.278], [0.55, 0.278]]]
    # the answer carries the rows' tints, and a reopened page serves the
    # CORRECTION's tints (not the proposal it replaced)
    assert body["tints"][0]["colour"][3] == 55
    assert body["tints"][0]["rects"][:2] == rows[0]["word_boxes"]
    (guess / "boundaries.json").write_text(
        _json.dumps([{"pages": ["p1.jpg"], "greeting": "", "signoff": None}]), encoding="utf-8"
    )
    (guess / "p1.txt").write_text("one two", encoding="utf-8")
    status, raw = server.get("/api/sync/batch/adopt-0001/drafts", cookie=server.cookie)
    assert status == 200
    assert _json.loads(raw.decode("utf-8"))["documents"][0]["tints"]["p1.jpg"] == body["tints"]


def test_row_adjustments_names_a_drawing_that_caught_nothing(server: ServerFixture) -> None:
    """The same request validates the traces (`Rows.validate`): a stroke over
    blank paper is answered with the violation, so the surface can name it to
    the person who drew it — the correction is still kept."""
    _seed_row_page(server)
    # a stroke far below both words (y 0.7 of 1600 = 1120px)
    status, body = server.post(
        "/api/sync/batch/adopt-0001/page/p1.jpg/row-adjustments",
        {"lines": [[[0.05, 0.7], [0.55, 0.7]]]},
    )
    assert status == 200
    assert body["violations"] == ["line 1 claims no word"]
    guess = server.work_dir / "adopt-0001" / "ocr-guess"
    assert (guess / "p1.row-adjustments.json").is_file()  # the drawing is kept


def test_a_clean_correction_answers_no_violations(server: ServerFixture) -> None:
    _seed_row_page(server)
    status, body = server.post(
        "/api/sync/batch/adopt-0001/page/p1.jpg/row-adjustments",
        {"lines": [[[0.05, 0.278], [0.55, 0.278]]]},
    )
    assert status == 200
    assert body["violations"] == []


def test_a_drawn_line_puts_the_batch_back_in_the_workers_queue(server: ServerFixture) -> None:
    """The corrected rows have no text yet: the worker must re-read them into
    the reading, and the registry's status is its queue."""
    _seed_row_page(server, status="review")
    status, _ = server.post(
        "/api/sync/batch/adopt-0001/page/p1.jpg/row-adjustments",
        {"lines": [[[0.05, 0.278], [0.55, 0.278]]]},
    )
    assert status == 200
    assert load_batch("adopt-0001", server.registry_dir).status == "pending"


def test_a_check_with_no_lines_does_not_requeue(server: ServerFixture) -> None:
    """ "Rows are right" writes the check and nothing to re-read: the batch
    stays where it is."""
    _seed_row_page(server, status="review")
    status, _ = server.post("/api/sync/batch/adopt-0001/page/p1.jpg/row-adjustments", {"lines": []})
    assert status == 200
    assert load_batch("adopt-0001", server.registry_dir).status == "review"


def test_row_adjustments_refuses_a_page_without_words(server: ServerFixture) -> None:
    """A page read before the words were persisted cannot be corrected —
    the refusal names the remedy instead of building empty rows."""
    import json as _json

    guess = server.work_dir / "adopt-0001" / "ocr-guess"
    guess.mkdir(parents=True, exist_ok=True)
    (guess / "p1.rows.json").write_text(
        _json.dumps({"page": "p1.jpg", "width": 600, "height": 1600, "rotation": 0, "revision": 1, "lines": []}),
        encoding="utf-8",
    )
    status, body = server.post("/api/sync/batch/adopt-0001/page/p1.jpg/row-adjustments", {"lines": []})
    assert status == 400
    assert "re-read" in body["error"]


# -- identification (stages 7-8) -------------------------------------------


class IdentifyChat:
    """The model seam — a document's people and places, counted so a re-read
    is visible."""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, system: str, user: str, *, thinking: bool = False) -> str:  # noqa: ARG002 — the harness signature
        self.calls += 1
        return json.dumps(
            {
                "people": [{"name": "Fern", "match": "p-fern", "quote": "Dear Fern"}],
                "places": [{"name": "Mallowfield", "match": None, "quote": "we swam at Mallowfield"}],
            }
        )


def _seed_document(server: ServerFixture) -> str:
    """An agreed document naming a person and a place, and the standing
    knowledge its pass resolves against."""
    server.archive.save_identity(
        "people",
        validate_identity(
            "people",
            {"people": [{"id": "p-alex", "name": "Alex Hale"}, {"id": "p-fern", "name": "Fern"}], "relationships": []},
        ),
    )
    server.archive.save_identity("places", validate_identity("places", {"places": []}))
    server.archive.save_identity("themes", validate_identity("themes", {"themes": []}))
    item = server.archive.agree_document(
        title="A letter from Fern",
        date="1971-05-01",
        date_precision="exact",
        text="Dear Fern, we swam at Mallowfield.",
    )
    return item.id


def test_identify_reads_the_document_once_and_proposes_its_entities(server: ServerFixture) -> None:
    chat = IdentifyChat()
    server2 = ServerFixture(server.data_dir, server.store, client=chat)
    try:
        item_id = _seed_document(server2)
        status, body = server2.post(f"/api/identify/document/{item_id}", {})
        assert status == 200, body
        # the standing record is untouched (confirmed); the document's ref is
        # the proposal, and the new place is a proposed record
        assert [p["id"] for p in body["people"]] == ["p-fern"]
        assert [(p["id"], p["status"]) for p in body["places"]] == [("pl-mallowfield", "proposed")]
        assert [ref["id"] for ref in body["item"]["people"]] == ["p-fern"]
        assert [(ref["id"], ref["status"]) for ref in body["item"]["people"]] == [("p-fern", "proposed")]
        assert [(ref["id"], ref["status"]) for ref in body["item"]["places"]] == [("pl-mallowfield", "proposed")]
        assert body["pending"] == 2
        # the document is read once: a second visit answers without a model call
        status, again = server2.post(f"/api/identify/document/{item_id}", {})
        assert status == 200
        assert again["item"]["places"] == body["item"]["places"]
        assert chat.calls == 1
    finally:
        server2.close()


def test_identify_decide_lands_in_the_identity_table(server: ServerFixture) -> None:
    chat = IdentifyChat()
    server2 = ServerFixture(server.data_dir, server.store, client=chat)
    try:
        item_id = _seed_document(server2)
        _ = server2.post(f"/api/identify/document/{item_id}", {})
        status, body = server2.post(
            "/api/identify/decide",
            {"item_id": item_id, "kind": "place", "entity_id": "pl-mallowfield", "decision": "attested"},
        )
        assert status == 200, body
        assert "status" not in body["entity"]  # a confirmed record omits the status key
        assert body["message"] == "Done — Mallowfield is recorded as a fact."
        assert body["pending"] == 1  # the person still waits
        places = server2.archive.get_identity("places")
        assert places is not None
        confirmed = places.record("pl-mallowfield")
        assert confirmed is not None and confirmed.status == "confirmed"
        item = server2.archive.get_item(item_id)
        assert item is not None and item.place_refs[0].status == "confirmed"
    finally:
        server2.close()


def test_identify_decide_carries_the_familys_words_for_a_guess(server: ServerFixture) -> None:
    chat = IdentifyChat()
    server2 = ServerFixture(server.data_dir, server.store, client=chat)
    try:
        item_id = _seed_document(server2)
        _ = server2.post(f"/api/identify/document/{item_id}", {})
        basis = {"text": "we spent every summer there", "by": "Alex", "when": "2026-10-29"}
        status, body = server2.post(
            "/api/identify/decide",
            {
                "item_id": item_id,
                "kind": "place",
                "entity_id": "pl-mallowfield",
                "decision": "estimated",
                "basis": basis,
            },
        )
        assert status == 200, body
        assert body["entity"]["status"] == "estimated"
        assert body["entity"]["basis"] == basis
        item = server2.archive.get_item(item_id)
        assert item is not None and item.place_refs[0].status == "estimated"
    finally:
        server2.close()


def test_identify_never_calls_a_confirmed_person_a_guess(server: ServerFixture) -> None:
    """The mention is the document's; the person is already a fact — the
    receipt says so and the mention stays confirmed."""
    chat = IdentifyChat()
    server2 = ServerFixture(server.data_dir, server.store, client=chat)
    try:
        item_id = _seed_document(server2)
        _ = server2.post(f"/api/identify/document/{item_id}", {})
        basis = {"text": "I think so", "by": "Alex", "when": "2026-10-29"}
        status, body = server2.post(
            "/api/identify/decide",
            {"item_id": item_id, "kind": "person", "entity_id": "p-fern", "decision": "estimated", "basis": basis},
        )
        assert status == 200, body
        assert body["message"] == "Done — Fern is already recorded as a fact."
        item = server2.archive.get_item(item_id)
        assert item is not None and item.people_refs[0].status == "confirmed"
    finally:
        server2.close()


def test_identify_needs_the_ai(server: ServerFixture) -> None:
    item_id = _seed_document(server)
    status, body = server.post(f"/api/identify/document/{item_id}", {})
    assert status == 503
    assert "AI" in body["error"]


def test_identify_requires_a_session(server: ServerFixture) -> None:
    item_id = _seed_document(server)
    status, _ = server.post(f"/api/identify/document/{item_id}", {}, cookie="")
    assert status == 401


def test_identify_unknown_document_404s(server: ServerFixture) -> None:
    status, _ = server.post("/api/identify/document/doc-1970-01-01", {})
    assert status == 404


def test_identify_decide_rejects_a_bad_decision(server: ServerFixture) -> None:
    item_id = _seed_document(server)
    status, _ = server.post(
        "/api/identify/decide",
        {"item_id": item_id, "kind": "place", "entity_id": "pl-x", "decision": "maybe"},
    )
    assert status == 400


def _item_text(archive: Archive, item_id: str) -> str:
    item = archive.get_item(item_id)
    assert item is not None
    asset = next(a for a in item.assets if a.kind == "transcription")
    return archive.read_content(item.id, asset.file) or ""


def _seed_approval_batch(fixture: ServerFixture) -> None:
    """A two-page document read and grouped, waiting for the review."""
    import json as _json

    batch = fixture.work_dir / "adopt-0001"
    guess = batch / "ocr-guess"
    guess.mkdir(parents=True)
    classify = {
        "p1.jpg": {"kind": "printed", "confidences": {"printed": 0.9}},
        "p2.jpg": {"kind": "printed", "confidences": {"printed": 0.9}},
    }
    (batch / "classify.json").write_text(_json.dumps(classify), encoding="utf-8")
    for page, text in (("p1", "PAGE ONE"), ("p2", "PAGE TWO")):
        (guess / f"{page}.txt").write_text(text, encoding="utf-8")
        (guess / f"{page}.printed.json").write_text("{}", encoding="utf-8")
    (guess / "boundaries.json").write_text(_json.dumps([{"pages": ["p1.jpg", "p2.jpg"]}]), encoding="utf-8")
    fixture.registry_dir.mkdir(parents=True)
    (fixture.registry_dir / "adopt-0001.json").write_text(
        _json.dumps(
            {
                "batch_id": "adopt-0001",
                "path": str(fixture.data_dir),
                "status": "review",
                "arrived_at": "2026-01-01T00:00:00+00:00",
                "pages": {"p1.jpg": "hash-1", "p2.jpg": "hash-2"},
                "boundaries": [{"pages": ["p1.jpg", "p2.jpg"]}],
            }
        ),
        encoding="utf-8",
    )


def test_sync_approvals_require_a_session(server: ServerFixture) -> None:
    status, _ = server.post("/api/sync/approvals", {"batch_id": "adopt-0001"}, cookie="")
    assert status == 401


def test_sync_approvals_take_one_page_then_catalogue_the_document(server: ServerFixture) -> None:
    """The reviewer approves page 1 while page 2 waits: the item exists as a
    draft holding page 1; page 2's approval completes it, catalogued, as the
    same item."""

    _seed_approval_batch(server)
    facts = {"batch_id": "adopt-0001", "title": "A letter", "date": "1915-05-02", "date_precision": "exact"}
    status, first = server.post("/api/sync/approvals", {**facts, "page": "p1.jpg", "text": "PAGE ONE"})
    assert status == 200 and first["document_complete"] is False
    item_id = first["item_id"]
    archive = Archive(server.store)
    item = archive.get_item(item_id)
    assert item is not None and item.status == "draft"
    assert _item_text(archive, item_id) == "PAGE ONE"

    status, second = server.post("/api/sync/approvals", {**facts, "page": "p2.jpg", "text": "PAGE TWO"})
    assert status == 200 and second["document_complete"] is True and second["item_id"] == item_id
    item = archive.get_item(item_id)
    assert item is not None and item.status == "catalogued"
    assert _item_text(archive, item_id) == "PAGE ONE\n\nPAGE TWO"
