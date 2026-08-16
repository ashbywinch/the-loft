"""Tests for the capture server: the API contract, append-only writes through
the store, and the projection refresh. The handler is exercised through the
real HTTP stack on an ephemeral port — no network, no AI."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tools.memory import ElicitationError
from tools.server import create_server
from tools.store import ImmutableStoreError, MemoryStore
from tools.sync import Outbox


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
    def __init__(self, data_dir: Path, store: MemoryStore, client: Any | None = None) -> None:
        self.store: MemoryStore = store
        self.data_dir: Path = data_dir
        # the session secret before any app build — the server refuses to
        # start without it (2026-08-14 review: forgeable sessions otherwise)
        import os

        os.environ.setdefault("THE_LOFT_SESSION_SECRET", "test-secret")
        # the sync surfaces are bound to tmp dirs, never the real workspace
        # (2026-08-14 review: the endpoints must not touch the home disk in tests)
        self.work_dir: Path = data_dir.parent / "work"
        self.outbox: Outbox = Outbox(data_dir.parent / "outbox")
        self.registry_dir: Path = data_dir.parent / "registry"
        # the identity seam (2026-08-06): the archive's people carry the
        # verified Google accounts; the capture API resolves the narrator
        # from the session, never from the client
        from tools.archive import Archive

        self.archive = Archive(store)
        self.archive.save_identity(
            "people",
            {
                "people": [
                    {"id": "p-alex", "name": "Alex Hale", "email": "alex@example.com"},
                    {"id": "p-other", "name": "Other", "email": "other@example.com"},
                ],
                "relationships": [],
            },
        )
        # the sync confirmation receiver re-publishes — the store must be
        # publishable (places/themes present), not just people
        self.archive.save_identity("places", {"places": [{"id": "pl-marlock", "name": "Marlock"}]})
        self.archive.save_identity("themes", {"themes": []})
        # the server refuses to start without a session secret (forgeable
        # sessions, 2026-08-14 review) — the test secret must be set BEFORE
        # create_server, not after (the old order worked locally only because
        # the dev shell exports the secret; CI has none, 2026-08-15)
        import os

        os.environ.setdefault("THE_LOFT_SESSION_SECRET", "test-secret")
        self.server = create_server(
            store,
            data_dir,
            client=client,
            app_dir=data_dir.parent,
            host="127.0.0.1",
            port=0,
            work_dir=self.work_dir,
            outbox=self.outbox,
            registry_dir=self.registry_dir,
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
        from tools import auth

        self.cookie = f"{auth.COOKIE_NAME}={auth._make_session_cookie('alex@example.com', 'Alex Hale', '')}"

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
    projection is refreshed (drafts are committed during dev, 2026-08-03)."""
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
    is ignored (2026-08-06, user: google auth, no name claims)."""
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
    wins) and the projection holds a single entry (user, 2026-08-03: a
    reboot mid-chat loses at most the last few words)."""
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
    projection (user, 2026-08-03)."""
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
    the household capture server (reviewer, 2026-08-03)."""
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
    """The archive's data is the private layer (2026-08-06, user: content
    gated behind sign-in) — a session is required to read people.json, and
    the app shell stays public so the gate can load."""
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
    'Malformed auth code' (2026-08-06, the invalid_grant)."""

    # an unregistered state fails cleanly BEFORE the exchange — this pins
    # the decode path by driving the callback with a real encoded shape
    class NoRedirect(urllib.request.HTTPRedirectHandler):
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
        {
            "people": [
                {"id": "p-alex", "name": "Alex Hale"},
                {"id": "p-robert", "name": "Quentin Whitlock"},
                {"id": "p-judith", "name": "Pearl Whitlock", "status": "proposed"},
            ],
            "relationships": [{"a": "p-robert", "b": "p-judith", "kind": "spouse"}],
        },
    )
    # the confirm/dismiss endpoints republish the projection, which needs the
    # whole identity set — a realistic archive
    server.archive.save_identity("places", {"places": []})
    server.archive.save_identity("themes", {"themes": []})
    server.archive.save_identity("orgs", {"orgs": []})
    server.archive.save_identity(
        "imports", {"imports": [{"id": "import-documents", "title": "The document import", "status": "pending"}]}
    )


def test_decide_attested_flips_proposed_to_confirmed(server: ServerFixture) -> None:
    """Attested = the reviewer's own verified word — the status drops, the
    import's relation text stays untouched (2026-08-09)."""
    _seed_pending(server)
    status, body = server.post(
        "/api/review/decide", {"session_id": "import-documents", "person_id": "p-judith", "decision": "attested"}
    )
    assert status == 200
    assert body["ok"] is True
    assert "status" not in body["person"]  # confirmed records omit the status key
    # the response carries the server's accurate remaining count — the
    # client's projection is stale until reload, so the count comes from
    # here (user 2026-08-16: the count must always be accurate)
    assert body["pending"] == 0  # the seed's only proposed person is now decided
    table = server.archive.get_identity("people")
    assert table is not None
    person = next(p for p in table["people"] if p["id"] == "p-judith")
    assert "status" not in person
    assert person.get("relation", "") == ""  # the attested path never rewrites the relation


