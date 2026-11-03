"""Real HTTPX adapter checks using only in-memory transports and byte streams.

No DNS, loopback server or certificate handshake is needed. The suite-wide socket
guard stays active; TLS verification setup and TLS failure normalization are
observed separately from an actual handshake, which is deliberately not run.
"""

import asyncio
import gzip
import ssl

import httpx
import pytest

from joi_observer.collectors.vllm import (
    AsyncHttpClient, HttpBodyTooLargeError, MAX_RESPONSE_BYTES, VllmCollector,
)
from joi_observer.config import ModelConfig, ModelType
from joi_observer.error_log import ErrorKind


class MemoryStream(httpx.AsyncByteStream):
    def __init__(self, chunks=(), *, gate=None):
        self.chunks = tuple(chunks)
        self.gate = gate
        self.started = asyncio.Event()
        self.closed = False
        self.read_chunks = 0

    async def __aiter__(self):
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        for chunk in self.chunks:
            self.read_chunks += 1
            yield chunk
            await asyncio.sleep(0)

    async def aclose(self):
        self.closed = True


def memory_port(stream, *, headers=None, status=200):
    clients = []
    requests = []

    async def handle(request):
        requests.append(request)
        return httpx.Response(status, headers=headers, stream=stream)

    def factory(**options):
        client = httpx.AsyncClient(**options, transport=httpx.MockTransport(handle))
        clients.append(client)
        return client

    return AsyncHttpClient(factory), clients, requests


@pytest.mark.parametrize("size", [MAX_RESPONSE_BYTES, MAX_RESPONSE_BYTES + 1])
def test_real_httpx_gzip_uses_decompressed_limit_and_closes_response(size):
    async def case():
        encoded = gzip.compress(b"x" * size)
        assert len(encoded) < 8192
        stream = MemoryStream((encoded,))
        port, clients, requests = memory_port(stream, headers={"content-encoding": "gzip"})
        if size == MAX_RESPONSE_BYTES:
            result = await port.get("https://model.invalid/metrics", timeout=1,
                                    max_bytes=MAX_RESPONSE_BYTES)
            assert result.body == b"x" * size
        else:
            with pytest.raises(HttpBodyTooLargeError):
                await port.get("https://model.invalid/metrics", timeout=1,
                               max_bytes=MAX_RESPONSE_BYTES)
        assert stream.closed and len(requests) == 1
        await port.close()
        assert clients[0].is_closed

    asyncio.run(case())


def test_real_httpx_uncompressed_limit_stops_before_reading_remaining_stream():
    async def case():
        stream = MemoryStream((b"a" * 65536,) * 100)
        port, clients, requests = memory_port(stream)
        with pytest.raises(HttpBodyTooLargeError):
            await port.get("http://model.invalid/metrics", timeout=1, max_bytes=65536)
        assert stream.closed and stream.read_chunks == 2
        assert len(requests) == 1
        await port.close()
        assert clients[0].is_closed

    asyncio.run(case())


@pytest.mark.parametrize("action", ["cancel", "close", "timeout"])
def test_real_httpx_pending_read_releases_stream_and_client(action):
    async def case():
        stream = MemoryStream(gate=asyncio.Event())
        port, clients, requests = memory_port(stream)
        task = asyncio.create_task(port.get("https://model.invalid/metrics",
                                           timeout=0.03 if action == "timeout" else 2,
                                           max_bytes=1024))
        await asyncio.wait_for(stream.started.wait(), 0.5)
        if action == "cancel":
            task.cancel()
        elif action == "close":
            await asyncio.wait_for(port.close(), 0.25)
        with pytest.raises(TimeoutError if action == "timeout" else asyncio.CancelledError):
            await asyncio.wait_for(task, 0.25)
        assert stream.closed and len(requests) == 1
        await port.close()
        assert clients[0].is_closed

    asyncio.run(case())


