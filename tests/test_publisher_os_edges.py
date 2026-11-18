"""Publisher resource edges and Unix OS calls, without starting any server."""

import asyncio
from dataclasses import replace
import gc
import os
from pathlib import Path
import socket
import stat
from types import SimpleNamespace

import pytest

from joi_observer.ipc import server
from joi_observer.ipc.protocol import IO_CHUNK_BYTES, decode_envelope
from joi_observer.service import CollectorService, InstanceLease, ServiceStartError
from test_service_contract import (
    MemoryLease, MemoryListener, MemoryLog, MemoryPeer, envelope_source,
    large_envelope, no_updates, runtime_fixture, until,
)


def test_publisher_pre_stopped_never_binds_or_reads_source():
    async def scenario():
        source, calls = envelope_source()
        listener = MemoryListener()
        publisher = server.SnapshotPublisher(source, listener, wait_updated=no_updates)
        stop = asyncio.Event()
        stop.set()
        await publisher.run(stop)
        assert listener.start_calls == 0 and calls == [0]
        await publisher.close()
        with pytest.raises(RuntimeError):
            await publisher.run(stop)
    asyncio.run(scenario())


def test_publisher_capacity_closes_only_the_sixty_fifth_reader_and_reuses_freed_slot():
    async def scenario():
        source, calls = envelope_source()
        listener = MemoryListener()
        peers = [MemoryPeer() for _ in range(65)]
        for peer in peers:
            await listener.peers.put(peer)
        publisher = server.SnapshotPublisher(source, listener, wait_updated=no_updates)
        stop = asyncio.Event()
        task = asyncio.create_task(publisher.run(stop))
        retry = MemoryPeer()
        try:
            await until(lambda: peers[-1].closed and all(peer.frames for peer in peers[:-1]), task)
            assert peers[-1].frames == []
            assert all(not peer.closed for peer in peers[:-1])
            assert calls == [1]
            assert len({peer.frames[0] for peer in peers[:-1]}) == 1
            await peers[0].incoming.put(b"")
            await until(lambda: peers[0].closed, task)
            await listener.peers.put(retry)
            await until(lambda: bool(retry.frames), task)
            assert not retry.closed and retry.frames[0] == peers[1].frames[0]
            assert not peers[-1].frames and all(not peer.closed for peer in peers[1:-1])
            assert calls == [1]
        finally:
            stop.set()
            await asyncio.wait_for(task, 1.2)
        assert retry.closed and all(peer.closed for peer in peers)
    asyncio.run(scenario())


