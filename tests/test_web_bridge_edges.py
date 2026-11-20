"""Exercise publication progress, first-line selection and independent HTTP readers."""

import asyncio
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from joi_observer.ipc.client import DEFAULT_ENDPOINT, ConnectionFailure
from joi_observer.web.api import SnapshotBridge
from joi_observer.web.app import create_app
from test_ipc_client import MemoryStream
from test_ipc_protocol import payload, wire
from test_web_api import (
    Attempts, HttpRequest, _AsgiExchange, dashboard_window_payload, fixture_app, lifespan, publication,
)


@contextmanager
def elapsed_time():
    """Advance asyncio's deadlines without sleeping for production timeout intervals."""
    loop = asyncio.get_running_loop()
    real_time = loop.time
    offset = 0.0

    def advance(seconds):
        nonlocal offset
        offset += seconds

    with patch.object(loop, "time", lambda: real_time() + offset):
        yield advance


def test_new_reader_rechecks_publication_age_and_waits_for_a_normal_fresh_frame():
    async def scenario():
        sample = payload()
        now = [60.0]
        stream = MemoryStream(wire(sample))
        attempts = Attempts(stream)
        app = create_app(connector=attempts, clock=lambda: now[0])
        async with lifespan(app), HttpRequest(app) as existing:
            assert (await existing.response())[0] == 200
            assert await existing.frame() == sample
            now[0] = 65.0
            async with HttpRequest(app) as boundary:
                assert (await boundary.response())[0] == 200
                assert await boundary.frame() == sample
            now[0] += 0.001
            async with HttpRequest(app) as waiting:
                stream.pending.put_nowait(wire(publication(sample, 2, 60.0005)))
                newer = publication(sample, 3, now[0])
                await asyncio.sleep(0.15)
                assert waiting.outgoing.empty()
                assert existing.outgoing.empty(), "An old record must not replace a live dashboard"
                stream.pending.put_nowait(wire(newer))
                assert (await waiting.response())[0] == 200
                assert await waiting.frame() == newer
                assert await existing.frame() == newer
        assert attempts.endpoints == [DEFAULT_ENDPOINT] and stream.closed

    asyncio.run(scenario())


def test_fresh_equal_time_updates_data_without_renewing_upstream_liveness():
    async def scenario():
        sample = payload()
        now = [60.0]
        stream = MemoryStream(wire(sample))
        port = Attempts(stream)
        app = create_app(connector=port, clock=lambda: now[0])
        with elapsed_time() as advance:
            async with lifespan(app), HttpRequest(app) as page:
                assert (await page.response())[0] == 200 and await page.frame() == sample

                # A higher sequence can carry a real status change at the same time.
                advance(4)
                now[0] = 64
                changed = publication(sample, 2, 60)
                changed["snapshot"]["revision"] += 1
                changed["snapshot"]["objects"][0]["metrics"][0]["value"] = "Running"
                stream.pending.put_nowait(wire(changed))
                assert await page.frame() == changed
                async with HttpRequest(app) as joined:
                    assert (await joined.response())[0] == 200 and await joined.frame() == changed
                    advance(2)
                    now[0] = 66
                    # This later timestamp is already stale; IPC itself is still alive.
                    stream.pending.put_nowait(wire(publication(changed, 3, 60.25)))
                    await asyncio.sleep(0.15)
                    advance(2)
                    now[0] = 68
                    # The original 7 s deadline is past. A mistaken renewal at
                    # t=4 would run until t=11 and could deliver this fresh row.
                    stream.pending.put_nowait(wire(publication(changed, 4, now[0])))
                    async with asyncio.timeout(2):
                        ends = await asyncio.gather(page.finish(), joined.finish())
                    assert ends == [b"", b""], "Both original readers must end before the late publication"
            assert stream.closed and port.endpoints == [DEFAULT_ENDPOINT]

    asyncio.run(scenario())


class HeldHTTPWrite(HttpRequest):
    """One ASGI writer with a controllable header, body chunk or final message."""

    def __init__(self, app, stage, *, chunk_number=1, path="/api/live", error=False):
        super().__init__(app, path)
        self.stage = stage
        self.chunk_number = chunk_number
        self.error = error
        self.hit = asyncio.Event()
        self.release = asyncio.Event()
        self.chunks = 0
        self.attempts_after_hold = []

    async def send(self, message):
        if self.hit.is_set():
            self.attempts_after_hold.append(message["type"])
        phase = "start"
        if message["type"] == "http.response.body":
            if message.get("body"):
                self.chunks += 1
                phase = "chunk" if self.chunks == self.chunk_number else "other"
            else:
                phase = "end"
        if phase == self.stage and not self.hit.is_set():
            self.hit.set()
            if self.error:
                raise BrokenPipeError("private writer diagnostic")
            await self.release.wait()
        await super().send(message)