def test_decide_estimated_records_the_basis_verbatim(server: ServerFixture) -> None:
    """Estimated = the reviewer's own words, named + dated (2026-08-09)."""
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
    assert next(p for p in table["people"] if p["id"] == "p-judith")["basis"] == basis


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
    assert next(p for p in table["people"] if p["id"] == "p-judith")["status"] == "proposed"


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
    assert next(p for p in table["people"] if p["id"] == "p-judith")["status"] == "proposed"  # untouched


def test_decide_rejects_an_unknown_decision(server: ServerFixture) -> None:
    _seed_pending(server)
    status, _ = server.post(
        "/api/review/decide", {"session_id": "import-documents", "person_id": "p-judith", "decision": "maybe"}
    )
    assert status == 400


def test_text_requires_the_ai(server: ServerFixture) -> None:
    """The free-text relevance check needs the model (2026-08-09)."""
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
    assert all(p["id"] != "p-judith" for p in table["people"])
    assert all(r.get("a") != "p-judith" and r.get("b") != "p-judith" for r in table["relationships"])
    assert any(p["id"] == "p-robert" for p in table["people"])  # the confirmed person stays


def test_decide_delete_of_an_already_resolved_person_is_a_state_not_an_error(server: ServerFixture) -> None:
    """The queue never holds resolved people — a stale delete is a state,
    not the old "not proposed" 400 (2026-08-09); and it must not record a
    false confirmation ("removed" when nothing was removed, 2026-08-11
    review)."""
    _seed_pending(server)
    status, body = server.post(
        "/api/review/decide", {"session_id": "import-documents", "person_id": "p-robert", "decision": "delete"}
    )
    assert status == 200
    assert body["ok"] is True
    assert body["person"]["id"] == "p-robert"  # unchanged — the confirmed person stays
    assert body["message"] == "Quentin Whitlock was already resolved — nothing changed."
    # nothing recorded — the stale delete must not persist a false decision
    # (the seed's session has no attempts, which is itself the proof)
    session = server.archive.get_review_session("import-documents")
    assert session is not None
    attempt = session.current_attempt()
    assert attempt is None or not attempt.decisions


def test_decide_pending_on_an_already_resolved_person_is_stale_too(server: ServerFixture) -> None:
    """2026-08-11 review: a "leave for later" on a confirmed person used to
    fall through the stale guard and record a false kept-decision —
    moving the session's resume point to a resolved person and even
    marking the walk finished. The queue never holds resolved people, so
    a keep on a never-proposed person is stale like any other decision."""
    _seed_pending(server)
    status, body = server.post(
        "/api/review/decide", {"session_id": "import-documents", "person_id": "p-robert", "decision": "pending"}
    )
    assert status == 200
    assert body["ok"] is True
    assert body["message"] == "Quentin Whitlock was already resolved — nothing changed."
    assert body["person"]["id"] == "p-robert"  # the confirmed person stays
    # nothing recorded — the stale keep must not advance the session
    session = server.archive.get_review_session("import-documents")
    assert session is not None
    attempt = session.current_attempt()
    assert attempt is None or not attempt.decisions


def test_decide_duplicate_delete_on_a_removed_person_is_a_state(server: ServerFixture) -> None:
    """2026-08-11 review: a second delete (double-tap, two devices) for a
    person already REMOVED from the table used to 400 ("no person") and
    the UI showed "That didn't save" for a deletion that had already
    succeeded. The missing-person case is the already-resolved state —
    nothing recorded, honest message, nothing written."""
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
    assert body2["message"] == "p-judith was already resolved — nothing changed."
    assert body2["person"] is None  # the person is gone — no record returned
    session = server.archive.get_review_session("import-documents")
    assert session is not None
    attempt = session.current_attempt()
    assert attempt is not None
    # exactly the ONE legitimate delete is recorded — the duplicate added nothing
    assert [d.decision for d in attempt.decisions] == ["delete"]