def test_real_snapshot_clients_accept_coalesced_sequences_and_peer_close_independently():
    """Connect the real publisher/cache state machines through byte ports."""
    from joi_observer.ipc.client import ConnectionFailure, ConnectionState, SnapshotClient
    from test_ipc_client import MemoryConnector, MemoryStream
    from test_service_contract import StateFeed

    async def scenario():
        class DuplexPeer(MemoryPeer):
            def __init__(self, *, hold_first=False):
                super().__init__()
                self.hold_first = hold_first
                self.first_send = asyncio.Event()
                self.release = asyncio.Event()
                peer = self

                class ClientStream(MemoryStream):
                    async def close(self):
                        if not self.closed:
                            await super().close()
                            peer.incoming.put_nowait(b"")

                self.stream = ClientStream()

            async def send(self, data):
                if not self.first_send.is_set():
                    self.first_send.set()
                    if self.hold_first:
                        await self.release.wait()
                await super().send(data)
                self.stream.pending.put_nowait(data)

            async def close(self):
                if not self.closed:
                    await super().close()
                    self.stream.pending.put_nowait(None)

        feed, listener = StateFeed(), MemoryListener()
        slow_peer, fast_peer = DuplexPeer(hold_first=True), DuplexPeer()
        await listener.peers.put(slow_peer)
        await listener.peers.put(fast_peer)
        slow_connector, fast_connector = MemoryConnector(slow_peer.stream), MemoryConnector(fast_peer.stream)
        slow, fast = SnapshotClient(connector=slow_connector), SnapshotClient(connector=fast_connector)
        publisher = server.SnapshotPublisher(feed.envelope, listener, wait_updated=feed.wait_updated,
                                             heartbeat_interval=10.0)
        stop = asyncio.Event()
        publishing = asyncio.create_task(publisher.run(stop))
        connecting = asyncio.create_task(slow.connect())
        try:
            await fast.connect()
            first_fast = fast.envelope()
            await asyncio.wait_for(slow_peer.first_send.wait(), 0.5)
            assert not connecting.done() and first_fast.sequence == 1
            for expected in (2, 3, 4):
                feed.accept()
                await until(lambda: fast.envelope().sequence == expected, publishing)
            assert not connecting.done() and feed.publications == 4
            slow_peer.release.set()
            first_slow = await asyncio.wait_for(connecting, 0.5)
            await until(lambda: slow.envelope().sequence == 4, publishing)
            assert first_slow.sequence == 1
            assert [decode_envelope(frame).sequence for frame in slow_peer.frames] == [1, 4]
            assert slow.envelope() == fast.envelope()
            assert first_fast.snapshot.revision == first_slow.snapshot.revision == 0
            assert first_fast.snapshot.objects[0].metrics[0].value is None

            await slow.close()
            await until(lambda: slow_peer.closed, publishing)
            assert fast.state is ConnectionState.CONNECTED and not fast_peer.closed
            feed.accept()
            await until(lambda: fast.envelope().sequence == 5, publishing)
            assert feed.publications == 5
            assert slow.state is ConnectionState.CLOSED
            with pytest.raises(ConnectionFailure):
                slow.snapshot()
            assert len(slow_connector.calls) == len(fast_connector.calls) == 1
        finally:
            slow_peer.release.set()
            await asyncio.gather(slow.close(), fast.close())
            await asyncio.gather(connecting, return_exceptions=True)
            stop.set()
            await asyncio.wait_for(publishing, 1.2)
            await publisher.close()
        assert slow_peer.closed and fast_peer.closed and listener.closed

    asyncio.run(scenario())


def test_pending_frame_is_replaced_while_in_flight_frame_is_preserved():
    class GatedPeer(MemoryPeer):
        def __init__(self):
            super().__init__()
            self.release = asyncio.Event()
            self.first = True

        async def send(self, data):
            if self.first:
                self.first = False
                await self.release.wait()
            await super().send(data)

    async def scenario():
        source, calls = envelope_source()
        listener, peer = MemoryListener(), GatedPeer()
        await listener.peers.put(peer)
        publisher = server.SnapshotPublisher(source, listener, wait_updated=no_updates,
                                             heartbeat_interval=0.01, write_timeout=1.0)
        stop = asyncio.Event()
        task = asyncio.create_task(publisher.run(stop))
        try:
            await until(lambda: calls[0] >= 5, task)
            assert peer.frames == []
            peer.release.set()
            await until(lambda: len(peer.frames) >= 2, task)
            assert decode_envelope(peer.frames[0]).sequence == 1
            # Frames two and three were superseded while frame one was in flight.
            assert decode_envelope(peer.frames[1]).sequence >= 4
            assert not peer.closed
        finally:
            stop.set()
            await asyncio.wait_for(task, 1.2)
    asyncio.run(scenario())