@pytest.mark.parametrize("owner", ["port", "collector"])
def test_close_during_cancelled_read_does_not_interrupt_response_release(owner):
    class DelayedCloseStream(MemoryStream):
        def __init__(self):
            super().__init__(gate=asyncio.Event())
            self.closing = asyncio.Event()

        async def aclose(self):
            self.closing.set()
            await asyncio.sleep(0.03)
            self.closed = True

    async def case():
        stream = DelayedCloseStream()
        port, clients, requests = memory_port(stream)
        if owner == "collector":
            config = ModelConfig("model", ModelType.CHAT, "model", "https://model.invalid")
            resource = VllmCollector(config, port)
            task = asyncio.create_task(resource.collect())
        else:
            resource = port
            task = asyncio.create_task(port.get("https://model.invalid/metrics", timeout=1,
                                               max_bytes=1024))
        await asyncio.wait_for(stream.started.wait(), 0.5)
        task.cancel()
        await asyncio.wait_for(stream.closing.wait(), 0.5)
        await asyncio.wait_for(resource.close(), 0.25)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream.closed and clients[0].is_closed and len(requests) == 1

    asyncio.run(case())


def test_repeated_external_cancel_during_response_release_still_finishes_cleanup():
    class DelayedCloseStream(MemoryStream):
        def __init__(self):
            super().__init__(gate=asyncio.Event())
            self.closing = asyncio.Event()

        async def aclose(self):
            self.closing.set()
            await asyncio.sleep(0.03)
            self.closed = True

    async def case():
        stream = DelayedCloseStream()
        port, clients, _ = memory_port(stream)
        task = asyncio.create_task(port.get("https://model.invalid/metrics", timeout=1,
                                           max_bytes=1024))
        await asyncio.wait_for(stream.started.wait(), 0.5)
        task.cancel()
        await asyncio.wait_for(stream.closing.wait(), 0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 0.25)
        assert stream.closed
        await port.close()
        assert clients[0].is_closed

    asyncio.run(case())


@pytest.mark.parametrize("error,kind,code", [
    (httpx.ConnectError("PRIVATE TLS certificate verify failed"),
     ErrorKind.UNAVAILABLE, "source.unavailable"),
    (httpx.ReadTimeout("PRIVATE read deadline"), ErrorKind.TIMEOUT, "collection.timeout"),
])
def test_real_httpx_transport_failures_are_safe_and_stop_the_collection(error, kind, code):
    async def case():
        requests = []
        clients = []

        async def handle(request):
            requests.append(request)
            if isinstance(error, httpx.ConnectError):
                raise error from ssl.SSLCertVerificationError("PRIVATE certificate detail")
            raise error

        def factory(**options):
            client = httpx.AsyncClient(**options, transport=httpx.MockTransport(handle))
            clients.append(client)
            return client

        port = AsyncHttpClient(factory)
        config = ModelConfig("model", ModelType.CHAT, "model", "https://model.invalid")
        collector = VllmCollector(config, port)
        result = await collector.collect()
        assert result.observation is None
        assert (result.failure.kind, result.failure.code) == (kind, code)
        assert "PRIVATE" not in repr(result)
        assert [request.url.path for request in requests] == ["/version"]
        await collector.close()
        assert clients[0].is_closed

    asyncio.run(case())


def test_default_real_httpx_client_enables_certificate_checks_without_environment_proxy(monkeypatch):
    contexts = []
    requests = []
    streams = []
    original_context = ssl.create_default_context

    def observe_context(*args, **kwargs):
        context = original_context(*args, **kwargs)
        contexts.append(context)
        return context

    async def offline_request(transport, request):
        requests.append(request)
        stream = MemoryStream((b"{}",))
        streams.append(stream)
        return httpx.Response(200, stream=stream)

    monkeypatch.setattr(ssl, "create_default_context", observe_context)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", offline_request)
    monkeypatch.setenv("HTTPS_PROXY", "http://PRIVATE-proxy.invalid:8888")
    monkeypatch.setenv("SSL_CERT_FILE", "/PRIVATE/nonexistent/certificate.pem")

    async def case():
        port = AsyncHttpClient()
        assert contexts == []
        result = await port.get("https://model.invalid/version", timeout=1, max_bytes=10)
        assert result.body == b"{}"
        assert contexts and all(context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
                                for context in contexts)
        assert len(requests) == 1 and requests[0].url.host == "model.invalid"
        assert streams[0].closed
        await port.close()

    asyncio.run(case())


