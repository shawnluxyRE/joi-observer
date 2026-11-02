"""Local IO fixtures; production assembly tests must never start Docker."""

import asyncio
import socket
import subprocess

import pytest


@pytest.fixture
def no_live_docker_io(monkeypatch):
    """Fail closed in Docker tests; adapter tests replace only the async OS port."""

    def forbidden(*args, **kwargs):
        raise AssertionError("Docker tests must use offline process/command ports.")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    original_run = asyncio.run

    def guarded_run(main, **kwargs):
        # Let Windows initialize the event loop's private wakeup socket first.
        # The guard then covers the business coroutine and all runner cleanup.
        with monkeypatch.context() as connections:
            async def guarded():
                connections.setattr(socket.socket, "connect", forbidden)
                return await main

            return original_run(guarded(), **kwargs)

    monkeypatch.setattr(asyncio, "run", guarded_run)


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