def test_progress_does_not_extend_whole_frame_write_deadline():
    class ProgressPeer(MemoryPeer):
        async def send(self, data):
            await asyncio.sleep(0.015)
            await super().send(data)

    async def scenario():
        full = large_envelope()
        value = replace(full, metadata=replace(full.metadata, models=full.metadata.models[:8]),
                        snapshot=replace(full.snapshot, objects=full.snapshot.objects[:8]))
        listener, slow, healthy = MemoryListener(), ProgressPeer(), MemoryPeer()
        await listener.peers.put(slow)
        await listener.peers.put(healthy)
        publisher = server.SnapshotPublisher(lambda: value, listener, wait_updated=no_updates,
                                             write_timeout=0.04, clock=lambda: 60.0)
        stop = asyncio.Event()
        task = asyncio.create_task(publisher.run(stop))
        try:
            await until(lambda: slow.closed and bool(healthy.frames), task)
            assert 0 < len(slow.writes) < len(healthy.writes)
            assert slow.frames == [] and not healthy.closed
            assert max(healthy.writes) <= IO_CHUNK_BYTES
            assert decode_envelope(healthy.frames[0]) == value
        finally:
            stop.set()
            await asyncio.wait_for(task, 1.2)
    asyncio.run(scenario())


def test_publisher_close_cancels_in_flight_codec_job(monkeypatch):
    async def scenario():
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def blocked_encoding(envelope):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

        monkeypatch.setattr(server, "encode_async", blocked_encoding)
        source, _ = envelope_source()
        listener, peer = MemoryListener(), MemoryPeer()
        await listener.peers.put(peer)
        publisher = server.SnapshotPublisher(source, listener, wait_updated=no_updates)
        stop = asyncio.Event()
        task = asyncio.create_task(publisher.run(stop))
        await asyncio.wait_for(entered.wait(), 0.5)
        await asyncio.wait_for(publisher.close(), 0.3)
        await asyncio.wait_for(task, 0.3)
        assert cancelled.is_set() and listener.closed and peer.closed
        assert peer.frames == []
        await publisher.close()
    asyncio.run(scenario())


class FakeSocket:
    def __init__(self, fs, endpoint, events):
        self.fs, self.endpoint, self.events = fs, endpoint, events
        self.closed = False

    def setblocking(self, value):
        self.events.append(("blocking", value))

    def bind(self, path):
        assert path == str(self.endpoint)
        self.events.append(("bind", path))
        self.fs[self.endpoint] = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o700,
                                                 st_uid=os.geteuid(), st_gid=os.getegid(),
                                                 st_dev=1, st_ino=42)

    def listen(self, backlog):
        assert stat.S_IMODE(self.fs[self.endpoint].st_mode) == 0o660
        self.events.append(("listen", backlog))

    def close(self):
        self.closed = True
        self.events.append(("close",))


def fake_unix_boundary(monkeypatch, tmp_path):
    """Replace socket construction and endpoint filesystem calls only."""
    endpoint = tmp_path / "snapshot.sock"
    fs = {tmp_path: SimpleNamespace(st_mode=stat.S_IFDIR | 0o750,
                                    st_uid=os.geteuid(), st_gid=os.getegid())}
    events, sockets = [], []
    original_lstat, original_unlink = Path.lstat, Path.unlink

    def lstat(path, *args, **kwargs):
        if path == endpoint:
            if path not in fs:
                raise FileNotFoundError
            return fs[path]
        if path == tmp_path:
            return fs[path]
        return original_lstat(path, *args, **kwargs)

    def unlink(path, *args, **kwargs):
        if path == endpoint:
            events.append(("unlink",))
            del fs[path]
            return
        return original_unlink(path, *args, **kwargs)

    def chmod(path, mode, **kwargs):
        assert path == endpoint and kwargs == {"follow_symlinks": False}
        events.append(("chmod", mode))
        fs[path].st_mode = stat.S_IFSOCK | mode

    def create_socket(family, kind):
        assert (family, kind) == (socket.AF_UNIX, socket.SOCK_STREAM)
        value = FakeSocket(fs, endpoint, events)
        sockets.append(value)
        return value

    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(Path, "unlink", unlink)
    monkeypatch.setattr(server.os, "chmod", chmod)
    monkeypatch.setattr(server.socket, "socket", create_socket)
    return endpoint, fs, events, sockets


