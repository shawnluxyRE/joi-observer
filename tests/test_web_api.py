"""Read-only HTTP and session contracts exercised through in-process ASGI messages.

The only transport substitutes are the reader's byte stream and ASGI server.
WebApplication, SnapshotBridge, SnapshotClient and the IPC codec are production
entry points. No socket, HTTP port or monitored service is contacted.
"""

import asyncio
import copy
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import replace
from email.utils import formatdate
from importlib.resources import files
import json
import re

import pytest

from joi_observer.config import ModelType
from joi_observer.data.models import HistoryPoint
from joi_observer.ipc.client import DEFAULT_ENDPOINT, ConnectionFailure, SnapshotClient
from joi_observer.ipc.protocol import (
    FRAME_HEADER_BYTES, IO_CHUNK_BYTES, SnapshotEnvelope, build_metadata, encode_envelope,
)
from joi_observer.web.api import SnapshotBridge
from joi_observer.web.app import create_app
from test_ipc_client import MemoryStream
from test_ipc_protocol import payload, wire
from test_snapshot_pipeline import collect_reference_rounds, pipeline_config


class _AsgiExchange:
    """Deliver individual protocol events and surface application exceptions."""

    def __init__(self, app, scope):
        self.app = app
        self.scope = scope
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()

    async def start(self):
        async def run():
            try:
                await self.app(self.scope, self.incoming.get, self.send)
            finally:
                self.outgoing.put_nowait(None)

        self.task = asyncio.create_task(run())
        await asyncio.sleep(0)

    async def send(self, message):
        self.outgoing.put_nowait(message)

    async def event(self, timeout=2):
        message = await asyncio.wait_for(self.outgoing.get(), timeout)
        if message is None:
            await self.task
            raise AssertionError("ASGI application finished before the expected event")
        return message


@asynccontextmanager
async def lifespan(app):
    """Run the ASGI startup/shutdown exchange used by the container worker."""
    call = _AsgiExchange(app, {"type": "lifespan", "asgi": {"version": "3.0"}})
    call.incoming.put_nowait({"type": "lifespan.startup"})
    await call.start()
    try:
        assert (await call.event())["type"] == "lifespan.startup.complete"
        try:
            yield
        finally:
            call.incoming.put_nowait({"type": "lifespan.shutdown"})
            assert (await call.event(timeout=5))["type"] == "lifespan.shutdown.complete"
    finally:
        if not call.task.done():
            await asyncio.wait_for(call.task, 2)


class HttpRequest(_AsgiExchange):
    """One browser request. Response-body chunks need not match NDJSON lines."""

    def __init__(self, app, path="/api/live", *, method="GET", query=b""):
        super().__init__(app, {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1", "scheme": "http", "method": method, "path": path,
            "root_path": "", "raw_path": path.encode(), "query_string": query,
            "headers": [(b"host", b"dashboard.invalid")],
        })
        self.buffer = bytearray()
        self.eof = False

    async def __aenter__(self):
        self.incoming.put_nowait({"type": "http.request", "body": b"", "more_body": False})
        await self.start()
        return self

    async def __aexit__(self, *exc):
        self.incoming.put_nowait({"type": "http.disconnect"})
        if not self.task.done():
            await asyncio.wait_for(self.task, 2)
        elif (error := self.task.exception()) is not None and error is not exc[1]:
            raise error

    async def response(self, timeout=2):
        message = await self.event(timeout)
        assert message["type"] == "http.response.start"
        self.headers = message.get("headers", ())
        headers = {key.lower(): value for key, value in self.headers}
        return message["status"], headers

    async def _read(self, timeout=2):
        assert not self.eof
        message = await self.event(timeout)
        assert message["type"] == "http.response.body"
        self.buffer.extend(message.get("body", b""))
        self.eof = not message.get("more_body", False)

    async def line(self):
        while b"\n" not in self.buffer:
            assert not self.eof, "The response ended without a complete NDJSON line"
            await self._read()
        line, _, rest = self.buffer.partition(b"\n")
        self.buffer = rest
        return bytes(line + b"\n")

    async def frame(self):
        return json.loads(await self.line())

    async def finish(self, timeout=2):
        while not self.eof:
            await self._read(timeout)
        return bytes(self.buffer)


class Attempts:
    """Each explicit IPC connect consumes one supplied byte port or OS failure."""

    def __init__(self, *outcomes):
        self.outcomes = iter(outcomes)
        self.endpoints = []

    async def connect(self, endpoint):
        self.endpoints.append(endpoint)
        outcome = next(self.outcomes)
        if isinstance(outcome, OSError):
            raise outcome
        return outcome


