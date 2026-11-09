"""Local IO fixtures; production assembly tests must never start Docker."""

import asyncio
import socket
import subprocess

import pytest


@pytest.fixture(autouse=True)
def no_network_connections(monkeypatch):
    """All tests are offline, including DNS and loopback; replace raw HTTP ports."""
    def forbidden(*args, **kwargs):
        raise AssertionError("Tests must not connect to servers or resolve network hosts.")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


@pytest.fixture
def pending_vllm_http_factory():
    """Preserve first-frame tests before any vLLM sample without network IO."""
    class PendingHttp:
        async def get(self, url, *, timeout, max_bytes):
            await asyncio.Future()

        async def close(self):
            pass

    return PendingHttp


@pytest.fixture
def no_live_docker_io(monkeypatch):
    """Fail closed in Docker tests; adapter tests replace only the async OS port."""

    def forbidden(*args, **kwargs):
        raise AssertionError("Docker tests must use offline process/command ports.")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.fixture
def pending_docker_command_factory():
    """Keep first-frame tests before any sample, including after REQ-003 wiring.

    Only the command IO is replaced. The real runtime, collector, Monitor and
    state still run; cancellation releases the pending IO without a result.
    """

    class PendingCommand:
        async def run(self, argv, *, timeout):
            await asyncio.Future()

        async def close(self):
            pass

    return PendingCommand
