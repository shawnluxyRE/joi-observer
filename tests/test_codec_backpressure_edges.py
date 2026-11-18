"""Real codec pipe backpressure through clients and the owning service.

Only stdout consumption is delayed to its natural high-water pause; codecs,
child process waiting, lifecycle owners and in-memory transports remain real.
"""

import asyncio
from dataclasses import replace
import json
import logging
import math
import os

import pytest

from joi_observer.data.models import MetricCollectionResult, ObjectSpec
from joi_observer.data.state import MonitorState
from joi_observer.ipc.client import ConnectionFailure, ConnectionState, SnapshotClient
from joi_observer.ipc.protocol import IO_CHUNK_BYTES, encode_envelope
from joi_observer.monitor import Monitor
from joi_observer.runtime import CollectorComponents, CollectorRuntime
from joi_observer.service import CollectorService
from test_ipc_client import MemoryConnector, MemoryStream
from test_ipc_protocol import large_snapshot_fixture
from test_service_contract import MemoryLease, MemoryListener, MemoryLog, MemoryPeer


class BackpressuredCodec:
    """Observe real child/pipe ownership without replacing Process.wait."""

    def __init__(self, monkeypatch):
        self.children = []
        self.paused = asyncio.Event()
        self.read_gate = asyncio.Event()
        self.gate_cancelled = asyncio.Event()
        self.buffer_at_pause = None
        self.loop_errors = []
        self.loop = asyncio.get_running_loop()
        self.previous_handler = self.loop.get_exception_handler()
        self.loop.set_exception_handler(lambda loop, context: self.loop_errors.append(context))
        real_start = asyncio.create_subprocess_exec

        async def observe_start(*args, **kwargs):
            child = await real_start(*args, **kwargs)
            self.children.append(child)
            reader = child.stdout
            real_read = reader.readexactly
            real_pause = reader._transport.pause_reading

            async def delayed_read(count):
                try:
                    async with asyncio.timeout(5):
                        await self.read_gate.wait()
                except asyncio.CancelledError:
                    self.gate_cancelled.set()
                    raise
                return await real_read(count)

            def observe_pause():
                real_pause()
                self.buffer_at_pause = len(reader._buffer)
                assert self.buffer_at_pause > 2 * reader._limit
                self.paused.set()

            monkeypatch.setattr(reader, "readexactly", delayed_read)
            monkeypatch.setattr(reader._transport, "pause_reading", observe_pause)
            return child

        monkeypatch.setattr(asyncio, "create_subprocess_exec", observe_start)

    async def wait_paused(self):
        await asyncio.wait_for(self.paused.wait(), 5)
        assert len(self.children) == 1
        assert self.children[0].stdout._paused

    def assert_reaped(self):
        assert len(self.children) == 1
        child = self.children[0]
        assert child.returncode is not None
        assert child.stdout._transport.is_closing()
        assert child._transport.is_closing()
        with pytest.raises(ProcessLookupError):
            os.kill(child.pid, 0)
        assert not self.loop_errors

    async def rescue(self):
        """Bound a red baseline too; rescue occurs after measured assertions."""
        self.read_gate.set()
        for child in self.children:
            if child.returncode is None:
                try:
                    child.kill()
                except ProcessLookupError:
                    pass
            child.stdin.close()
            child.stdout._transport.close()
            await asyncio.wait_for(child.wait(), 1)
            child._transport.close()
        self.loop.set_exception_handler(self.previous_handler)


async def require_done(tasks, timeout, message):
    """Observe a deadline without cancelling a stuck product owner again."""
    _, pending = await asyncio.wait(tasks, timeout=timeout)
    assert not pending, message