def fixture_app(port, **kwargs):
    """The independent wire samples cover a few host seconds starting at 60."""
    return create_app(connector=port, clock=lambda: 64.0, **kwargs)


def publication(sample, sequence, published_at):
    """Advance a wire fixture on its own host clock, retaining only in-window history."""
    updated = copy.deepcopy(sample)
    updated.update(sequence=sequence, published_at=published_at)
    for obj in updated["snapshot"]["objects"]:
        obj["history"] = [point for point in obj["history"] if point["sampled_at"] >= published_at - 60]
    return updated


async def dashboard_window_payload(tmp_path):
    """One ordinary one-minute window with steady readings from the offline sources."""
    config = pipeline_config(tmp_path)
    rounds = await collect_reference_rounds(config, ModelType.EMBEDDING)
    healthy = rounds[1]
    objects = tuple(
        replace(item, sampled_at=60.0, history=tuple(
            HistoryPoint(float(second), item.metrics) for second in range(61)
        ))
        for item in healthy.objects
    )
    metadata = build_metadata(config, hostname="Offline Host", system="Ubuntu 24.04")
    envelope = SnapshotEnvelope("sample-host", "sample-config", 1, 60.0, metadata,
                                replace(healthy, objects=objects))
    return json.loads(encode_envelope(envelope)[FRAME_HEADER_BYTES:])


def test_startup_and_packaged_assets_are_available_without_ipc_or_login():
    async def scenario():
        port = Attempts()
        app = create_app(connector=port)
        async with lifespan(app):
            async with HttpRequest(app, "/") as request:
                status, headers = await request.response()
                assert status == 200 and b"text/html" in headers[b"content-type"]
                assert b"no-cache" in headers[b"cache-control"]
                document = await request.finish()
            release, = set(re.findall(rb"/static/([a-f0-9]{64})/dashboard\.(?:js|css)", document))
            assert b"__JOI_RELEASE__" not in document
            for name, media in (("dashboard.css", b"text/css"), ("dashboard.js", b"javascript")):
                path = f"/static/{release.decode()}/{name}"
                assert path.encode() in document
                async with HttpRequest(app, path) as request:
                    status, headers = await request.response()
                    assert status == 200 and media in headers[b"content-type"]
                    cache = {token.strip() for token in headers[b"cache-control"].lower().split(b",")}
                    assert {b"public", b"immutable", b"max-age=31536000"} <= cache
                    asset = files("joi_observer.web").joinpath("static", name)
                    assert await request.finish() == asset.read_bytes()
        assert port.endpoints == []

    asyncio.run(scenario())


def test_releases_do_not_mix_even_when_the_directory_changes_between_requests(tmp_path):
    changed = "dashboard.css"

    async def revision(app):
        async with HttpRequest(app, "/") as request:
            assert (await request.response())[0] == 200
            document = await request.finish()
        release, = set(re.findall(rb"/static/([a-f0-9]{64})/dashboard\.(?:js|css)", document))
        return release.decode()

    async def scenario():
        source = files("joi_observer.web").joinpath("static")
        original = {}
        for name in ("index.html", "dashboard.css", "dashboard.js"):
            original[name] = source.joinpath(name).read_bytes()
            (tmp_path / name).write_bytes(original[name])
        port = Attempts()
        a = create_app(connector=port, asset_root=tmp_path)
        async with lifespan(a):
            first = await revision(a)
            (tmp_path / changed).write_bytes(original[changed] + b"\n")
            b = create_app(connector=port, asset_root=tmp_path)
            async with lifespan(b):
                second = await revision(b)
                assert first != second and await revision(a) == first
                for name in ("dashboard.js", "dashboard.css"):
                    async with HttpRequest(a, f"/static/{first}/{name}") as old:
                        assert (await old.response())[0] == 200
                        assert await old.finish() == original[name]
                    async with HttpRequest(b, f"/static/{second}/{name}") as current:
                        assert (await current.response())[0] == 200
                        assert await current.finish() == (tmp_path / name).read_bytes()
                    async with HttpRequest(b, f"/static/{first}/{name}") as mismatched:
                        status, headers = await mismatched.response()
                        assert status == 404 and b"no-store" in headers[b"cache-control"]
                        await mismatched.finish()
        assert not port.endpoints

    asyncio.run(scenario())


