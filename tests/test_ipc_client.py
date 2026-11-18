"""Client state-machine contracts using byte streams only, never sockets."""

import asyncio
import json
from pathlib import Path
import struct

import pytest

from joi_observer.ipc.client import ConnectionFailure, ConnectionState, SnapshotClient
from joi_observer.ipc.protocol import FRAME_HEADER_BYTES, IO_CHUNK_BYTES
from test_ipc_protocol import large_snapshot_fixture, wire


def frame(*, instance="instance-a", config="config-a", sequence=1, revision=0,
          label="Host", stale=False, published_at=None, history=()):
    payload = {
        "protocol_version": 1, "instance_id": instance, "config_revision": config,
        "sequence": sequence, "published_at": 100.0 + sequence if published_at is None else published_at,
        "metadata": {"hostname": label, "system": "Ubuntu 24.04", "mount_points": [],
                     "models": [], "containers": []},
        "snapshot": {"revision": revision, "objects": [
            {"key": {"collector": "host", "object_id": "cpu"},
             "metrics": [{"name": "cpu_percent", "value": {"integer": "0"}, "unit": "%", "applicable": True}],
             "stale": stale, "sampled_at": 100.0, "history": list(history)}]},
    }
    body = json.dumps(payload).encode()
    return struct.pack(">Q", len(body)) + body


class MemoryStream:
    def __init__(self, first=b""):
        self.pending = asyncio.Queue()
        self.pending.put_nowait(first)
        self.buffer = b""
        self.reads = 0
        self.read_sizes = []
        self.closed = False

    async def readexactly(self, count):
        self.read_sizes.append(count)
        assert 1 <= count <= IO_CHUNK_BYTES
        self.reads += 1
        while len(self.buffer) < count:
            chunk = await self.pending.get()
            if chunk is None:
                raise asyncio.IncompleteReadError(self.buffer, count)
            self.buffer += chunk
        result, self.buffer = self.buffer[:count], self.buffer[count:]
        return result

    async def close(self):
        self.closed = True


class MemoryConnector:
    def __init__(self, stream=None, error=None):
        self.stream = stream
        self.error = error
        self.calls = []

    async def connect(self, endpoint):
        self.calls.append(endpoint)
        if self.error:
            raise self.error
        return self.stream


def test_complete_first_frame_and_sync_cache_have_no_transport_io():
    async def scenario():
        stream = MemoryStream(frame())
        port = MemoryConnector(stream)
        client = SnapshotClient(connector=port)
        try:
            first = await client.connect()
            assert client.state is ConnectionState.CONNECTED
            reads = stream.reads
            for _ in range(100):
                assert client.envelope() is first
                assert client.snapshot() is first.snapshot
            assert stream.reads == reads
            assert len(port.calls) == 1
        finally:
            await client.close()
        assert stream.closed and client.state is ConnectionState.CLOSED
        await client.close()
    asyncio.run(scenario())


def test_fragmented_wire_is_installed_atomically_and_old_value_stays_immutable():
    async def scenario():
        stream = MemoryStream(frame())
        client = SnapshotClient(connector=MemoryConnector(stream))
        try:
            old = await client.connect()
            second = frame(sequence=2, revision=1, stale=True)
            boundary = FRAME_HEADER_BYTES + (len(second) - FRAME_HEADER_BYTES) // 2
            await stream.pending.put(second[:boundary])
            await asyncio.sleep(0)
            assert client.envelope() is old
            await stream.pending.put(second[boundary:])
            async def updated():
                while client.envelope().sequence != 2:
                    await asyncio.sleep(0)
            await asyncio.wait_for(updated(), 0.5)
            assert client.snapshot().objects[0].stale
            assert not old.snapshot.objects[0].stale
            assert client.state is ConnectionState.CONNECTED
        finally:
            await client.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("next_frame", [
    None, struct.pack(">Q", 1) + b"{", frame(instance="new", sequence=2, revision=2),
    frame(config="new", sequence=2, revision=2), frame(sequence=1, revision=2),
    frame(sequence=2, revision=2, label="different metadata"),
    pytest.param(frame(sequence=2, revision=1), id="revision-regression"),
    pytest.param(frame(sequence=2, revision=2, published_at=100.5), id="time-regression"),
])
def test_failure_latches_and_never_reconnects_even_when_source_recovers(next_frame):
    async def scenario():
        stream = MemoryStream(frame(revision=2))
        connector = MemoryConnector(stream)
        client = SnapshotClient(connector=connector)
        try:
            await client.connect()
            await stream.pending.put(next_frame)
            with pytest.raises(ConnectionFailure):
                await asyncio.wait_for(client.wait_failed(), 0.5)
            assert client.state is ConnectionState.FAILED and stream.closed
            await stream.pending.put(frame(sequence=3, revision=3))
            await asyncio.sleep(0.02)
            assert len(connector.calls) == 1
            with pytest.raises(ConnectionFailure):
                client.snapshot()
            with pytest.raises(RuntimeError):
                await client.connect()
            assert len(connector.calls) == 1
        finally:
            await client.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("initial", [b"", b"\x00\x00"])