def _assert_asyncio_diagnostics(records, record_property, label):
    """Record standard slow-callback timing; reject other asyncio diagnostics.

    Debug startup timing is not a resource lifetime assertion. Recognize only
    the structured WARNING emitted by BaseEventLoop._run_once, keeping unknown
    warnings and all errors visible alongside the explicit resource checks.
    """
    slow_callbacks, failures = [], []
    for record in records:
        if record.name != "asyncio" or record.levelno < logging.WARNING:
            continue
        args = record.args
        if (record.levelno == logging.WARNING and record.module == "base_events"
                and record.filename == "base_events.py" and record.funcName == "_run_once"
                and record.msg == "Executing %s took %.3f seconds"
                and type(args) is tuple and len(args) == 2 and type(args[0]) is str
                and type(args[1]) in (int, float) and math.isfinite(args[1]) and args[1] >= 0):
            slow_callbacks.append({"message": record.getMessage(), "seconds": args[1]})
        else:
            failures.append(record)
    record_property(f"asyncio_slow_callbacks_{label}", json.dumps(slow_callbacks))
    assert not failures, [record.getMessage() for record in failures]


@pytest.mark.parametrize("phase", ["first", "next"])
@pytest.mark.parametrize("trigger", ["deadline", "close"])
def test_client_backpressured_decoder_finishes_deadline_and_close(
        monkeypatch, record_testsuite_property, caplog, phase, trigger):
    async def scenario():
        large, _ = large_snapshot_fixture(32)
        compact = replace(large, snapshot=replace(large.snapshot, objects=tuple(
            replace(item, history=()) for item in large.snapshot.objects)))
        compact_wire = encode_envelope(compact)
        assert len(compact_wire) <= IO_CHUNK_BYTES
        incoming = large if phase == "first" else replace(
            large, sequence=large.sequence + 1,
            snapshot=replace(large.snapshot, revision=large.snapshot.revision + 1))
        large_wire = encode_envelope(incoming)
        stream = MemoryStream(large_wire if phase == "first" else compact_wire)
        connector = MemoryConnector(stream)
        client = SnapshotClient(connector=connector, timeout=0.5 if trigger == "deadline" else 5)
        codec = BackpressuredCodec(monkeypatch)
        baseline = asyncio.all_tasks()
        operation = closing = None
        try:
            if phase == "first":
                operation = asyncio.create_task(client.connect())
            else:
                old = await client.connect()
                assert client.envelope() is old
                stream.pending.put_nowait(large_wire)
                operation = asyncio.create_task(client.wait_failed())
            await codec.wait_paused()
            began = asyncio.get_running_loop().time()
            if trigger == "deadline":
                await require_done({operation}, 1.1, "Frame deadline stuck in real decoder cleanup")
                with pytest.raises(ConnectionFailure):
                    operation.result()
                assert client.state is ConnectionState.FAILED
                for current in (client.envelope, client.snapshot):
                    with pytest.raises(ConnectionFailure):
                        current()
                assert stream.closed
                # Late bytes and releasing the consumer cannot revive failure.
                codec.read_gate.set()
                stream.pending.put_nowait(compact_wire)
                await asyncio.sleep(0.02)
                assert client.state is ConnectionState.FAILED and len(connector.calls) == 1
            else:
                closing = asyncio.create_task(client.close())
                await require_done({closing, operation}, 1.1, "Client close stuck in real decoder cleanup")
                closing.result()
                with pytest.raises(asyncio.CancelledError):
                    operation.result()
                assert client.state is ConnectionState.CLOSED and stream.closed
                with pytest.raises(ConnectionFailure):
                    client.envelope()
            elapsed = asyncio.get_running_loop().time() - began
            record_testsuite_property(f"backpressure_client_{phase}_{trigger}_seconds", elapsed)
            assert elapsed < 1.1
            assert codec.gate_cancelled.is_set()
            codec.assert_reaped()
            assert len(connector.calls) == 1
            await client.close()
            await client.close()
            assert not (asyncio.all_tasks() - baseline)
        finally:
            await codec.rescue()
            for job in (operation, closing):
                if job is not None and not job.done() and not job.cancelling():
                    job.cancel()
            await asyncio.gather(*(job for job in (operation, closing) if job is not None),
                                 return_exceptions=True)
            await client.close()

    asyncio.run(scenario(), debug=True)
    _assert_asyncio_diagnostics(caplog.records, record_testsuite_property,
                               f"client_{phase}_{trigger}")