def test_unix_listener_binds_after_safe_residual_check_and_permissions(monkeypatch, tmp_path):
    async def scenario():
        endpoint, fs, events, sockets = fake_unix_boundary(monkeypatch, tmp_path)
        fs[endpoint] = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o660,
                                       st_uid=os.geteuid(), st_gid=os.getegid(),
                                       st_dev=1, st_ino=1)
        listener = server.UnixListener(endpoint)
        await listener.start()
        await listener.start()
        assert len(sockets) == 1
        assert events.index(("unlink",)) < events.index(("bind", str(endpoint)))
        assert events.index(("chmod", 0o660)) < events.index(("listen", 64))
        await listener.close()
        await listener.close()
        assert sockets[0].closed and endpoint not in fs
    asyncio.run(scenario())


@pytest.mark.parametrize("kind", [stat.S_IFREG, stat.S_IFLNK])
def test_unix_listener_never_overwrites_non_socket_endpoint(monkeypatch, tmp_path, kind):
    async def scenario():
        endpoint, fs, _, sockets = fake_unix_boundary(monkeypatch, tmp_path)
        existing = SimpleNamespace(st_mode=kind | 0o600, st_uid=os.geteuid())
        fs[endpoint] = existing
        with pytest.raises(ValueError):
            await server.UnixListener(endpoint).start()
        assert fs[endpoint] is existing and sockets == []
    asyncio.run(scenario())


@pytest.mark.parametrize("attribute,value", [
    ("st_mode", stat.S_IFDIR | 0o770),
    ("st_mode", stat.S_IFDIR | 0o755),
    ("st_mode", stat.S_IFLNK | 0o750),
    ("st_uid", -1),
    ("st_gid", -1),
])
def test_unix_listener_rejects_unsafe_parent_before_creating_socket(monkeypatch, tmp_path, attribute, value):
    async def scenario():
        endpoint, fs, events, sockets = fake_unix_boundary(monkeypatch, tmp_path)
        setattr(fs[tmp_path], attribute, value)
        with pytest.raises(ValueError):
            await server.UnixListener(endpoint).start()
        assert sockets == [] and events == [] and endpoint not in fs
    asyncio.run(scenario())


def test_unix_listener_cleanup_keeps_replaced_inode(monkeypatch, tmp_path):
    async def scenario():
        endpoint, fs, _, sockets = fake_unix_boundary(monkeypatch, tmp_path)
        listener = server.UnixListener(endpoint)
        await listener.start()
        replacement = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o660,
                                      st_uid=os.geteuid(), st_dev=1, st_ino=99)
        fs[endpoint] = replacement
        await listener.close()
        assert fs[endpoint] is replacement and sockets[0].closed
    asyncio.run(scenario())


def test_unix_listener_permission_failure_closes_socket_before_accept(monkeypatch, tmp_path):
    async def scenario():
        endpoint, fs, events, sockets = fake_unix_boundary(monkeypatch, tmp_path)

        def refusing_chmod(*args, **kwargs):
            raise PermissionError("private OS detail")

        monkeypatch.setattr(server.os, "chmod", refusing_chmod)
        with pytest.raises(PermissionError):
            await server.UnixListener(endpoint).start()
        assert sockets[0].closed and endpoint not in fs
        assert not any(event[0] == "listen" for event in events)
    asyncio.run(scenario())


def test_unix_listener_cleanup_failure_preserves_original_start_error(monkeypatch, tmp_path):
    async def scenario():
        endpoint, _, events, sockets = fake_unix_boundary(monkeypatch, tmp_path)
        primary = PermissionError("original permission failure")

        def refusing_chmod(*args, **kwargs):
            raise primary

        def refusing_unlink(path, *args, **kwargs):
            assert path == endpoint
            raise OSError("secondary cleanup failure")

        monkeypatch.setattr(server.os, "chmod", refusing_chmod)
        monkeypatch.setattr(Path, "unlink", refusing_unlink)
        with pytest.raises(PermissionError) as caught:
            await server.UnixListener(endpoint).start()
        assert caught.value is primary and sockets[0].closed
        assert not any(event[0] == "listen" for event in events)
    asyncio.run(scenario())