def test_reader_freshness_stays_bound_to_its_own_bytes_across_shared_cache_replacement():
    async def scenario():
        now = [60.0]
        first = payload()
        stream = MemoryStream(wire(first))
        bridge = SnapshotBridge(connector=Attempts(stream), clock=lambda: now[0])
        try:
            async with bridge.subscribe() as held:
                assert not held.current_is_fresh()
                await anext(held)
                now[0] = 65.0
                assert held.current_is_fresh()
                now[0] += 0.001
                stream.pending.put_nowait(wire(publication(first, 2, now[0])))
                async with bridge.subscribe() as other:
                    newest_line = await anext(other)
                    assert other.current_is_fresh() and not held.current_is_fresh()
                    assert await anext(held) == newest_line and held.current_is_fresh()
                    stream.pending.put_nowait(None)
                    with pytest.raises(ConnectionFailure):
                        await asyncio.wait_for(anext(other), 2)
                    assert not held.current_is_fresh()
                assert not other.current_is_fresh()
        finally:
            await bridge.close()

    asyncio.run(scenario())


class ClosingStream(MemoryStream):
    def __init__(self, first=b""):
        super().__init__(first)
        self.closing = asyncio.Event()
        self.release = asyncio.Event()

    async def close(self):
        self.closing.set()
        await self.release.wait()
        await super().close()


async def wait_for_pending_requests(*pages):
    # Let each ASGI exchange consume its initial event while the prior
    # transport is held in close, before releasing it or advancing the clock.
    async with asyncio.timeout(2):
        while any(not page.incoming.empty() for page in pages):
            await asyncio.sleep(0)


def test_new_page_during_failed_transport_cleanup_gets_the_replacement_instance():
    async def scenario():
        sample = payload()
        replacement = dict(sample, instance_id="next-instance", config_revision="next-config")
        old = ClosingStream(wire(sample))
        new = MemoryStream(wire(replacement))
        port = Attempts(old, new)
        app = fixture_app(port)
        async with lifespan(app), HttpRequest(app) as existing:
            assert (await existing.response())[0] == 200
            assert await existing.frame() == sample
            old.pending.put_nowait(None)
            await asyncio.wait_for(old.closing.wait(), 2)
            # The IPC receiver has observed EOF and entered transport cleanup.
            # A fresh GET now can wait for that cleanup and open the replacement.
            async with HttpRequest(app) as reopened:
                old.release.set()
                status, _ = await reopened.response()
                assert status == 200
                assert await reopened.frame() == replacement
                assert await existing.finish() == b""
                assert port.endpoints == [DEFAULT_ENDPOINT, DEFAULT_ENDPOINT]

    asyncio.run(scenario())


@pytest.mark.parametrize("replacement_available", [True, False])
def test_two_refreshes_during_first_frame_failure_share_one_replacement(replacement_available):
    async def scenario():
        old = ClosingStream()
        old.pending.put_nowait(None)
        replacement = dict(payload(), instance_id="replacement", config_revision="replacement-config")

        class AfterClose(Attempts):
            async def connect(self, endpoint):
                if self.endpoints:
                    assert old.closed, "Replacement started before the old transport closed"
                return await super().connect(endpoint)

        port = AfterClose(old, MemoryStream(wire(replacement)) if replacement_available else OSError())
        app = fixture_app(port)
        async with lifespan(app), HttpRequest(app) as original:
            await asyncio.wait_for(old.closing.wait(), 2)
            async with HttpRequest(app) as left, HttpRequest(app) as right:
                await wait_for_pending_requests(left, right)
                assert not old.closed and port.endpoints == [DEFAULT_ENDPOINT]
                assert left.outgoing.empty() and right.outgoing.empty()
                old.release.set()
                assert (await original.response())[0] == 503
                expected = 200 if replacement_available else 503
                for page in (left, right):
                    assert (await page.response())[0] == expected
                    if replacement_available:
                        assert await page.frame() == replacement
                assert port.endpoints == [DEFAULT_ENDPOINT, DEFAULT_ENDPOINT]

    asyncio.run(scenario())


def test_refresh_whose_deadline_elapsed_in_cleanup_cannot_open_an_upstream():
    async def scenario():
        old = ClosingStream(wire(payload()))
        port = Attempts(old, MemoryStream(wire(payload())))
        app = fixture_app(port)
        with elapsed_time() as advance:
            async with lifespan(app), HttpRequest(app) as original:
                assert (await original.response())[0] == 200
                await original.frame()
                old.pending.put_nowait(None)
                await asyncio.wait_for(old.closing.wait(), 2)
                async with HttpRequest(app) as expired:
                    await wait_for_pending_requests(expired)
                    advance(7.1)
                    old.release.set()
                    assert (await expired.response())[0] == 503
                    assert await original.finish() == b""
                    assert port.endpoints == [DEFAULT_ENDPOINT]
                async with HttpRequest(app) as fresh:
                    assert (await fresh.response())[0] == 200
                    assert await fresh.frame() == payload()
                    assert port.endpoints == [DEFAULT_ENDPOINT, DEFAULT_ENDPOINT]

    asyncio.run(scenario())