def test_real_httpx_redirect_stays_on_the_configured_origin():
    async def case():
        stream = MemoryStream((b"PRIVATE redirect",))
        port, clients, requests = memory_port(
            stream, status=302, headers={"location": "https://different.invalid/metrics"})
        result = await port.get("https://model.invalid/metrics", timeout=1, max_bytes=100)
        assert result.status == 302
        assert len(requests) == 1 and requests[0].url.host == "model.invalid"
        assert stream.closed
        await port.close()
        assert clients[0].is_closed

    asyncio.run(case())


def test_real_httpx_invalid_compressed_payload_is_a_response_failure():
    """A received invalid body is not a network or TLS outage."""
    async def case():
        stream = MemoryStream((b"PRIVATE invalid gzip body",))
        port, clients, requests = memory_port(stream, headers={"content-encoding": "gzip"})
        config = ModelConfig("model", ModelType.CHAT, "model", "https://model.invalid")
        collector = VllmCollector(config, port)
        try:
            result = await collector.collect()
            assert result.observation is None
            assert (result.failure.kind, result.failure.code) == (
                ErrorKind.PARSE, "response.invalid")
            assert "PRIVATE" not in repr(result)
            assert [request.url.path for request in requests] == ["/version"]
            assert stream.closed
        finally:
            await collector.close()
        assert clients[0].is_closed

    asyncio.run(case())


def test_real_httpx_checksum_failure_on_second_path_stops_and_releases_streams():
    """Decoded prefix bytes never turn a damaged gzip tail into a valid catalog."""
    async def case():
        encoded = gzip.compress(b'{"data":[{"id":"model"}]}')
        streams = [MemoryStream((b'{"version":"0.31.0"}',)),
                   MemoryStream((encoded[:-8], b"PRIVATE!"))]
        requests = []
        clients = []

        async def handle(request):
            requests.append(request)
            index = len(requests) - 1
            return httpx.Response(200, stream=streams[index],
                                  headers={"content-encoding": "gzip"} if index == 1 else None)

        def factory(**options):
            client = httpx.AsyncClient(**options, transport=httpx.MockTransport(handle))
            clients.append(client)
            return client

        port = AsyncHttpClient(factory)
        collector = VllmCollector(
            ModelConfig("model", ModelType.CHAT, "model", "https://model.invalid"), port)
        try:
            result = await collector.collect()
            assert result.observation is None
            assert (result.failure.kind, result.failure.code) == (ErrorKind.PARSE, "response.invalid")
            assert "PRIVATE" not in repr(result)
            assert [request.url.path for request in requests] == ["/version", "/v1/models"]
            assert streams[1].read_chunks == 2
            assert all(stream.closed for stream in streams)
        finally:
            await collector.close()
        assert clients[0].is_closed

    asyncio.run(case())


@pytest.mark.parametrize("action", ["cancel", "close", "timeout"])
def test_real_httpx_natural_eof_release_survives_interruption(action):
    """HTTPX also releases inside its byte iterator after the body reaches EOF."""
    class DelayedEofCloseStream(MemoryStream):
        def __init__(self):
            super().__init__((b"{}",))
            self.closing = asyncio.Event()

        async def aclose(self):
            self.closing.set()
            await asyncio.sleep(0.03)
            self.closed = True

    async def case():
        stream = DelayedEofCloseStream()
        port, clients, requests = memory_port(stream)
        task = asyncio.create_task(port.get(
            "https://model.invalid/version", timeout=0.02 if action == "timeout" else 1,
            max_bytes=1024))
        try:
            await asyncio.wait_for(stream.closing.wait(), 0.5)
            if action == "cancel":
                task.cancel()
            elif action == "close":
                await asyncio.wait_for(port.close(), 0.25)
            with pytest.raises(TimeoutError if action == "timeout" else asyncio.CancelledError):
                await asyncio.wait_for(task, 0.25)
            assert stream.closed  # the body finished, but its release must also finish
            assert len(requests) == 1
        finally:
            await port.close()
        assert clients[0].is_closed

    asyncio.run(case())


