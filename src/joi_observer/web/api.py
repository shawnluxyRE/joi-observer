"""One shared IPC subscription, exposed as read-only browser response streams."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Protocol

from joi_observer._shutdown import cancel_once, spawn
from joi_observer.ipc.client import (
    DEFAULT_ENDPOINT, ConnectionFailure, ConnectionState, Connector, SnapshotClient,
)


FRESH_AGE = 5.0
PROGRESS_TIMEOUT = 7.0
SHUTDOWN_TIMEOUT = 4.0
_POLL_INTERVAL = 0.05
_LINE_WHITESPACE = bytes.maketrans(b"\r\n", b"  ")
_TERMINAL_STATES = (ConnectionState.FAILED, ConnectionState.CLOSED)


class LineSubscription(Protocol):
    """A reader bound to a single upstream connection attempt."""

    def __aiter__(self) -> AsyncIterator[bytes]: ...

    async def __anext__(self) -> bytes:
        """Yield a complete fresh NDJSON line and remember the selected publication."""
        ...

    def current_is_fresh(self) -> bool:
        """Check that this reader's selected publication still belongs to a live attempt
        and its age on the host is in [0, 5] seconds. Return false before selection
        or after detach. Updates for other readers never change this selection.
        """
        ...


@dataclass(frozen=True, slots=True)
class _Publication:
    sequence: int
    published_at: float
    line: bytes


class _Attempt:
    """Own one one-shot client until its receiver and transport have closed."""

    def __init__(self, client: SnapshotClient, clock: Callable[[], float], deadline: float,
                 generation: int):
        self.client = client
        self.clock = clock
        self.deadline = deadline
        self.generation = generation
        self.readers = 0
        self.latest: _Publication | None = None
        self.changed = asyncio.Event()
        self.ended = False
        self.started = False
        self.task = spawn(self._run())

    def _notify(self):
        self.changed.set()
        self.changed = asyncio.Event()

    def _invalidate(self):
        self.ended = True
        self.latest = None
        self._notify()

    def stop(self):
        if not self.ended:
            self._invalidate()
            # A task cancelled before its first turn cannot run its finally.
            if self.started and self.client.state not in _TERMINAL_STATES:
                cancel_once(self.task)

    def accepts_readers(self) -> bool:
        return (not self.ended and self.client.state not in _TERMINAL_STATES
                and asyncio.get_running_loop().time() < self.deadline)

    def is_fresh(self, publication: _Publication) -> bool:
        return (not self.ended and self.client.state is ConnectionState.CONNECTED
                and asyncio.get_running_loop().time() < self.deadline
                and 0 <= self.clock() - publication.published_at <= FRESH_AGE)

    def _read_cache(self, now: float):
        envelope, body = self.client.wire_publication()
        previous = self.latest
        if previous is not None and envelope.sequence == previous.sequence:
            return
        if not 0 <= self.clock() - envelope.published_at <= FRESH_AGE:
            return
        if previous is None or envelope.published_at > previous.published_at:
            self.deadline = now + PROGRESS_TIMEOUT
        if b"\n" in body or b"\r" in body:
            body = body.translate(_LINE_WHITESPACE)
        self.latest = _Publication(envelope.sequence, envelope.published_at, body + b"\n")
        self._notify()

    async def _run(self):
        self.started = True
        failed = None
        loop = asyncio.get_running_loop()
        try:
            if self.ended:
                return
            await self.client.connect()
            failed = spawn(self.client.wait_failed())
            while not failed.done():
                if self.client.state in _TERMINAL_STATES:
                    # Failure is observable before transport cleanup finishes.
                    # Leave the receive task ownership of that close until it signals.
                    await failed
                    break
                now = loop.time()
                if now >= self.deadline:
                    break
                self._read_cache(now)
                await asyncio.wait((failed,), timeout=min(_POLL_INTERVAL, self.deadline - now))
        except (ConnectionFailure, asyncio.CancelledError):
            pass
        finally:
            self._invalidate()
            try:
                if failed is not None:
                    cancel_once(failed)
                    await asyncio.gather(failed, return_exceptions=True)
            finally:
                await self.client.close()


class _Reader:
    def __init__(self, attempt: _Attempt, first_deadline: float):
        self.attempt = attempt
        self.first_deadline = first_deadline
        self.selected: _Publication | None = None
        self.attached = True

    def __aiter__(self):
        return self

    def current_is_fresh(self) -> bool:
        return self.attached and self.selected is not None and self.attempt.is_fresh(self.selected)

    async def __anext__(self) -> bytes:
        attempt = self.attempt
        deadline = self.first_deadline if self.selected is None else None
        try:
            async with asyncio.timeout_at(deadline):
                while self.attached and not attempt.ended:
                    if deadline is not None and asyncio.get_running_loop().time() >= deadline:
                        break
                    latest = attempt.latest
                    if latest is not None and latest is not self.selected and attempt.is_fresh(latest):
                        self.selected = latest
                        return latest.line
                    await attempt.changed.wait()
        except TimeoutError:
            pass
        raise ConnectionFailure("No fresh snapshot.")


class SnapshotBridge:
    """Share one one-shot IPC client and the latest verified line among active pages.

    The first requesting page starts the connection. Concurrent pages join the
    same attempt. Read the envelope and body together via wire_publication() on
    SnapshotClient(retain_body=True) after its normal whitelist and session checks.
    Reuse a single-line body verbatim with one LF terminator. For an otherwise
    valid formatted JSON body, normalize physical CR/LF whitespace before
    appending LF. Preserve JSON string escapes and decimal metric tags.

    Publish the latest higher sequence with host age in [0, 5] seconds, even
    when its publication time equals the preceding one. Only the first fresh
    publication or an advancing fresh timestamp renews the attempt's 7 s
    progress deadline. Poll the local cache and observe wait_failed() while
    subscribed. Readers may skip sequences and each retains at most its current
    line plus access to the shared latest line. Source STALE is normal data.
    """

    def __init__(self, endpoint: Path = DEFAULT_ENDPOINT, *,
                 connector: Connector | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        """Use the host monotonic clock for age and event-loop time for operation deadlines."""
        self.endpoint = endpoint
        self.connector = connector
        self.clock = clock
        self._attempt: _Attempt | None = None
        self._closed = False
        self._shutdown_deadline: float | None = None

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[LineSubscription]:
        """Register a reader before waiting for its first validated line.

        Wait at most 7 s from registration for an eligible initial publication.
        Only a new request may open a new upstream attempt. IPC failure or
        expiry wakes all waiting readers of this attempt with ConnectionFailure.
        Last-reader exit closes the upstream client. Delayed results and cleanup
        belong to their original attempt and cannot affect its successor.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + PROGRESS_TIMEOUT
        if self._closed:
            raise ConnectionFailure("Snapshot bridge closed.")
        attempt = self._attempt
        generation = 1
        if attempt is not None and not attempt.accepts_readers():
            previous = attempt
            generation = previous.generation + 1
            previous.stop()
            # Concurrent refreshes admitted during this cleanup may only join
            # the immediate successor. Their original first-line budgets continue.
            try:
                async with asyncio.timeout_at(deadline):
                    await asyncio.shield(previous.task)
            except TimeoutError:
                raise ConnectionFailure("Snapshot unavailable.") from None
            if self._closed or loop.time() >= deadline:
                raise ConnectionFailure("Snapshot unavailable.")
            attempt = self._attempt
            if attempt is previous:
                attempt = None
            elif attempt.generation != generation or not attempt.accepts_readers():
                raise ConnectionFailure("Snapshot unavailable.")

        if attempt is None:
            client = SnapshotClient(self.endpoint, connector=self.connector, retain_body=True)
            attempt = self._attempt = _Attempt(client, self.clock, deadline, generation)

        reader = _Reader(attempt, deadline)
        attempt.readers += 1
        try:
            yield reader
        finally:
            reader.attached = False
            reader.selected = None
            attempt.readers -= 1
            if attempt.readers:
                attempt._notify()
            else:
                attempt.stop()
                await asyncio.shield(attempt.task)

    async def close(self) -> None:
        """Stop admission, wake readers and join owned IPC cleanup once.

        Concurrent shutdown and request exits share cleanup. Detach subscribers,
        finish the bridge's own tasks and await SnapshotClient.close(). The
        client's bounded return completes the IPC part of shutdown. Its
        transport handles close errors internally. If bridge-owned work is
        still pending at the common 4 s deadline, raise TimeoutError and
        retain ownership of pending cleanup until process exit.
        """
        self._closed = True
        if self._shutdown_deadline is None:
            self._shutdown_deadline = asyncio.get_running_loop().time() + SHUTDOWN_TIMEOUT
        attempt = self._attempt
        if attempt is not None:
            attempt.stop()
            async with asyncio.timeout_at(self._shutdown_deadline):
                await asyncio.shield(attempt.task)
