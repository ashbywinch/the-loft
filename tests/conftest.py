"""Tests never hit the network (docs/testing-standards.md): any socket
connect to a non-loopback address fails loudly instead of hanging or
phoning out. The capture-server tests bind and call 127.0.0.1 — loopback
stays open; everything else is blocked at the socket seam, so urllib,
requests and the AI client all fail the same way. The ONE deliberate
exemption (2026-08-10): the ``eval``-marked tests — the real-model evals
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