@pytest.mark.parametrize("path,method,query,status", [
    ("/api/live", "POST", b"", 405),
    ("/", "DELETE", b"", 405),
    ("/api/live", "GET", b"model=other", 400),
    ("/static/config.yaml", "GET", b"", 404),
    ("/static/../app.py", "GET", b"", 404),
    ("/api/containers/restart", "POST", b"", 404),
])
def test_unknown_routes_and_commands_do_not_reach_ipc(path, method, query, status):
    async def scenario():
        port = Attempts()
        app = create_app(connector=port)
        async with lifespan(app), HttpRequest(app, path, method=method, query=query) as request:
            code, headers = await request.response()
            assert code == status
            if status == 405:
                assert headers[b"allow"] == b"GET"
            await request.finish()
        assert port.endpoints == []

    asyncio.run(scenario())


def test_wire_publication_pairs_the_checked_envelope_with_its_original_body():
    async def scenario():
        original = payload()
        first = wire(original)
        stream = MemoryStream(first)
        client = SnapshotClient(connector=Attempts(stream), retain_body=True)
        try:
            await client.connect()
            envelope, body = client.wire_publication()
            assert envelope is client.envelope() and body == first[FRAME_HEADER_BYTES:]
            update = publication(original, 2, 60)
            update["snapshot"]["revision"] += 1
            second = wire(update)
            stream.pending.put_nowait(second)
            async with asyncio.timeout(2):
                while client.envelope().sequence < 2:
                    await asyncio.sleep(0)
            newer, next_body = client.wire_publication()
            assert newer is client.envelope() and next_body == second[FRAME_HEADER_BYTES:]
            assert envelope.sequence == 1 and body == first[FRAME_HEADER_BYTES:]
            stream.pending.put_nowait(wire(dict(update, sequence=3, undisclosed="should not pass")))
            with pytest.raises(ConnectionFailure):
                await asyncio.wait_for(client.wait_failed(), 2)
            with pytest.raises(ConnectionFailure):
                client.wire_publication()
        finally:
            await client.close()

    asyncio.run(scenario())


def test_first_line_is_whitelisted_and_atomic_then_real_heartbeat_advances():
    async def scenario():
        sample = payload()
        # Extra spacing is legal in a single line and survives a byte relay.
        body = json.dumps(sample, ensure_ascii=False, separators=(", ", ": ")).encode("utf-8")
        frame = len(body).to_bytes(FRAME_HEADER_BYTES, "big") + body
        stream = MemoryStream(frame[:13])
        port = Attempts(stream)
        wall_now = [1_800_000_000.0]

        host_now = [60.0]
        app = create_app(connector=port, clock=lambda: host_now[0],
                         wall_clock=lambda: wall_now[0])
        async with lifespan(app), AsyncExitStack() as page:
            request = await page.enter_async_context(HttpRequest(app))
            # This prefix contains the length and an incomplete JSON object.
            await asyncio.sleep(0.05)
            assert request.outgoing.empty()
            wall_now[0] += 4.0
            host_now[0] += 4.0
            stream.pending.put_nowait(frame[13:])
            status, headers = await request.response()
            assert status == 200
            assert headers[b"content-type"].split(b";")[0] == b"application/x-ndjson"
            assert b"no-store" in headers[b"cache-control"]
            assert [value for name, value in request.headers if name.lower() == b"date"] == [
                formatdate(wall_now[0], usegmt=True).encode()
            ]
            sent_times = [value for key, value in request.headers if key.lower() == b"x-joi-sent-at"]
            assert len(sent_times) == 1 and float(sent_times[0]) == host_now[0]
            assert await request.line() == body + b"\n"
            heartbeat = publication(sample, 2, 61)
            # A formatted IPC body is valid too. On HTTP it occupies one line.
            pretty = json.dumps(heartbeat, ensure_ascii=False, indent=2).replace("\n", "\r\n").encode("utf-8")
            stream.pending.put_nowait(len(pretty).to_bytes(FRAME_HEADER_BYTES, "big") + pretty)
            line = await request.line()
            assert b"\r" not in line and json.loads(line) == heartbeat
            recovered = publication(heartbeat, 3, 62)
            recovered["snapshot"]["revision"] += 1
            recovered["snapshot"]["objects"][1]["stale"] = False
            stream.pending.put_nowait(wire(recovered))
            assert await request.frame() == recovered
            await page.aclose()
            assert port.endpoints == [DEFAULT_ENDPOINT] and stream.closed

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["unavailable", "invalid-whitelist"])
def test_first_failure_is_safe_and_quiet_until_a_new_request(failure):
    async def scenario():
        sample = payload()
        private = "PRIVATE-source-diagnostic"
        bad = OSError(private)
        if failure == "invalid-whitelist":
            bad = MemoryStream(wire(dict(sample, raw_error=private)))
        healthy = MemoryStream(wire(sample))
        port = Attempts(bad, healthy)
        app = fixture_app(port)
        async with lifespan(app):
            async with HttpRequest(app) as failed:
                status, headers = await failed.response()
                assert status == 503 and b"no-store" in headers[b"cache-control"]
                message = await failed.finish()
                assert message and private.encode() not in message and b'"snapshot"' not in message
            await asyncio.sleep(1.1)
            assert port.endpoints == [DEFAULT_ENDPOINT]
            async with HttpRequest(app) as refreshed:
                assert (await refreshed.response())[0] == 200
                assert await refreshed.frame() == sample
        assert port.endpoints == [DEFAULT_ENDPOINT, DEFAULT_ENDPOINT]

    asyncio.run(scenario())


