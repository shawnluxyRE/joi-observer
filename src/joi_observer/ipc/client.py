"""One-shot local snapshot subscription and synchronous immutable cache.

Importing or constructing a client never opens a connection.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from enum import Enum
import math
from pathlib import Path
import struct
from typing import Protocol

from joi_observer.data.models import StateSnapshot
from joi_observer._shutdown import spawn, run_cleanup, await_owner, join_tasks, cancel_once
from joi_observer.ipc.protocol import FRAME_HEADER_BYTES, FRAME_TIMEOUT, IO_CHUNK_BYTES, SnapshotEnvelope
from joi_observer.ipc._worker import decode_async


DEFAULT_ENDPOINT = Path("/run/joi-observer/snapshot.sock")


class ConnectionState(str, Enum):
    NEW = "new"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FAILED = "failed"
    CLOSED = "closed"


class ConnectionFailure(Exception):
    """Safe client failure; CLI prints a fixed message, never raw transport data."""


class ReceiveStream(Protocol):
    """Byte transport boundary; no request, command or sampling method exists."""

    async def readexactly(self, count: int) -> bytes:
        """Read 1..IO_CHUNK_BYTES bytes, or raise EOF/IO error; cancellable.

        The client reads the eight-byte header first, then bounded body blocks.
        The complete declared length must never be passed as one read request.
        """
        ...

    async def close(self) -> None:
        """Idempotently release this connection only, without draining forever."""
        ...


class Connector(Protocol):
    async def connect(self, endpoint: Path) -> ReceiveStream:
        """Make one AF_UNIX connection attempt; no retries, DNS or TCP fallback."""
        ...


class UnixConnector:
    """Production local transport; construction does no IO."""

    async def connect(self, endpoint: Path) -> ReceiveStream:
        """Open one cancellable Unix stream; propagate errors to SnapshotClient."""
        reader, writer = await asyncio.open_unix_connection(str(endpoint), limit=IO_CHUNK_BYTES)
        try:
            return _UnixStream(reader, writer)
        except BaseException:
            try:
                writer.close()
                async with asyncio.timeout(0.25):
                    await writer.wait_closed()
            except BaseException:
                with suppress(BaseException):
                    writer.transport.abort()
            raise


class _UnixStream:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer

    async def readexactly(self, count):
        return await self.reader.readexactly(count)

    async def close(self):
        self.writer.close()
        try:
            async with asyncio.timeout(0.25):
                await self.writer.wait_closed()
        except (Exception, asyncio.CancelledError):
            self.writer.transport.abort()


class SnapshotClient:
    """Own one connection, one receive task and at most one complete envelope.

    connect() obtains the first validated frame before returning, then a task
    replaces the cache atomically. snapshot()/envelope()/state perform no IO.
    EOF, malformed frames, timeout or changed instance/config identity latch
    FAILED, close the stream and wake wait_failed(). No code path reconnects.
    Metadata must equal the first frame's metadata, and published_at cannot
    decrease, even when instance/config ids remain unchanged.
    Large-body validation/decoding uses controlled asynchronous execution so
    CPU work cannot occupy the UI loop indefinitely. At most one decode is in
    flight; immutable bytes enter the worker and a complete immutable envelope
    returns. Only the owning loop installs it. Cancelling a wait discards any
    late result, and close must not wait for default-executor shutdown beyond
    its budget. No worker reads or mutates this client's live cache.
    A new object is required even after failure; stale sources are ordinary
    connected data. sequence must increase, state revision must not decrease.
    A heartbeat may retain the previous state revision. Failed/closed caches
    cannot be read as current data: snapshot/envelope raise ConnectionFailure.
    """

    def __init__(self, endpoint: Path = DEFAULT_ENDPOINT, *,
                 connector: Connector | None = None,
                 timeout: float = FRAME_TIMEOUT,
                 retain_body: bool = False) -> None:
        """Store transport settings. Web consumers can retain the latest validated wire body."""
        self._retain_body = retain_body
        self.endpoint = endpoint
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Timeout must be positive and finite.")
        self.connector = connector if connector is not None else UnixConnector()
        self.timeout = timeout
        self._state = ConnectionState.NEW
        self._cached: tuple[SnapshotEnvelope, bytes | None] | None = None
        self._stream = None
        self._receiver = None
        self._ended = asyncio.Event()
        self._connecting = None
        self._close_task = None
        self._deadline = None

    @property
    def state(self) -> ConnectionState:
        """Return NEW/CONNECTING/CONNECTED/FAILED/CLOSED without IO."""
        return self._state

    async def connect(self) -> SnapshotEnvelope:
        """One attempt including first frame within timeout; valid only in NEW.

        Timeout covers connect plus whole first frame, including partial reads.
        Each subsequent frame has the same whole-frame deadline. Read the
        eight-byte header and then body blocks no larger than IO_CHUNK_BYTES;
        do not preallocate storage from the declared total length. A complete
        body larger than 8 MiB is valid. Full validation precedes cache replacement.
        Zero/truncated/malformed frames fail; all failures are translated
        to ConnectionFailure; cancellation closes and propagates cancellation.
        Repeated calls raise RuntimeError and never open another transport.
        """
        if self._state is not ConnectionState.NEW:
            raise RuntimeError("A snapshot client connects only once.")
        self._state = ConnectionState.CONNECTING
        self._connecting = asyncio.current_task()
        try:
            async with asyncio.timeout(self.timeout):
                stream = await self.connector.connect(self.endpoint)
                if self._state is not ConnectionState.CONNECTING:
                    await stream.close()
                    raise ConnectionFailure("Snapshot connection closed.")
                self._stream = stream
                first = await self._frame()
            if self._state is not ConnectionState.CONNECTING:
                raise ConnectionFailure("Snapshot connection closed.")
            self._cached = first
            self._state = ConnectionState.CONNECTED
            self._receiver = spawn(self._receive())
            return first[0]
        except asyncio.CancelledError:
            # An external close may be awaiting this task. Clean only its
            # transport here, avoiding a close-task/self-await cycle.
            self._state = ConnectionState.CLOSED
            self._cached = None
            await self._close_stream()
            self._ended.set()
            raise
        except Exception:
            await self._fail()
            raise ConnectionFailure("Snapshot connection failed.") from None
        finally:
            self._connecting = None

    def snapshot(self) -> StateSnapshot:
        """Return the current immutable StateSnapshot; never read the stream."""
        return self.envelope().snapshot

    def envelope(self) -> SnapshotEnvelope:
        """Return the atomically paired metadata, identity and snapshot cache."""
        if self._state is not ConnectionState.CONNECTED or self._cached is None:
            raise ConnectionFailure("No current snapshot connection.")
        return self._cached[0]

    def wire_publication(self) -> tuple[SnapshotEnvelope, bytes]:
        """Read the latest validated envelope and its original UTF-8 JSON body atomically.

        Available to clients created with retain_body=True. The body excludes
        the length prefix and preserves its original whitespace. Cache the pair
        only after full decode and session checks. A partial or invalid next
        frame never contributes bytes to a returned publication. Before connect,
        after failure/close, or without retention, raise ConnectionFailure.
        Ordinary snapshot()/envelope() clients need no additional body cache.
        """
        publication = self._cached
        if self._state is not ConnectionState.CONNECTED or publication is None or publication[1] is None:
            raise ConnectionFailure("No current wire publication.")
        return publication

    async def wait_failed(self) -> None:
        """Wait for terminal failure and raise ConnectionFailure; no polling IO.

        Normal close releases waiters by cancellation, not a false failure.
        Transport diagnostics and old snapshots never enter error messages.
        """
        await self._ended.wait()
        if self._state is ConnectionState.FAILED:
            raise ConnectionFailure("Snapshot connection failed.")
        raise asyncio.CancelledError

    async def close(self) -> None:
        """Cancel receiving and perform a bounded transport close, idempotently.

        Transition to CLOSED and discard cache. Never stop the service. Closing
        a NEW client performs no IO. FAILED remains observable until close.
        A normal return acknowledges client cleanup. The client handles
        transport-close errors and timeouts internally.
        """
        self._state = ConnectionState.CLOSED
        self._cached = None
        self._ended.set()
        if self._close_task is None:
            self._deadline = asyncio.get_running_loop().time() + 1.0
            await run_cleanup(self._cleanup, publish=lambda task: setattr(self, "_close_task", task))
        else:
            await await_owner(self._close_task)

    async def _cleanup(self):
        receiver, self._receiver = self._receiver, None
        tasks = {task for task in (receiver, self._connecting) if task is not None}
        for task in tasks:
            cancel_once(task)
        try:
            async with asyncio.timeout_at(self._deadline):
                await join_tasks(tasks)
        except TimeoutError:
            pass
        finally:
            # Joining can itself fail after tasks were cancelled. The stream
            # remains owned until this finally closes it.
            try:
                await self._close_stream()
            finally:
                self._ended.set()

    async def _close_stream(self):
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                async with asyncio.timeout(0.25):
                    await stream.close()
            except Exception:
                pass

    async def _fail(self):
        if self._state is not ConnectionState.CLOSED:
            self._state = ConnectionState.FAILED
            self._cached = None
        await self._close_stream()
        self._ended.set()

    async def _frame(self):
        header = await self._stream.readexactly(8)
        remaining = struct.unpack(">Q", header)[0]
        if not remaining:
            raise ConnectionFailure("Invalid snapshot frame.")
        parts = [header]
        while remaining:
            size = min(remaining, IO_CHUNK_BYTES)
            parts.append(await self._stream.readexactly(size))
            remaining -= size
            await asyncio.sleep(0)
        frame = b"".join(parts)
        del parts
        envelope = await decode_async(frame)
        return envelope, frame[FRAME_HEADER_BYTES:] if self._retain_body else None

    async def _receive(self):
        try:
            while self._state is ConnectionState.CONNECTED:
                async with asyncio.timeout(self.timeout):
                    publication = await self._frame()
                if self._state is not ConnectionState.CONNECTED:
                    return
                old = self.envelope()
                value = publication[0]
                if (value.instance_id != old.instance_id or value.config_revision != old.config_revision
                        or value.metadata != old.metadata or value.sequence <= old.sequence
                        or value.snapshot.revision < old.snapshot.revision
                        or value.published_at < old.published_at):
                    raise ConnectionFailure("Snapshot session changed.")
                self._cached = publication
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._fail()
