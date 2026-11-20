"""Allocation faults never detach an already owned IPC resource."""

import asyncio

import pytest
from types import SimpleNamespace

from joi_observer.ipc.client import ConnectionFailure, ConnectionState, SnapshotClient
from joi_observer.ipc.server import SnapshotPublisher
from test_ipc_client import MemoryConnector, MemoryStream, frame
from test_service_contract import MemoryListener, MemoryPeer, envelope_source, no_updates, until
from test_publisher_os_edges import FakeSocket, fake_unix_boundary


def test_receiver_allocation_failure_closes_the_first_frame_connection(monkeypatch):
    async def scenario():
        stream = MemoryStream(frame())
        client = SnapshotClient(connector=MemoryConnector(stream))
        original = asyncio.create_task

        def allocate(coro, **kwargs):
            if coro.cr_code is SnapshotClient._receive.__code__:
                coro.close()
                raise MemoryError("receiver unavailable")
            return original(coro, **kwargs)

        monkeypatch.setattr(asyncio, "create_task", allocate)
        with pytest.raises(ConnectionFailure):
            await client.connect()
        assert client.state is ConnectionState.FAILED and stream.closed
        await client.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("resource", ["listener", "peer"])
def test_publisher_close_resource_task_failure_uses_inline_cleanup(monkeypatch, resource):
    async def scenario():
        source, _ = envelope_source()
        listener, peer = MemoryListener(), MemoryPeer()
        listener.peers.put_nowait(peer)
        publisher = SnapshotPublisher(source, listener, wait_updated=no_updates)
        stop = asyncio.Event()
        running = asyncio.create_task(publisher.run(stop))
        original = asyncio.create_task
        refused = []

        def allocate(coro, **kwargs):
            selected = (resource == "listener" and coro.cr_code is MemoryListener.close.__code__
                        or resource == "peer" and coro.cr_code is SnapshotPublisher._close_peer.__code__)
            if selected and not refused:
                refused.append(True)
                coro.close()
                raise MemoryError("resource close task unavailable")
            return original(coro, **kwargs)

        try:
            await until(lambda: bool(peer.frames), running)
            monkeypatch.setattr(asyncio, "create_task", allocate)
            with pytest.raises(MemoryError):
                await publisher.close()
            assert refused and listener.closed and peer.closed
            await asyncio.gather(running, return_exceptions=True)
            # A successfully created owner retains its original cleanup
            # outcome; joining it again must not repeat the resource work.
            with pytest.raises(MemoryError):
                await publisher.close()
            assert len(refused) == 1 and listener.closed and peer.closed
        finally:
            stop.set()
            await asyncio.gather(running, return_exceptions=True)
            await asyncio.gather(publisher.close(), return_exceptions=True)
    asyncio.run(scenario())


def test_accepted_socket_adapter_allocation_failure_closes_the_os_port(monkeypatch, tmp_path):
    from joi_observer.ipc import server

    async def scenario():
        endpoint, _, _, _ = fake_unix_boundary(monkeypatch, tmp_path)
        listener = server.UnixListener(endpoint)
        await listener.start()
        accepted = FakeSocket({}, endpoint, [])

        async def accept(connection):
            return accepted, ""

        def refuse(connection):
            raise MemoryError("peer adapter unavailable")

        monkeypatch.setattr(asyncio.get_running_loop(), "sock_accept", accept)
        monkeypatch.setattr(server, "_UnixPeer", refuse)
        try:
            with pytest.raises(MemoryError):
                await listener.accept()
            assert accepted.closed
        finally:
            await listener.close()
    asyncio.run(scenario())


def test_connected_stream_adapter_allocation_failure_closes_the_os_port(monkeypatch):
    from joi_observer.ipc import client as module

    async def scenario():
        closed = []
        writer = SimpleNamespace(close=lambda: closed.append(True))

        async def wait_closed():
            assert closed

        writer.wait_closed = wait_closed

        async def connect(*args, **kwargs):
            return object(), writer

        def refuse(*args):
            raise MemoryError("stream adapter unavailable")

        monkeypatch.setattr(asyncio, "open_unix_connection", connect)
        monkeypatch.setattr(module, "_UnixStream", refuse)
        with pytest.raises(MemoryError):
            await module.UnixConnector().connect(__import__('pathlib').Path('/unused.sock'))
        assert closed == [True]
    asyncio.run(scenario())


def test_listener_start_error_survives_cleanup_owner_allocation_failure(monkeypatch):
    async def scenario():
        primary = OSError("original bind failure")

        class Listener(MemoryListener):
            async def start(self):
                raise primary

        original = asyncio.create_task

        def allocate(coro, **kwargs):
            if kwargs.get("name") == "snapshot-publisher-close":
                coro.close()
                raise MemoryError("secondary cleanup allocation failure")
            return original(coro, **kwargs)

        monkeypatch.setattr(asyncio, "create_task", allocate)
        source, _ = envelope_source()
        listener = Listener()
        publisher = SnapshotPublisher(source, listener, wait_updated=no_updates)
        with pytest.raises(OSError) as caught:
            await publisher.start()
        assert caught.value is primary and listener.closed
        await publisher.close()
    asyncio.run(scenario())


def test_accepted_adapter_error_survives_secondary_os_close_failure(monkeypatch, tmp_path):
    from joi_observer.ipc import server

    async def scenario():
        endpoint, _, _, _ = fake_unix_boundary(monkeypatch, tmp_path)
        listener = server.UnixListener(endpoint)
        await listener.start()
        primary = MemoryError("original adapter allocation failure")
        closed = []

        def close():
            closed.append(True)
            raise OSError("secondary close failure")

        accepted = SimpleNamespace(setblocking=lambda value: None, close=close)

        async def accept(connection):
            return accepted, ""

        def refuse(connection):
            raise primary

        monkeypatch.setattr(asyncio.get_running_loop(), "sock_accept", accept)
        monkeypatch.setattr(server, "_UnixPeer", refuse)
        try:
            with pytest.raises(MemoryError) as caught:
                await listener.accept()
            assert caught.value is primary and closed
        finally:
            await listener.close()
    asyncio.run(scenario())