def test_deciding_the_last_proposed_person_completes_the_session(server: ServerFixture) -> None:
    _seed_pending(server)
    status, _ = server.post(
        "/api/review/decide", {"session_id": "import-documents", "person_id": "p-judith", "decision": "attested"}
    )
    assert status == 200
    imports = server.archive.get_identity("imports")
    assert imports is not None
    assert imports["imports"][0]["status"] == "reviewed"  # nothing left pending — the session is done


def test_review_reads_the_transcription_not_the_summary(server: ServerFixture) -> None:
    """2026-08-09 (user: "extremely bad at identifying the relevant part of
    the document to quote when explaining the attestation"): the review's
    facts must carry the VERBATIM transcription — the text the family sees
    in the claim and the item page — never the sidecar's archival summary.
    The projection used to read only the sidecar's story field, so the
    model could not see the document's own words at all."""
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
    # (DI, 2026-08-09) — the fixture's server deliberately runs clientless
    server2 = ServerFixture(server.data_dir, server.store, client=FakeChat())
    try:
        _seed_pending(server2)  # the second init re-seeded the people table
        server2.archive.save_item(
            {
                "id": "doc-2001-email",
                "title": "The 2001 email",
                "date": "2001-02-07",
                "date_precision": "exact",
                "type": "letter",
                "status": "catalogued",
                "people": [{"id": "p-judith", "status": "confirmed"}],
            },
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
        # (R7; 2026-08-11 review)
        assert set(body) == {"ok", "message", "relevant", "contradiction", "confidence", "note", "findings", "question"}
        # the model's prompt carries the transcription's own words — never
        # the summary, and never a bare "no documents" note
        assert "Pearl Whitlock was the one who kept the photographs" in seen["user"]
        # AND the reviewer's own words — the loop must never overwrite the
        # request's text with an item's content (2026-08-10 review, high:
        # the verdict was computed against the last item's transcription and
        # that content was persisted as the user's line)
        assert "Grandma used to say so." in seen["user"]
        imports = server2.archive.get_identity("imports")
        assert imports is not None
        session = next(s for s in imports["imports"] if s.get("id") == "import-documents")
        messages = session["attempts"][-1]["messages"]
        user_lines = [m["text"] for m in messages if m["role"] == "user"]
        # the transcript holds the user's words verbatim, EXACTLY ONCE —
        # the record-before-the-call fix must not double them on the
        # success path (2026-08-11 review: the line recorded twice)
        assert user_lines == ["Grandma used to say so."]
    finally:
        server2.close()


def test_review_reads_transcription_only_mentions(server: ServerFixture) -> None:
    """2026-08-11 review: the metadata pre-filter must NOT drop an item
    whose only mention of the person lives in the verbatim transcription
    (a draft with no people refs and no story yet) — the bounded
    first-chunk read settles the shortlist, so the model can still attest
    from the document's own words. The sidecar story alone must never be
    the item's only window."""
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
            },
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
    """2026-08-11 review: the shortlist filter matched the person's name
    case-sensitively against story/transcription — an item whose only
    mention is lowercased (OCR text, an uppercase heading) was silently
    dropped, and the document became invisible to the investigation. The
    needles and the compared text are now lowered."""
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
            },
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
    """2026-08-10 review: /api/review/decide resolved and saved the person
    BEFORE checking the session existed — a stale session_id changed the
    archive and then returned 500. The session is now validated first:
    a stale id gets a 404 and the person is untouched."""
    _seed_pending(server)
    status, body = server.post(
        "/api/review/decide",
        {"session_id": "import-nope", "person_id": "p-judith", "decision": "attested"},
    )
    assert status == 404
    assert "no import session" in body["error"]
    table = server.archive.get_identity("people")
    assert table is not None
    assert next(p for p in table["people"] if p["id"] == "p-judith")["status"] == "proposed"  # untouched


def test_review_text_keeps_the_words_when_the_model_call_fails(server: ServerFixture) -> None:
    """2026-08-11 review: the family's line was recorded only AFTER the
    model call, so an AI outage (ElicitationError) lost their words from
    the transcript — the transcript no longer equalled what the family saw
    (R7/R8). The line now joins the transcript the moment it arrives; the
    failure returns 422 but the record stands."""
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
        session = next(s for s in imports["imports"] if s.get("id") == "import-documents")
        messages = session["attempts"][-1]["messages"]
        user_line = next(m["text"] for m in messages if m["role"] == "user")
        assert user_line == "Grandma used to say so."  # never lost to the outage
    finally:
        server2.close()