def test_publisher_observes_late_cleanup_failure_after_budget_expires():
    class FailingCloseListener(MemoryListener):
        async def close(self):
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                await asyncio.sleep(0)
                raise OSError("late cleanup failure")

    async def scenario():
        unobserved = []
        loop = asyncio.get_running_loop()
        previous = loop.get_exception_handler()
        loop.set_exception_handler(lambda loop, context: unobserved.append(context))
        try:
            source, calls = envelope_source()
            publisher = server.SnapshotPublisher(source, FailingCloseListener(), wait_updated=no_updates)
            await asyncio.wait_for(publisher.close(), 0.3)
            await asyncio.sleep(0.01)
            gc.collect()
            await asyncio.sleep(0)
            assert calls == [0]
            assert unobserved == []
        finally:
            loop.set_exception_handler(previous)
    asyncio.run(scenario())


def test_unix_listener_accept_and_peer_use_nonblocking_os_ports(monkeypatch, tmp_path):
    async def scenario():
        endpoint, _, _, _ = fake_unix_boundary(monkeypatch, tmp_path)
        listener = server.UnixListener(endpoint)
        await listener.start()
        loop = asyncio.get_running_loop()
        accepted = FakeSocket({}, endpoint, [])
        calls = []

        async def accept(connection):
            calls.append(("accept", connection))
            return accepted, ""

        async def send(connection, data):
            calls.append(("send", connection, data))

        async def receive(connection, count):
            calls.append(("receive", connection, count))
            return b"x"

        monkeypatch.setattr(loop, "sock_accept", accept)
        monkeypatch.setattr(loop, "sock_sendall", send)
        monkeypatch.setattr(loop, "sock_recv", receive)
        peer = await listener.accept()
        await peer.send(b"frame")
        assert await peer.receive(1) == b"x"
        assert calls[1:] == [("send", accepted, b"frame"), ("receive", accepted, 1)]
        assert ("blocking", False) in accepted.events
        with pytest.raises(ValueError):
            await peer.send(b"x" * (IO_CHUNK_BYTES + 1))
        await peer.close()
        await listener.close()
        assert accepted.closed
    asyncio.run(scenario())


def test_instance_lease_rejects_unsafe_parent_and_permissive_existing_lock(tmp_path):
    parent = tmp_path / "unsafe"
    parent.mkdir()
    parent.chmod(0o777)
    with pytest.raises(ValueError):
        InstanceLease(parent / "service.lock").acquire()
    parent.chmod(0o700)
    path = parent / "service.lock"
    path.write_text("preserve", encoding="utf-8")
    path.chmod(0o644)
    with pytest.raises(ValueError):
        InstanceLease(path).acquire()
    assert path.read_text(encoding="utf-8") == "preserve"


def test_service_pre_stopped_never_takes_lease_or_loads_config(tmp_path):
    class CountingLease(MemoryLease):
        calls = 0

        def acquire(self):
            self.calls += 1
            super().acquire()

    async def scenario():
        lease = CountingLease()
        service = CollectorService(tmp_path / "does-not-exist.yaml", lease=lease)
        stop = asyncio.Event()
        stop.set()
        await service.run(stop)
        await service.close()
        assert lease.calls == 0 and not lease.held
        with pytest.raises(RuntimeError):
            await service.run(stop)
    asyncio.run(scenario())