def test_recovered_reader_finishes_its_line_then_gets_the_latest_pending_publication(tmp_path):
    async def scenario():
        sample = await dashboard_window_payload(tmp_path)
        stream = MemoryStream(wire(sample))
        port = Attempts(stream)
        app = fixture_app(port)
        async with lifespan(app), HttpRequest(app) as fast, HeldHTTPWrite(app, "chunk", chunk_number=2) as slow:
            assert (await fast.response())[0] == (await slow.response())[0] == 200
            assert await fast.frame() == sample
            await asyncio.wait_for(slow.hit.wait(), 2)
            try:
                for seq in (2, 3, 4):
                    latest = publication(sample, seq, 60 + seq / 10)
                    stream.pending.put_nowait(wire(latest))
                    assert await fast.frame() == latest
            finally:
                slow.release.set()
            # The first chunk arrived before updates. The rest of that same
            # original line must still parse; a FIFO would next produce seq 2.
            assert await slow.frame() == sample
            assert await slow.frame() == latest
            assert port.endpoints == [DEFAULT_ENDPOINT]

    asyncio.run(scenario())


def test_transport_oserror_is_local_to_the_page_and_never_starts_a_second_response():
    async def scenario():
        sample = payload()
        stream = MemoryStream(wire(sample))
        port = Attempts(stream)
        app = fixture_app(port)
        async with lifespan(app), HttpRequest(app) as fast:
            assert (await fast.response())[0] == 200 and await fast.frame() == sample
            async with HeldHTTPWrite(app, "chunk", error=True) as broken:
                assert (await broken.response())[0] == 200
                await asyncio.wait_for(broken.task, 1)
                assert broken.hit.is_set() and not broken.attempts_after_hold
            next_line = publication(sample, 2, 61)
            stream.pending.put_nowait(wire(next_line))
            assert await fast.frame() == next_line and not stream.closed
        assert stream.closed and port.endpoints == [DEFAULT_ENDPOINT]

    asyncio.run(scenario())


def test_waiting_headers_can_switch_to_a_fresh_first_line_before_body_starts():
    async def scenario():
        sample = payload()
        stream = MemoryStream(wire(sample))
        port = Attempts(stream)
        now = [64.9]
        app = create_app(connector=port, clock=lambda: now[0])
        async with lifespan(app), HttpRequest(app) as fast, HeldHTTPWrite(app, "start") as opening:
            assert (await fast.response())[0] == 200 and await fast.frame() == sample
            await asyncio.wait_for(opening.hit.wait(), 2)
            now[0] = 65.1
            fresh = publication(sample, 2, now[0])
            stream.pending.put_nowait(wire(fresh))
            # The bridge already has fresh bytes when the first page can write again.
            assert await fast.frame() == fresh
            opening.release.set()
            assert (await opening.response())[0] == 200 and await opening.frame() == fresh
            later = publication(sample, 3, now[0] + 1)
            now[0] += 1
            stream.pending.put_nowait(wire(later))
            assert await opening.frame() == later
        assert stream.closed and port.endpoints == [DEFAULT_ENDPOINT]

    asyncio.run(scenario())


def test_live_header_and_first_line_share_one_write_budget_and_the_fast_reader_continues():
    class SlowFirstWrite(HttpRequest):
        def __init__(self, app):
            super().__init__(app)
            self.entered_header = asyncio.Event()
            self.release_header = asyncio.Event()
            self.entered_body = asyncio.Event()
            self.attempted_after_timeout = False

        async def send(self, message):
            if self.entered_body.is_set():
                self.attempted_after_timeout = True
            if message["type"] == "http.response.start":
                self.entered_header.set()
                await self.release_header.wait()
            elif message.get("body"):
                self.entered_body.set()
                await asyncio.Future()
            await super().send(message)

    async def scenario():
        sample = payload()
        stream = MemoryStream(wire(sample))
        port = Attempts(stream)
        app = fixture_app(port)
        with elapsed_time() as advance:
            async with lifespan(app), HttpRequest(app) as fast, SlowFirstWrite(app) as slow:
                assert (await fast.response())[0] == 200 and await fast.frame() == sample
                await asyncio.wait_for(slow.entered_header.wait(), 2)
                advance(3)
                newer = publication(sample, 2, 61)
                stream.pending.put_nowait(wire(newer))
                assert await fast.frame() == newer
                slow.release_header.set()
                assert (await slow.response())[0] == 200
                await asyncio.wait_for(slow.entered_body.wait(), 2)
                advance(3)
                # The total deadline has passed although neither individual write took five seconds.
                await asyncio.wait_for(asyncio.shield(slow.task), 1)
                assert not slow.attempted_after_timeout
                latest = publication(sample, 3, 62)
                stream.pending.put_nowait(wire(latest))
                assert await fast.frame() == latest and not stream.closed
            assert stream.closed and port.endpoints == [DEFAULT_ENDPOINT]

    asyncio.run(scenario())


