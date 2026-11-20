"""Single-worker ASGI factory for the packaged dashboard and its live stream."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from email.utils import formatdate
from hashlib import sha256
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
import time

from joi_observer._shutdown import cancel_once, spawn
from joi_observer.ipc.client import DEFAULT_ENDPOINT, ConnectionFailure, Connector
from joi_observer.ipc.protocol import IO_CHUNK_BYTES
from joi_observer.web.api import PROGRESS_TIMEOUT, SHUTDOWN_TIMEOUT, LineSubscription, SnapshotBridge


_WRITE_TIMEOUT = 5.0
_IMMUTABLE = b"public, max-age=31536000, immutable"


async def _write(send, event, deadline: float):
    # An ASGI send is allowed to return without yielding. Enforce the same
    # absolute budget even when asyncio has not yet dispatched its timer.
    loop = asyncio.get_running_loop()
    if loop.time() >= deadline:
        raise TimeoutError
    await send(event)
    if asyncio.current_task().cancelling():
        raise asyncio.CancelledError
    if loop.time() >= deadline:
        raise TimeoutError


async def _send_body(send, body: bytes, deadline: float, *, streaming: bool):
    for offset in range(0, len(body), IO_CHUNK_BYTES):
        end = offset + IO_CHUNK_BYTES
        await _write(send, {"type": "http.response.body", "body": body[offset:end],
                            "more_body": streaming or end < len(body)}, deadline)


async def _fresh_line(reader: LineSubscription, deadline: float) -> bytes:
    try:
        async with asyncio.timeout_at(deadline):
            while asyncio.get_running_loop().time() < deadline:
                line = await anext(reader)
                if reader.current_is_fresh():
                    return line
    except TimeoutError:
        pass
    raise ConnectionFailure("No fresh snapshot.")


class WebApplication:
    """Serve fixed package resources and same-origin, read-only NDJSON."""

    def __init__(self, bridge: SnapshotBridge, *, asset_root: Traversable | None = None,
                 wall_clock: Callable[[], float] = time.time) -> None:
        """Store the bridge, packaged assets (or test directory) and UTC epoch clock."""
        self.bridge = bridge
        self.asset_root = asset_root
        self.wall_clock = wall_clock
        self._routes = {}
        self._requests = set()
        self._stopping = False

    async def __call__(self, scope: dict, receive: Callable[[], Awaitable[dict]],
                       send: Callable[[dict], Awaitable[None]]) -> None:
        """Dispatch one ASGI request or the worker lifespan.

        Startup loads the three package resources and freezes their release. A
        resource or initialization error fails startup. Host IPC is opened only
        by a live GET. Shutdown awaits the bridge's tasks and the IPC client's
        bounded close through bridge.close(). Report shutdown.failed if this
        Web-owned operation raises or misses its deadline.

        GET / returns no-cache HTML referencing the release's CSS and JS. The
        release is a 64-character lowercase hex identifier that changes with
        any of the three assets. Serve matching fixed asset routes with the
        published immutable cache policy. Unknown assets and routes return
        404, other methods on known routes return 405 (Allow: GET), and a
        query on /api/live returns 400. These routes never subscribe.

        GET /api/live returns no-store UTF-8 application/x-ndjson. Acquire a
        fresh first line on the reader's original 7 s wait budget. Immediately
        before committing live 200, check that selection and attach one UTC
        Date and one X-Joi-Sent-At in host monotonic seconds. After the header
        write, recheck the selection before the first body byte. If it expired,
        take a newer fresh line of this same attempt with any time remaining
        in the original 5 s first-write budget. Finish its chunks within that
        budget. An expired or failed attempt before headers yields a safe 503,
        and after headers terminates the response when no eligible line can
        be delivered in time. Each later complete line has its own 5 s write
        budget, in chunks of at most 64 KiB. Once a line starts, finish it
        intact or end the response. Never send a second response header.

        Observe disconnect while waiting or writing. Release a reader once on
        every exit, including cancellation and send failure. A blocked page
        cannot delay another. Finite responses have a 5 s total write budget.
        Release the reader before best-effort EOF (at most 1 s) or a safe 503.
        After a failed/timed-out send or disconnect, stop writing immediately.
        """
        if scope["type"] == "lifespan":
            await self._lifespan(receive, send)
            return
        if scope["type"] != "http":
            raise ValueError("Unsupported ASGI scope.")
        if self._stopping:
            return
        response = spawn(self._exchange(scope, receive, send))
        self._requests.add(response)
        try:
            await response
        finally:
            self._requests.discard(response)

    async def _exchange(self, scope, receive, send):
        response = asyncio.current_task()
        disconnected = False

        async def watch_disconnect():
            nonlocal disconnected
            try:
                while (await receive())["type"] != "http.disconnect":
                    pass
            except OSError:
                pass
            except Exception:
                cancel_once(response)
                raise
            disconnected = True
            cancel_once(response)

        watcher = spawn(watch_disconnect())
        try:
            await self._respond(scope, send)
        except (OSError, TimeoutError):
            # A failed write terminates this response, including its final write.
            pass
        except asyncio.CancelledError:
            if not disconnected:
                raise
        finally:
            cancel_once(watcher)
            await asyncio.gather(watcher, return_exceptions=True)
            if not watcher.cancelled():
                watcher.result()

    def _load_assets(self):
        root = self.asset_root if self.asset_root is not None else files(__package__).joinpath("static")
        assets = {name: root.joinpath(name).read_bytes()
                  for name in ("index.html", "dashboard.css", "dashboard.js")}
        digest = sha256()
        for body in assets.values():
            digest.update(len(body).to_bytes(8, "big"))
            digest.update(body)
        release = digest.hexdigest()
        html = assets["index.html"].replace(b"__JOI_RELEASE__", release.encode("ascii"))
        self._routes = {
            "/": (html, b"text/html; charset=utf-8", b"no-cache"),
            f"/static/{release}/dashboard.css": (assets["dashboard.css"], b"text/css; charset=utf-8", _IMMUTABLE),
            f"/static/{release}/dashboard.js": (assets["dashboard.js"], b"text/javascript; charset=utf-8", _IMMUTABLE),
        }

    async def _lifespan(self, receive, send):
        while True:
            event = await receive()
            if event["type"] == "lifespan.startup":
                try:
                    self._load_assets()
                except Exception:
                    await send({"type": "lifespan.startup.failed", "message": "Dashboard assets unavailable."})
                    return
                await send({"type": "lifespan.startup.complete"})
            if event["type"] == "lifespan.shutdown":
                self._stopping = True
                try:
                    loop = asyncio.get_running_loop()
                    deadline = loop.time() + SHUTDOWN_TIMEOUT
                    async with asyncio.timeout_at(deadline):
                        await self.bridge.close()
                        # Fast readers can finish their EOF. A stuck writer has no
                        # subscription to preserve once the worker is stopping.
                        if self._requests:
                            requests = tuple(self._requests)
                            _, pending = await asyncio.wait(requests, timeout=1.0)
                            for task in pending:
                                cancel_once(task)
                            if pending:
                                # Waiting on tasks must not transfer the shutdown
                                # timer's cancellation into a stalled transport.
                                await asyncio.wait(pending)
                            for task in requests:
                                if not task.cancelled():
                                    task.result()
                        if loop.time() >= deadline:
                            raise TimeoutError
                except Exception:
                    await send({"type": "lifespan.shutdown.failed", "message": "Dashboard cleanup failed."})
                else:
                    await send({"type": "lifespan.shutdown.complete"})
                return

    def _headers(self, media: bytes, cache: bytes):
        return [(b"content-type", media), (b"cache-control", cache),
                (b"date", formatdate(self.wall_clock(), usegmt=True).encode("ascii"))]

    async def _finite(self, send, status, body, media=b"text/plain; charset=utf-8",
                      cache=b"no-store", extra=()):
        headers = self._headers(media, cache)
        headers.append((b"content-length", str(len(body)).encode("ascii")))
        headers.extend(extra)
        deadline = asyncio.get_running_loop().time() + _WRITE_TIMEOUT
        async with asyncio.timeout_at(deadline):
            await _write(send, {"type": "http.response.start", "status": status, "headers": headers}, deadline)
            if body:
                await _send_body(send, body, deadline, streaming=False)
            else:
                await _write(send, {"type": "http.response.body", "body": b""}, deadline)

    async def _respond(self, scope, send):
        path = scope["path"]
        if path not in self._routes and path != "/api/live":
            await self._finite(send, 404, b"Not found.")
        elif scope["method"] != "GET":
            await self._finite(send, 405, b"Method not allowed.", extra=((b"allow", b"GET"),))
        elif path in self._routes:
            await self._finite(send, 200, *self._routes[path])
        elif scope.get("query_string"):
            await self._finite(send, 400, b"Invalid request.")
        else:
            await self._live(send)

    async def _live(self, send):
        loop = asyncio.get_running_loop()
        first_deadline = loop.time() + PROGRESS_TIMEOUT
        started = False
        try:
            async with self.bridge.subscribe() as reader:
                line = await _fresh_line(reader, first_deadline)
                write_deadline = loop.time() + _WRITE_TIMEOUT
                headers = self._headers(b"application/x-ndjson; charset=utf-8", b"no-store")
                headers.append((b"x-joi-sent-at", repr(self.bridge.clock()).encode("ascii")))
                async with asyncio.timeout_at(write_deadline):
                    await _write(send, {"type": "http.response.start", "status": 200, "headers": headers},
                                 write_deadline)
                started = True
                if not reader.current_is_fresh():
                    line = await _fresh_line(reader, write_deadline)
                async with asyncio.timeout_at(write_deadline):
                    await _send_body(send, line, write_deadline, streaming=True)
                while True:
                    line = await anext(reader)
                    write_deadline = loop.time() + _WRITE_TIMEOUT
                    async with asyncio.timeout_at(write_deadline):
                        await _send_body(send, line, write_deadline, streaming=True)
        except ConnectionFailure:
            pass
        if started:
            async with asyncio.timeout(1.0):
                await send({"type": "http.response.body", "body": b"", "more_body": False})
        else:
            await self._finite(send, 503, b"Snapshot unavailable.")


def create_app(*, endpoint: Path = DEFAULT_ENDPOINT,
               connector: Connector | None = None,
               clock: Callable[[], float] = time.monotonic,
               wall_clock: Callable[[], float] = time.time,
               asset_root: Traversable | None = None) -> WebApplication:
    """Build the worker from the package assets and one local read-only connector.

    Construction performs no I/O and never instantiates host collectors.
    """
    bridge = SnapshotBridge(endpoint, connector=connector, clock=clock)
    return WebApplication(bridge, asset_root=asset_root, wall_clock=wall_clock)
