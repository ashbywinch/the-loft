"""Tests never hit the network (docs/testing-standards.md): any socket
connect to a non-loopback address fails loudly instead of hanging or
phoning out. The capture-server tests bind and call 127.0.0.1 — loopback
stays open; everything else is blocked at the socket seam, so urllib,
requests and the AI client all fail the same way. The ONE deliberate
exemption: the ``eval``-marked tests — the real-model evals
run with ``pytest -m eval``, and they exist to phone the model API."""

from __future__ import annotations

import socket
from typing import Any

import pytest

_LOOPBACK = ("127.0.0.1", "::1")


@pytest.fixture(autouse=True)
def _no_outbound_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if "eval" in request.keywords:
        return  # the eval-marked tests are the deliberate network users
    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: Any) -> None:
        host = address[0] if isinstance(address, tuple) else address
        if host not in _LOOPBACK:
            raise OSError(f"network access blocked in tests (host={host!r})")
        real_connect(self, address)

    # The network guard is test infrastructure, not a dependency fake —
    # lucidlint: ignore monkeypatch DI cannot block sockets
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


@pytest.fixture(autouse=True)
def _the_real_workspace_is_untouched(request: pytest.FixtureRequest) -> Any:
    """No test writes into the family's archive, registry or work tree: a
    default path that leaks (a seam's default, a helper built without its
    dirs) fails the test that used it, naming the folder it created.

    The archive-marked checks (`make verify`) read the real archive by
    design, so they are exempt. Two levels are enough: a stray write always
    adds an item folder or a file inside one."""
    if "archive" in request.keywords:
        yield
        return
    from tools.loft_paths import ARCHIVE_DIR, REGISTRY_DIR, WORK_DIR

    def snapshot() -> dict[str, set[str]]:
        roots = {"archive": ARCHIVE_DIR, "registry": REGISTRY_DIR, "work": WORK_DIR}
        state: dict[str, set[str]] = {}
        for name, root in roots.items():
            if not root.is_dir():
                state[name] = set()
                continue
            entries: set[str] = {child.name for child in root.iterdir()}
            assets = root / "assets"
            if assets.is_dir():
                for item in assets.iterdir():
                    entries |= {f"assets/{item.name}/{child.name}" for child in item.iterdir()}
            state[name] = entries
        return state

    before = snapshot()
    yield
    after = snapshot()
    grown = {name: sorted(after[name] - before[name]) for name in after if after[name] - before[name]}
    assert not grown, f"a test wrote to the real workspace: {grown}"