def test_blocked_finite_error_headers_are_released_without_touching_ipc():
    async def scenario():
        port = Attempts()
        app = fixture_app(port)
        with elapsed_time() as advance:
            async with lifespan(app), HeldHTTPWrite(app, "start", path="/missing") as page:
                await asyncio.wait_for(page.hit.wait(), 2)
                advance(6)
                await asyncio.wait_for(asyncio.shield(page.task), 2)
                assert not page.attempts_after_hold and not port.endpoints

    asyncio.run(scenario())


def test_stream_end_releases_its_subscription_before_the_bounded_final_send():
    async def scenario():
        sample = payload()
        old, new = MemoryStream(wire(sample)), MemoryStream(wire(sample))
        port = Attempts(old, new)
        app = fixture_app(port)
        with elapsed_time() as advance:
            async with lifespan(app), HeldHTTPWrite(app, "end") as page:
                assert (await page.response())[0] == 200 and await page.frame() == sample
                old.pending.put_nowait(None)
                await asyncio.wait_for(page.hit.wait(), 2)
                async with HttpRequest(app) as refreshed:
                    assert (await refreshed.response())[0] == 200 and await refreshed.frame() == sample
                    assert old.closed and not new.closed
                advance(2)
                await asyncio.wait_for(asyncio.shield(page.task), 2)
                assert not page.attempts_after_hold
            assert port.endpoints == [DEFAULT_ENDPOINT] * 2

    asyncio.run(scenario())


@pytest.mark.parametrize("stalled_cleanup", [False, True], ids=["cooperative", "missed-deadline"])
def test_lifespan_joins_blocked_writer_and_disconnect_observer_within_one_budget(stalled_cleanup):
    class ObservedInput(asyncio.Queue):
        def __init__(self):
            super().__init__()
            self.released = False

        async def get(self):
            try:
                return await super().get()
            except asyncio.CancelledError:
                self.released = True
                raise

    class BlockedPage(HttpRequest):
        def __init__(self, app):
            super().__init__(app)
            self.incoming = ObservedInput()
            self.writing = asyncio.Event()
            self.stopping = asyncio.Event()
            self.release = asyncio.Event()
            self.finished_write = False

        async def send(self, event):
            if event.get("body"):
                self.writing.set()
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    self.stopping.set()
                    if stalled_cleanup:
                        await self.release.wait()
                    raise
                finally:
                    self.finished_write = True
            await super().send(event)

    async def scenario():
        stream = MemoryStream(wire(payload()))
        app = fixture_app(Attempts(stream))
        page = BlockedPage(app)

        class Worker(_AsgiExchange):
            async def send(self, event):
                if event["type"] == "lifespan.shutdown.complete":
                    assert page.finished_write and page.incoming.released
                await super().send(event)

        worker = Worker(app, {"type": "lifespan"})
        worker.incoming.put_nowait({"type": "lifespan.startup"})
        await worker.start()
        assert (await worker.event())["type"] == "lifespan.startup.complete"
        await page.__aenter__()
        try:
            await asyncio.wait_for(page.writing.wait(), 2)
            with elapsed_time() as advance:
                async with HttpRequest(app) as fast:
                    assert (await fast.response())[0] == 200 and await fast.frame() == payload()
                    loop = asyncio.get_running_loop()
                    shutdown_started = loop.time()
                    worker.incoming.put_nowait({"type": "lifespan.shutdown"})
                    assert await fast.finish() == b""
                    await asyncio.wait_for(page.stopping.wait(), 4)
                    if stalled_cleanup:
                        advance(max(0, shutdown_started + 4.1 - loop.time()))
                        assert (await worker.event(timeout=0.5))["type"] == "lifespan.shutdown.failed"
                        assert not page.finished_write
                    else:
                        assert (await worker.event())["type"] == "lifespan.shutdown.complete"
                    assert stream.closed
        finally:
            page.release.set()
            if not page.task.done() and not page.stopping.is_set():
                page.task.cancel()
            if not worker.task.done():
                worker.task.cancel()
            await asyncio.gather(page.task, worker.task, return_exceptions=True)
        assert page.finished_write and page.incoming.released

    asyncio.run(scenario())
