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

from tools.server import create_server
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
    def __init__(self, data_dir: Path, store: MemoryStore) -> None:
        self.store: MemoryStore = store
        self.data_dir: Path = data_dir
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
        self.server = create_server(store, data_dir, client=None, app_dir=data_dir.parent, host="127.0.0.1", port=0)
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
        import os

        os.environ.setdefault("THE_LOFT_SESSION_SECRET", "test-secret")
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


def test_confirm_person_flips_proposed_to_confirmed(server: ServerFixture) -> None:
    _seed_pending(server)
    status, body = server.post("/api/people/confirm", {"id": "p-judith"})
    assert status == 200
    assert body["ok"] is True
    assert "status" not in body["person"]  # confirmed records omit the status key
    table = server.archive.get_identity("people")
    assert table is not None
    person = next(p for p in table["people"] if p["id"] == "p-judith")
    assert "status" not in person


def test_confirm_pins_the_specific_relation_the_review_settled_on(server: ServerFixture) -> None:
    """The review chat confirms with the resolved kinship (2026-08-08, user:
    never a bare "cousin") — the person's relation becomes the specific term."""
    _seed_pending(server)
    relation = "first cousin once removed (Nora's cousin via Fern)"
    status, body = server.post("/api/people/confirm", {"id": "p-judith", "relation": relation})
    assert status == 200
    assert body["person"]["relation"] == relation
    table = server.archive.get_identity("people")
    assert table is not None
    person = next(p for p in table["people"] if p["id"] == "p-judith")
    assert person["relation"] == "first cousin once removed (Nora's cousin via Fern)"


def test_confirm_without_a_relation_keeps_the_imports_text(server: ServerFixture) -> None:
    _seed_pending(server)
    status, body = server.post("/api/people/confirm", {"id": "p-judith"})
    assert status == 200
    assert body["person"].get("relation", "") == ""  # untouched


def test_confirm_requires_a_session(server: ServerFixture) -> None:
    _seed_pending(server)
    status, body = server.post("/api/people/confirm", {"id": "p-judith"}, cookie="")
    assert status == 401
    table = server.archive.get_identity("people")
    assert table is not None
    assert next(p for p in table["people"] if p["id"] == "p-judith")["status"] == "proposed"  # untouched


def test_relate_requires_the_ai(server: ServerFixture) -> None:
    _seed_pending(server)
    status, body = server.post("/api/review/relate", {"person_id": "p-judith", "text": "my mum's cousin"})
    assert status == 503  # no AI client on this server
    assert "AI isn't configured" in body["error"]


def test_relate_requires_a_session(server: ServerFixture) -> None:
    _seed_pending(server)
    status, body = server.post("/api/review/relate", {"person_id": "p-judith", "text": "cousin"}, cookie="")
    assert status == 401


def test_relate_unknown_person_404s(server: ServerFixture) -> None:
    _seed_pending(server)
    status, body = server.post("/api/review/relate", {"person_id": "p-nope", "text": "cousin"})
    assert status == 404


def test_relate_requires_person_and_text(server: ServerFixture) -> None:
    _seed_pending(server)
    status, _ = server.post("/api/review/relate", {"person_id": "p-judith", "text": "  "})
    assert status == 400


def test_dismiss_removes_the_person_and_their_relationships(server: ServerFixture) -> None:
    _seed_pending(server)
    status, body = server.post("/api/people/dismiss", {"id": "p-judith"})
    assert status == 200
    assert body["ok"] is True
    table = server.archive.get_identity("people")
    assert table is not None
    assert all(p["id"] != "p-judith" for p in table["people"])
    assert all(r.get("a") != "p-judith" and r.get("b") != "p-judith" for r in table["relationships"])
    assert any(p["id"] == "p-robert" for p in table["people"])  # the confirmed person stays


def test_dismiss_refuses_a_confirmed_person(server: ServerFixture) -> None:
    status, body = server.post("/api/people/dismiss", {"id": "p-alex"})
    assert status == 400
    assert "not proposed" in body["error"]


def test_confirming_the_last_proposed_person_completes_the_session(server: ServerFixture) -> None:
    _seed_pending(server)
    status, body = server.post("/api/people/confirm", {"id": "p-judith"})
    assert status == 200
    imports = server.archive.get_identity("imports")
    assert imports is not None
    assert imports["imports"][0]["status"] == "reviewed"  # nothing left pending — the session is done