def test_old_streams_cannot_follow_a_refresh_into_a_new_service_instance():
    async def scenario():
        sample = payload()
        old = MemoryStream(wire(sample))
        replacement = dict(sample, instance_id="new-instance", config_revision="new-config")
        new = MemoryStream(wire(replacement))
        port = Attempts(old, new)
        app = fixture_app(port)
        async with lifespan(app), HttpRequest(app) as a, HttpRequest(app) as b:
            for page in (a, b):
                assert (await page.response())[0] == 200
                assert await page.frame() == sample
            assert port.endpoints == [DEFAULT_ENDPOINT]
            old.pending.put_nowait(None)
            assert await a.finish() == b""
            await asyncio.sleep(1.1)
            assert port.endpoints == [DEFAULT_ENDPOINT]
            async with HttpRequest(app) as refreshed:
                assert (await refreshed.response())[0] == 200
                assert await refreshed.frame() == replacement
                # Even an old tab which deferred reading its final HTTP chunk
                # cannot see data made available by another user's refresh.
                assert await b.finish() == b""
                assert a.eof and old.closed and not new.closed
        assert new.closed and len(port.endpoints) == 2

    asyncio.run(scenario())


def test_changed_service_on_an_open_transport_requires_a_new_page_request():
    async def scenario():
        original = payload()
        replacement = publication(original, 2, 61)
        replacement.update(instance_id="restarted-host", config_revision="changed-config")
        replacement["metadata"]["hostname"] = "new-host-name"
        old = MemoryStream(wire(original))
        port = Attempts(old, MemoryStream(wire(replacement)))
        app = fixture_app(port)
        async with lifespan(app), HttpRequest(app) as left, HttpRequest(app) as right:
            for page in (left, right):
                assert (await page.response())[0] == 200
                assert await page.frame() == original

            # This full frame is valid on a new connection. No EOF precedes it.
            old.pending.put_nowait(wire(replacement))
            assert await asyncio.gather(left.finish(), right.finish()) == [b"", b""]
            assert old.closed and port.endpoints == [DEFAULT_ENDPOINT]

            async with HttpRequest(app) as refreshed:
                assert (await refreshed.response())[0] == 200
                assert await refreshed.frame() == replacement
                assert port.endpoints == [DEFAULT_ENDPOINT, DEFAULT_ENDPOINT]

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel_first", [True, False], ids=["opener-leaves", "joiner-leaves"])
def test_disconnect_during_shared_first_connect_only_detaches_that_waiter(cancel_first):
    async def scenario():
        stream = MemoryStream()
        port = Attempts(stream)
        app = fixture_app(port)
        async with lifespan(app), AsyncExitStack() as opener, AsyncExitStack() as joiner:
            first = await opener.enter_async_context(HttpRequest(app))
            # Establish which request owns the initial wait before the second arrives.
            async with asyncio.timeout(2):
                while not stream.reads:
                    await asyncio.sleep(0.005)
            second = await joiner.enter_async_context(HttpRequest(app))
            await asyncio.sleep(0.05)
            leaving, remaining = (opener, second) if cancel_first else (joiner, first)
            await leaving.aclose()
            assert len(port.endpoints) == 1 and not stream.closed
            sample = payload()
            stream.pending.put_nowait(wire(sample))
            assert (await remaining.response())[0] == 200
            assert await remaining.frame() == sample
        assert stream.closed and len(port.endpoints) == 1

    asyncio.run(scenario())