def test_service_warning_callback_failure_does_not_stop_collection(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("mount_points: []\nsample_interval: 1\n", encoding="utf-8")
    sources, warnings = [], []

    def runtime_factory(config):
        runtime, source, _ = runtime_fixture(config, log=MemoryLog(prepare_result=False))
        sources.append(source)
        return runtime

    def warning(message):
        warnings.append(message)
        raise RuntimeError("unreliable warning sink")

    async def scenario():
        lease = MemoryLease()
        service = CollectorService(path, runtime_factory=runtime_factory, listener=MemoryListener(),
                                   lease=lease, host_factory=lambda: ("Host", "Ubuntu 24.04"),
                                   on_warning=warning)
        stop = asyncio.Event()
        task = asyncio.create_task(service.run(stop))
        try:
            await until(lambda: bool(sources) and sources[0].calls >= 1, task)
            assert warnings == ["Error log unavailable; monitoring will continue."]
            assert lease.held and not task.done()
        finally:
            stop.set()
            await asyncio.wait_for(task, 1.2)
        assert sources[0].closed and not lease.held
    asyncio.run(scenario())


def test_encoding_failure_stops_publication_but_not_service_sampling(monkeypatch, tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("mount_points: []\nsample_interval: 1\n", encoding="utf-8")
    sources, warnings = [], []
    real_encoding = server.encode_async
    encodings = 0

    async def fail_after_first_frame(envelope):
        nonlocal encodings
        encodings += 1
        if encodings > 1:
            raise RuntimeError("private encoder fault")
        return await real_encoding(envelope)

    def runtime_factory(config):
        runtime, source, _ = runtime_fixture(config)
        sources.append(source)
        return runtime

    async def scenario():
        monkeypatch.setattr(server, "encode_async", fail_after_first_frame)
        listener, peer, lease = MemoryListener(), MemoryPeer(), MemoryLease()
        await listener.peers.put(peer)
        service = CollectorService(path, runtime_factory=runtime_factory, listener=listener,
                                   lease=lease, host_factory=lambda: ("Host", "Ubuntu 24.04"),
                                   on_warning=warnings.append)
        stop = asyncio.Event()
        task = asyncio.create_task(service.run(stop))
        try:
            await until(lambda: peer.closed and listener.closed, task)
            before = sources[0].calls
            await until(lambda: sources[0].calls > before, task, timeout=2.5)
            assert not task.done() and lease.held and encodings == 2
            assert warnings == ["Snapshot publishing stopped; collection continues. Restart collector service to restore access."]
        finally:
            stop.set()
            await asyncio.wait_for(task, 1.2)
        assert sources[0].closed and not lease.held
    asyncio.run(scenario())


def test_partial_service_start_shares_cleanup_budget_before_releasing_lease(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("mount_points: []\nsample_interval: 1\n", encoding="utf-8")

    async def scenario():
        finish_start, release_source = asyncio.Event(), asyncio.Event()
        source_closing, source_cancelled = asyncio.Event(), asyncio.Event()
        runtime, source, log = runtime_fixture()

        async def close_source():
            source_closing.set()
            try:
                await release_source.wait()
            finally:
                source.closed = True
                source_cancelled.set()

        source.close = close_source

        class SlowStartingListener(MemoryListener):
            async def start(self):
                self.start_calls += 1
                self.started.set()
                await finish_start.wait()

            async def close(self):
                await asyncio.sleep(0.18)
                self.closed = True
                finish_start.set()

        listener, lease = SlowStartingListener(), MemoryLease()
        service = CollectorService(path, runtime_factory=lambda config: runtime,
                                   listener=listener, lease=lease,
                                   host_factory=lambda: ("Host", "Ubuntu 24.04"))
        running = asyncio.create_task(service.run(asyncio.Event()))
        try:
            await asyncio.wait_for(listener.started.wait(), 0.5)
            started = asyncio.get_running_loop().time()
            await service.close()
            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(0)
            assert elapsed < 1.1
            assert source.calls == 0 and source_closing.is_set() and log.closed
            assert not lease.held
            assert source_cancelled.is_set(), "service released its lease while cancellable source cleanup was still active"
        finally:
            release_source.set()
            finish_start.set()
            await asyncio.gather(running, return_exceptions=True)
            await runtime.close()
            await service.close()
    asyncio.run(scenario())


def test_bind_failure_uses_one_shared_service_cleanup_budget(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("mount_points: []\nsample_interval: 1\n", encoding="utf-8")

    async def scenario():
        release_source = asyncio.Event()
        runtime, source, log = runtime_fixture()

        async def close_source():
            try:
                await release_source.wait()
            finally:
                source.closed = True

        source.close = close_source

        class FailingListener(MemoryListener):
            async def start(self):
                raise OSError("offline bind failure")

            async def close(self):
                await asyncio.sleep(0.18)
                self.closed = True

        listener, lease = FailingListener(), MemoryLease()
        service = CollectorService(path, runtime_factory=lambda config: runtime,
                                   listener=listener, lease=lease,
                                   host_factory=lambda: ("Host", "Ubuntu 24.04"))
        try:
            started = asyncio.get_running_loop().time()
            with pytest.raises(ServiceStartError):
                await service.run(asyncio.Event())
            elapsed = asyncio.get_running_loop().time() - started
            assert source.calls == 0 and listener.closed and log.closed and not lease.held
            assert elapsed < 1.1, "publisher cleanup and runtime cleanup must share one service deadline"
        finally:
            release_source.set()
            await runtime.close()
            await service.close()
            await asyncio.sleep(0)
    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["producer", "accept-loop", "accept-loop-large", "stop-wait", "close-wait", "update-wait", "heartbeat", "reader"])
def test_publisher_task_allocation_failure_releases_all_previously_acquired_work(monkeypatch, stage):
    async def scenario():
        baseline = asyncio.all_tasks()
        original_task = asyncio.create_task
        event_waits = 0
        refused = []

        def refuse_one(coroutine, *args, **kwargs):
            nonlocal event_waits
            code = getattr(coroutine, "cr_code", None)
            if code is asyncio.Event.wait.__code__:
                event_waits += 1
            reject = (
                stage == "producer" and code is server.SnapshotPublisher._produce.__code__
                or stage in ("accept-loop", "accept-loop-large") and code is server.SnapshotPublisher._accept.__code__
                or stage == "stop-wait" and code is asyncio.Event.wait.__code__ and event_waits == 1
                or stage == "close-wait" and code is asyncio.Event.wait.__code__ and event_waits == 2
                or stage == "update-wait" and code is no_updates.__code__
                or stage == "heartbeat" and code is asyncio.sleep.__code__
                or stage == "reader" and code is server.SnapshotPublisher._serve.__code__
            )
            if reject and not refused:
                refused.append(stage)
                coroutine.close()
                raise MemoryError("offline publisher task allocation failure")
            return original_task(coroutine, *args, **kwargs)

        class Listener(MemoryListener):
            def __init__(self):
                super().__init__()
                self.accepted = []

            async def accept(self):
                peer = await super().accept()
                self.accepted.append(peer)
                return peer

        monkeypatch.setattr(asyncio, "create_task", refuse_one)
        source, _ = envelope_source()
        if stage == "accept-loop-large":
            from test_ipc_protocol import large_snapshot_fixture
            large, _ = large_snapshot_fixture(2)
            source = lambda: large
        listener = Listener()
        listener.peers.put_nowait(MemoryPeer())
        publisher = server.SnapshotPublisher(source, listener, wait_updated=no_updates)
        try:
            with pytest.raises(MemoryError):
                await publisher.run(asyncio.Event())
            assert refused == [stage] and listener.closed
            assert all(peer.closed for peer in listener.accepted), "an accepted peer cannot be detached by reader-task allocation failure"
            assert not {task for task in asyncio.all_tasks() - baseline if not task.done()}, (
                "publisher close must join tasks acquired before a later allocation failed")
        finally:
            await publisher.close()
            for peer in listener.accepted:
                await peer.close()
            remaining = {task for task in asyncio.all_tasks() - baseline
                         if task is not asyncio.current_task() and not task.done()}
            for task in remaining:
                task.cancel()
            await asyncio.gather(*remaining, return_exceptions=True)
    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["sender", "incoming"])
def test_reader_task_allocation_failure_does_not_keep_its_stream_or_orphan_sender(monkeypatch, stage):
    async def scenario():
        baseline = asyncio.all_tasks()
        original_task = asyncio.create_task
        refused = asyncio.Event()

        def refuse_one(coroutine, *args, **kwargs):
            code = getattr(coroutine, "cr_code", None)
            reject = (stage == "sender" and code is server.SnapshotPublisher._send.__code__
                      or stage == "incoming" and code is MemoryPeer.receive.__code__)
            if reject and not refused.is_set():
                refused.set()
                coroutine.close()
                raise MemoryError("offline reader task allocation failure")
            return original_task(coroutine, *args, **kwargs)

        monkeypatch.setattr(asyncio, "create_task", refuse_one)
        source, _ = envelope_source()
        listener, peer = MemoryListener(), MemoryPeer()
        listener.peers.put_nowait(peer)
        publisher = server.SnapshotPublisher(source, listener, wait_updated=no_updates)
        stop = asyncio.Event()
        running = original_task(publisher.run(stop))
        try:
            await asyncio.wait_for(refused.wait(), 0.5)
            # Give the reader's normal finally/close path an opportunity to run;
            # no arbitrary port delay or cancellation suppression is injected.
            await asyncio.sleep(0.02)
            assert peer.closed, "a partially initialized reader must release its accepted stream"
            stop.set()
            outcome, = await asyncio.wait_for(asyncio.gather(running, return_exceptions=True), 0.5)
            assert outcome is None or isinstance(outcome, MemoryError)
            assert not {task for task in asyncio.all_tasks() - baseline if not task.done()}
        finally:
            stop.set()
            await asyncio.gather(running, return_exceptions=True)
            await publisher.close()
            await peer.close()
            remaining = {task for task in asyncio.all_tasks() - baseline
                         if task is not asyncio.current_task() and not task.done()}
            for task in remaining:
                task.cancel()
            await asyncio.gather(*remaining, return_exceptions=True)
    asyncio.run(scenario())


def test_publisher_cleanup_task_allocation_failure_still_releases_listener_and_readers(monkeypatch):
    async def scenario():
        source, _ = envelope_source()
        listener, peer = MemoryListener(), MemoryPeer()
        listener.peers.put_nowait(peer)
        publisher = server.SnapshotPublisher(source, listener, wait_updated=no_updates)
        stop = asyncio.Event()
        running = asyncio.create_task(publisher.run(stop))
        original_task = asyncio.create_task
        refused = []

        def refuse_cleanup(coroutine, *args, **kwargs):
            if getattr(coroutine, "cr_code", None) is server.SnapshotPublisher._cleanup.__code__ and not refused:
                refused.append(True)
                coroutine.close()
                raise MemoryError("offline publisher cleanup task allocation failure")
            return original_task(coroutine, *args, **kwargs)

        try:
            await until(lambda: bool(peer.frames), running)
            monkeypatch.setattr(asyncio, "create_task", refuse_cleanup)
            stop.set()
            result, = await asyncio.wait_for(asyncio.gather(running, return_exceptions=True), 0.5)
            assert result is None or isinstance(result, MemoryError)
            assert refused == [True]
            assert listener.closed and peer.closed, "failed cleanup owner allocation must not detach active publication resources"
        finally:
            stop.set()
            await publisher.close()
            await asyncio.gather(running, return_exceptions=True)
    asyncio.run(scenario())