@pytest.mark.parametrize("trigger", ["stop", "cancel", "close"])
def test_service_backpressured_encoder_reaps_before_releasing_lease(
        tmp_path, monkeypatch, record_testsuite_property, caplog, trigger):
    async def scenario():
        large, _ = large_snapshot_fixture(32)
        config_path = tmp_path / "config.yaml"
        config_path.write_text("mount_points: []\nmodels:\n" + "".join(
            f"  - id: {item.id}\n    type: chat\n    name: Model\n"
            "    served_model_name: served/model\n    base_url: http://offline.invalid\n"
            for item in large.metadata.models), encoding="utf-8")
        codec = BackpressuredCodec(monkeypatch)
        log, listener, peer = MemoryLog(), MemoryListener(), MemoryPeer()
        listener.peers.put_nowait(peer)
        releases = []
        sources = []

        class ObservedLease(MemoryLease):
            def release(self):
                releases.append(tuple((child.returncode,
                                       child.stdout._transport.is_closing(),
                                       child._transport.is_closing()) for child in codec.children))
                super().release()

        class OfflineSource:
            def __init__(self, obj):
                self.metrics = obj.metrics
                self.spec = ObjectSpec(obj.key, tuple(replace(metric, value=None)
                                                     for metric in obj.metrics))
                self.calls = 0
                self.closed = False

            async def collect(self):
                self.calls += 1
                return MetricCollectionResult(self.spec.key, self.metrics)

            async def close(self):
                self.closed = True

        def runtime_factory(config):
            sources.extend(OfflineSource(obj) for obj in large.snapshot.objects)
            state = MonitorState(tuple(source.spec for source in sources))
            # Public State admission seeds legal recent history. The running
            # real Monitor continues sampling while its encoder is backpressured.
            start = asyncio.get_running_loop().time() - 59
            for second in range(61):
                for source in sources:
                    state.accept(MetricCollectionResult(source.spec.key, source.metrics),
                                 sampled_at=start + second * 0.9)
            updates = asyncio.Event()
            monitor = Monitor(tuple(sources), state, log, interval=0.02, on_update=updates.set)
            return CollectorRuntime(config, components=CollectorComponents(state, monitor, log, updates))

        lease = ObservedLease()
        service = CollectorService(config_path, runtime_factory=runtime_factory,
                                   listener=listener, lease=lease,
                                   host_factory=lambda: ("Host", "Ubuntu 24.04"))
        stop = asyncio.Event()
        baseline = asyncio.all_tasks()
        running = asyncio.create_task(service.run(stop))
        closing = None
        try:
            await codec.wait_paused()
            assert lease.held and not running.done()
            count = sum(source.calls for source in sources)
            await asyncio.sleep(0.04)
            assert sum(source.calls for source in sources) > count
            assert not peer.frames, "A blocked first encode must not publish a partial frame"
            began = asyncio.get_running_loop().time()
            if trigger == "stop":
                stop.set()
            elif trigger == "cancel":
                running.cancel()
            else:
                closing = asyncio.create_task(service.close())
            jobs = {running} if closing is None else {running, closing}
            await require_done(jobs, 1.1, "Service exit stuck in real encoder cleanup")
            result, = await asyncio.gather(running, return_exceptions=True)
            if trigger == "cancel":
                assert isinstance(result, asyncio.CancelledError)
            else:
                assert result is None
            if closing is not None:
                closing.result()
            elapsed = asyncio.get_running_loop().time() - began
            record_testsuite_property(f"backpressure_service_{trigger}_seconds", elapsed)
            assert elapsed < 1.1
            assert codec.gate_cancelled.is_set()
            codec.assert_reaped()
            assert len(releases) == 1 and releases[0]
            assert all(code is not None and read_closed and parent_closed
                       for code, read_closed, parent_closed in releases[0])
            assert not lease.held and listener.closed and peer.closed and log.closed
            assert sources and all(source.closed for source in sources)
            await service.close()
            assert not (asyncio.all_tasks() - baseline)
        finally:
            await codec.rescue()
            stop.set()
            for job in (running, closing):
                if job is not None and not job.done() and not job.cancelling():
                    job.cancel()
            await asyncio.gather(*(job for job in (running, closing) if job is not None),
                                 return_exceptions=True)
            await service.close()

    asyncio.run(scenario(), debug=True)
    _assert_asyncio_diagnostics(caplog.records, record_testsuite_property, f"service_{trigger}")