def test_start_returns_the_lines_already_recorded_in_the_attempt(server: ServerFixture) -> None:
    """2026-08-10 review (duplicate transcript on re-render): the start
    response carries the current attempt's recorded lines, so the app
    records only what's new — the transcript never duplicates the opening
    or a claim."""
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
        _json.dumps({"batch_id": batch_id, "path": str(fixture.data_dir), "status": "review", "boundaries": None}),
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


def test_sync_confirmations_records_and_reports(server: ServerFixture) -> None:
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
        },
    )
    assert status == 200
    assert body["ok"] is True
    import json as _json

    record = _json.loads((server.registry_dir / "adopt-0001.json").read_text(encoding="utf-8"))
    assert record["boundaries"][0]["status"] == "confirmed"
    confirmed = server.work_dir / "adopt-0001" / "ocr-confirmed" / "doc-01.txt"
    assert confirmed.read_text(encoding="utf-8") == "Chère Maman."


def test_sync_confirmations_rejects_a_bad_shape(server: ServerFixture) -> None:
    status, body = server.post(
        "/api/sync/confirmations",
        {"batch_id": "adopt-0001", "doc_index": 1, "pages": [], "text": "x"},
    )
    assert status == 400


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


def test_sync_page_requires_a_session(server: ServerFixture) -> None:
    status, _ = server.get("/api/sync/batch/adopt-0001/page/p1.jpg")
    assert status == 401


def test_sync_page_serves_the_oriented_image(server: ServerFixture) -> None:
    _seed_sync_batch(server)
    oriented = server.work_dir / "adopt-0001" / "oriented"
    oriented.mkdir(parents=True)
    (oriented / "p1.jpg").write_bytes(b"\xff\xd8fake-jpeg-bytes")
    status, raw = server.get("/api/sync/batch/adopt-0001/page/p1.jpg", cookie=server.cookie)
    assert status == 200
    assert raw == b"\xff\xd8fake-jpeg-bytes"


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
    """2026-08-14 review: int(doc_index) raises TypeError for non-scalars —
    a 400 like the ValueError case, never a 500."""
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


def test_serve_app_factory_builds_from_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The uvicorn factory for --reload (2026-08-16: make serve always
    auto-reloads): the server's configuration travels via the environment
    the CLI set, so the reloader's subprocess can rebuild the app fresh on
    every source change."""
    app_data = make_app_data(tmp_path)
    (tmp_path / "archive").mkdir()
    monkeypatch.setenv("THE_LOFT_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("LOFT_ARCHIVE", str(tmp_path / "archive"))
    monkeypatch.setenv("LOFT_DATA", str(app_data))
    monkeypatch.setenv("LOFT_APP", str(tmp_path))

    from tools.cli import serve_app

    app = serve_app()
    assert any(getattr(route, "path", None) == "/api/health" for route in app.routes)


def test_sync_rotate_accepts_the_desired_zero(server: ServerFixture) -> None:
    """A rotate-back intent (the desired cumulative 0) must not default to
    an unintended +90 (bot review, 2026-08-16)."""
    import json as _json

    from PIL import Image

    from tools.layout import Detection, build_layout, write_layout

    _seed_sync_batch(server)
    oriented = server.work_dir / "adopt-0001" / "oriented"
    oriented.mkdir(parents=True)
    Image.new("RGB", (100, 200), "white").save(oriented / "p1.jpg")
    write_layout(
        build_layout(
            "p1.jpg",
            100,
            200,
            "Chère Maman.",
            [Detection(box=[0, 100, 50, 120], text="noise", score=0.4, words=[])],
        ),
        server.work_dir / "adopt-0001" / "ocr-guess" / "p1.layout.json",
    )
    status, body = server.post("/api/sync/batch/adopt-0001/page/p1.jpg/rotate", {"quarters": 0})
    assert status == 200
    assert body["processing"] is False  # the desired 0 with nothing rotated is a no-op, never a +90
    layout = _json.loads((server.work_dir / "adopt-0001" / "ocr-guess" / "p1.layout.json").read_text(encoding="utf-8"))
    assert layout.get("rotation", 0) == 0  # the layout carries no rotation until a rotate applies one