def test_first_frame_deadline_includes_partial_reads(initial):
    async def scenario():
        stream = MemoryStream(initial)
        connector = MemoryConnector(stream)
        client = SnapshotClient(connector=connector, timeout=0.03)
        try:
            with pytest.raises(ConnectionFailure):
                await asyncio.wait_for(client.connect(), 0.5)
            assert stream.closed and client.state is ConnectionState.FAILED
            assert len(connector.calls) == 1
        finally:
            await client.close()
    asyncio.run(scenario())


def test_post_handshake_silence_is_failure_but_new_client_can_manually_recover():
    async def scenario():
        stream = MemoryStream(frame())
        connector = MemoryConnector(stream)
        client = SnapshotClient(connector=connector, timeout=0.03)
        try:
            await client.connect()
            with pytest.raises(ConnectionFailure):
                await asyncio.wait_for(client.wait_failed(), 0.5)
            connector.stream = MemoryStream(frame(instance="new", config="new"))
            new_client = SnapshotClient(connector=connector)
            try:
                fresh = await new_client.connect()
                assert fresh.instance_id == "new" and fresh.snapshot.objects[0].history == ()
                assert client.state is ConnectionState.FAILED
                assert len(connector.calls) == 2
            finally:
                await new_client.close()
        finally:
            await client.close()
    asyncio.run(scenario())


def test_failed_initial_connect_is_not_retried_or_reported_as_source_stale():
    async def scenario():
        connector = MemoryConnector(error=OSError("private transport detail"))
        client = SnapshotClient(Path("/unavailable.sock"), connector=connector)
        try:
            with pytest.raises(ConnectionFailure) as error:
                await client.connect()
            assert "private transport detail" not in str(error.value)
            assert client.state is ConnectionState.FAILED
            await asyncio.sleep(0.02)
            assert len(connector.calls) == 1
        finally:
            await client.close()
    asyncio.run(scenario())


def test_declared_large_length_reads_bounded_blocks_until_deadline_without_preallocation():
    async def scenario():
        stream = MemoryStream(struct.pack(">Q", 2**63))
        connector = MemoryConnector(stream)
        client = SnapshotClient(connector=connector, timeout=0.03)
        try:
            with pytest.raises(ConnectionFailure):
                await asyncio.wait_for(client.connect(), 0.5)
            assert stream.read_sizes[0] == FRAME_HEADER_BYTES
            assert len(stream.read_sizes) >= 2
            assert max(stream.read_sizes) <= IO_CHUNK_BYTES
            assert stream.closed and len(connector.calls) == 1
        finally:
            await client.close()
    asyncio.run(scenario())


def test_large_complete_snapshot_is_received_in_bounded_blocks_and_installed_whole():
    async def scenario():
        expected, payload = large_snapshot_fixture()
        encoded = wire(payload)
        assert len(encoded) > 8 * 1024 * 1024
        stream = MemoryStream(encoded)
        client = SnapshotClient(connector=MemoryConnector(stream))
        try:
            actual = await asyncio.wait_for(client.connect(), 5.0)
            assert actual == expected
            assert client.envelope() is actual
            assert len(client.snapshot().objects) == len(expected.snapshot.objects)
            assert stream.read_sizes[0] == FRAME_HEADER_BYTES
            assert max(stream.read_sizes) <= IO_CHUNK_BYTES
            assert len(stream.read_sizes) > len(encoded) // IO_CHUNK_BYTES
        finally:
            await client.close()
    asyncio.run(scenario())


def test_same_revision_heartbeat_replaces_cache_when_history_expires():
    async def scenario():
        point = {"sampled_at": 100.0, "metrics": [
            {"name": "cpu_percent", "value": {"integer": "0"}, "unit": "%", "applicable": True}]}
        stream = MemoryStream(frame(revision=7, history=(point,)))
        client = SnapshotClient(connector=MemoryConnector(stream))
        try:
            old = await client.connect()
            await stream.pending.put(frame(sequence=2, revision=7, published_at=161.0))
            async def updated():
                while client.envelope().sequence != 2:
                    await asyncio.sleep(0)
            await asyncio.wait_for(updated(), 0.5)
            assert client.snapshot().revision == old.snapshot.revision == 7
            assert client.snapshot().objects[0].history == ()
            assert old.snapshot.objects[0].history
            assert client.envelope() is not old and client.state is ConnectionState.CONNECTED
        finally:
            await client.close()
    asyncio.run(scenario())