class TrackedEofRelease(MemoryStream):
    """Cooperative resource release records completion separately from its start."""
    def __init__(self, *, release_delay=0.03):
        super().__init__((b'{"version":"0.31.0"}',))
        self.release_delay = release_delay
        self.closing = asyncio.Event()
        self.close_calls = 0
        self.release_cancelled = False

    async def aclose(self):
        self.close_calls += 1
        self.closing.set()
        try:
            await asyncio.sleep(self.release_delay)
        except asyncio.CancelledError:
            self.release_cancelled = True
            raise
        finally:
            self.closed = True


def test_real_httpx_eof_repeated_cancel_then_close_finishes_one_release():
    async def case():
        stream = TrackedEofRelease()
        port, clients, requests = memory_port(stream)
        task = asyncio.create_task(port.get("https://model.invalid/version", timeout=1,
                                           max_bytes=1024))
        await asyncio.wait_for(stream.closing.wait(), 0.5)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.wait_for(port.close(), 0.25)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream.closed and not stream.release_cancelled and stream.close_calls == 1
        assert clients[0].is_closed and len(requests) == 1
        await asyncio.sleep(0)
        assert asyncio.all_tasks() == {asyncio.current_task()}

    asyncio.run(case())


def test_real_httpx_collector_total_timeout_during_eof_finishes_release_without_next_path():
    async def case():
        stream = TrackedEofRelease()
        port, clients, requests = memory_port(stream)
        config = ModelConfig("model", ModelType.CHAT, "model", "https://model.invalid")
        collector = VllmCollector(config, port, timeout=0.02)
        result = await asyncio.wait_for(collector.collect(), 0.25)
        assert (result.failure.kind, result.failure.code) == (ErrorKind.TIMEOUT, "collection.timeout")
        assert result.observation is None
        assert stream.closed and not stream.release_cancelled and stream.close_calls == 1
        assert [request.url.path for request in requests] == ["/version"]
        await collector.close()
        assert clients[0].is_closed
        await asyncio.sleep(0)
        assert asyncio.all_tasks() == {asyncio.current_task()}

    asyncio.run(case())


@pytest.mark.parametrize("action", ["cancel", "close", "timeout"])
def test_real_httpx_overdue_eof_release_is_bounded_and_leaves_no_tasks(action):
    async def case():
        stream = TrackedEofRelease(release_delay=10)
        port, clients, requests = memory_port(stream)
        task = asyncio.create_task(port.get(
            "https://model.invalid/version", timeout=0.02 if action == "timeout" else 1,
            max_bytes=1024))
        await asyncio.wait_for(stream.closing.wait(), 0.5)
        if action == "cancel":
            task.cancel()
        elif action == "close":
            await asyncio.wait_for(port.close(), 0.25)
        with pytest.raises(TimeoutError if action == "timeout" else asyncio.CancelledError):
            await asyncio.wait_for(task, 0.25)
        assert stream.closed and stream.release_cancelled and stream.close_calls == 1
        await port.close()
        assert clients[0].is_closed and len(requests) == 1
        await asyncio.sleep(0)
        assert asyncio.all_tasks() == {asyncio.current_task()}

    asyncio.run(case())


def test_real_httpx_eof_release_error_remains_a_safe_transport_failure():
    class FailingRelease(MemoryStream):
        async def aclose(self):
            self.closed = True
            raise OSError("PRIVATE release failure")

    async def case():
        stream = FailingRelease((b'{"version":"0.31.0"}',))
        port, clients, requests = memory_port(stream)
        collector = VllmCollector(
            ModelConfig("model", ModelType.CHAT, "model", "https://model.invalid"), port)
        result = await collector.collect()
        assert (result.failure.kind, result.failure.code) == (ErrorKind.UNAVAILABLE, "source.unavailable")
        assert result.observation is None and "PRIVATE" not in repr(result)
        assert stream.closed and [request.url.path for request in requests] == ["/version"]
        await collector.close()
        assert clients[0].is_closed
        await asyncio.sleep(0)
        assert asyncio.all_tasks() == {asyncio.current_task()}

    asyncio.run(case())
