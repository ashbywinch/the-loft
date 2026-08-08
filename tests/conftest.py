"""Tests never hit the network (docs/testing-standards.md): any socket
connect to a non-loopback address fails loudly instead of hanging or
phoning out. The capture-server tests bind and call 127.0.0.1 — loopback
stays open; everything else is blocked at the socket seam, so urllib,
requests and the AI client all fail the same way."""

from __future__ import annotations

import socket
from typing import Any

import pytest

_LOOPBACK = ("127.0.0.1", "::1")


@pytest.fixture(autouse=True)
def _no_outbound_network(monkeypatch: pytest.MonkeyPatch) -> None:
    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: Any) -> None:
        host = address[0] if isinstance(address, tuple) else address
        if host not in _LOOPBACK:
            raise OSError(f"network access blocked in tests (host={host!r})")
        real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