def test_last_page_leaving_before_the_first_frame_releases_the_pending_subscription():
    async def scenario():
        pending = MemoryStream()
        sample = payload()
        port = Attempts(pending, MemoryStream(wire(sample)))
        app = fixture_app(port)
        async with lifespan(app):
            async with HttpRequest(app) as page:
                async with asyncio.timeout(2):
                    while not pending.reads:
                        await asyncio.sleep(0)
                assert page.outgoing.empty()
            assert pending.closed and port.endpoints == [DEFAULT_ENDPOINT]
            async with HttpRequest(app) as reopened:
                assert (await reopened.response())[0] == 200
                assert await reopened.frame() == sample
                assert port.endpoints == [DEFAULT_ENDPOINT, DEFAULT_ENDPOINT]

    asyncio.run(scenario())


def test_application_shutdown_ends_an_open_http_stream_and_releases_ipc():
    async def scenario():
        sample = payload()
        stream = MemoryStream(wire(sample))
        port = Attempts(stream)
        app = fixture_app(port)
        async with AsyncExitStack() as worker:
            await worker.enter_async_context(lifespan(app))
            async with HttpRequest(app) as page:
                assert (await page.response())[0] == 200
                assert await page.frame() == sample
                # The browser stays connected throughout the shutdown exchange.
                await worker.aclose()
                assert stream.closed and port.endpoints == [DEFAULT_ENDPOINT]
                assert await page.finish() == b""

    asyncio.run(scenario())


def test_dashboard_window_is_complete_across_http_body_chunks(tmp_path):
    async def scenario():
        sample = await dashboard_window_payload(tmp_path)
        app = fixture_app(Attempts(MemoryStream(wire(sample))))
        async with lifespan(app), HttpRequest(app) as page:
            assert (await page.response(timeout=8))[0] == 200
            line = bytearray()
            chunks = 0
            while not line.endswith(b"\n"):
                message = await page.event()
                assert message["type"] == "http.response.body" and message["more_body"]
                chunk = message.get("body", b"")
                assert len(chunk) <= IO_CHUNK_BYTES
                if chunk:
                    chunks += 1
                line.extend(chunk)
            assert chunks > 1
            assert json.loads(line) == sample

    asyncio.run(scenario())


def test_stalled_http_writer_does_not_block_another_page():
    class SlowRequest(HttpRequest):
        def __init__(self, app):
            super().__init__(app)
            self.stalled = asyncio.Event()

        async def send(self, message):
            if message["type"] == "http.response.body" and message.get("body"):
                self.stalled.set()
                await asyncio.Future()
            await super().send(message)

    async def scenario():
        sample = payload()
        stream = MemoryStream(wire(sample))
        port = Attempts(stream)
        app = fixture_app(port)
        async with lifespan(app), HttpRequest(app) as fast:
            assert (await fast.response())[0] == 200
            assert await fast.frame() == sample
            async with SlowRequest(app) as slow:
                assert (await slow.response())[0] == 200
                await asyncio.wait_for(slow.stalled.wait(), 2)
                newer = publication(sample, 2, 61)
                stream.pending.put_nowait(wire(newer))
                assert await fast.frame() == newer
            assert not stream.closed
        assert stream.closed and len(port.endpoints) == 1

    asyncio.run(scenario())


def test_delayed_bridge_reader_remains_bound_to_its_failed_attempt():
    async def scenario():
        sample = payload()
        old = MemoryStream(wire(sample))
        replacement = dict(sample, instance_id="replacement", config_revision="next")
        new = MemoryStream(wire(replacement))
        bridge = SnapshotBridge(connector=Attempts(old, new), clock=lambda: 60.0)
        async with bridge.subscribe() as delayed, bridge.subscribe() as active:
            assert json.loads(await anext(active)) == sample
            old.pending.put_nowait(None)
            with pytest.raises(ConnectionFailure):
                await asyncio.wait_for(anext(active), 2)
            async with bridge.subscribe() as refreshed:
                assert json.loads(await anext(refreshed)) == replacement
                with pytest.raises(ConnectionFailure):
                    await asyncio.wait_for(anext(delayed), 2)
        assert old.closed and new.closed
        await bridge.close()
        await bridge.close()

    asyncio.run(scenario())
