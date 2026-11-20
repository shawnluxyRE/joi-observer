"""常驻采集与只读发布黑盒；全部传输为内存端口，不连接本地或远程服务。"""

import asyncio
from pathlib import Path
import struct
import threading
import time

import pytest

from joi_observer.config import AppConfig, ConfigError, ModelType
from joi_observer.data.models import (
    HistoryPoint, Metric, MetricCollectionResult, ObjectKey, ObjectSnapshot, ObjectSpec, StateSnapshot,
)
from joi_observer.data.state import MonitorState
from joi_observer.ipc.protocol import (
    IO_CHUNK_BYTES, DisplayMetadata, ModelDisplay, SnapshotEnvelope, decode_envelope,
)
from joi_observer.ipc.server import SnapshotPublisher
from joi_observer.monitor import Monitor
from joi_observer.error_log import ErrorKind, Failure
from joi_observer.runtime import CollectorComponents, CollectorRuntime
from joi_observer.service import CollectorService, InstanceLease, ServiceAlreadyRunning, ServiceStartError


class MemoryLog:
    def __init__(self, *, prepare_result=True):
        self.closed = False
        self.prepare_result = prepare_result

    def prepare(self):
        return self.prepare_result

    def record(self, *args, **kwargs):
        pass

    def recovered(self, *args):
        pass

    async def close(self, *, timeout=1.0):
        self.closed = True
        return True


class SampleSource:
    spec = ObjectSpec(ObjectKey("host", "cpu"), (Metric("cpu_percent", None, "%"),))

    def __init__(self):
        self.calls = 0
        self.closed = False

    async def collect(self):
        self.calls += 1
        return MetricCollectionResult(self.spec.key, (Metric("cpu_percent", 25.0, "%"),))

    async def close(self):
        self.closed = True


class MemoryPeer:
    def __init__(self, *, stalled=False):
        self.frames = []
        self.writes = []
        self.buffer = bytearray()
        self.incoming = asyncio.Queue()
        self.closed = False
        self.stalled = stalled

    async def send(self, data):
        if self.stalled:
            await asyncio.Future()
        assert 0 < len(data) <= IO_CHUNK_BYTES
        self.writes.append(len(data))
        self.buffer.extend(data)
        while len(self.buffer) >= 8:
            length = struct.unpack(">Q", self.buffer[:8])[0]
            if len(self.buffer) < 8 + length:
                break
            self.frames.append(bytes(self.buffer[:8 + length]))
            del self.buffer[:8 + length]
        await asyncio.sleep(0)

    async def receive(self, max_bytes):
        value = await self.incoming.get()
        return value[:max_bytes]

    async def close(self):
        self.closed = True


class MemoryListener:
    def __init__(self):
        self.started = asyncio.Event()
        self.peers = asyncio.Queue()
        self.closed = False
        self.accept_calls = 0
        self.start_calls = 0

    async def start(self):
        self.start_calls += 1
        self.started.set()

    async def accept(self):
        self.accept_calls += 1
        value = await self.peers.get()
        if isinstance(value, Exception):
            raise value
        return value

    async def close(self):
        self.closed = True


class MemoryLease:
    def __init__(self):
        self.held = False

    def acquire(self):
        assert not self.held
        self.held = True

    def release(self):
        self.held = False


async def until(predicate, task, *, timeout=1.0):
    async def check():
        while not predicate():
            if task.done():
                await task
                raise AssertionError("Service stopped before the expected observation")
            await asyncio.sleep(0.005)
    await asyncio.wait_for(check(), timeout)


def runtime_fixture(config=None, *, log=None):
    config = config or AppConfig(sample_interval=0.02)
    source = SampleSource()
    mounts = tuple(ObjectSpec(ObjectKey("storage", f"mount-{i}"), (
        Metric("used_bytes", None, "B"), Metric("total_bytes", None, "B"),
        Metric("used_percent", None, "%"))) for i, _ in enumerate(config.mount_points))
    state = MonitorState((source.spec, *mounts))
    log = log or MemoryLog()
    updates = asyncio.Event()
    monitor = Monitor((source,), state, log, interval=config.sample_interval, on_update=updates.set)
    runtime = CollectorRuntime(config, components=CollectorComponents(state, monitor, log, updates))
    return runtime, source, log


def test_runtime_samples_without_terminal_or_clients_and_stops_owned_resources():
    async def scenario():
        runtime, source, log = runtime_fixture()
        assert runtime.prepare_log()
        stop = asyncio.Event()
        task = asyncio.create_task(runtime.run(stop))
        try:
            await until(lambda: source.calls >= 3, task)
            snapshot = runtime.snapshot()
            assert snapshot.objects[0].metrics == (Metric("cpu_percent", 25.0, "%"),)
            assert snapshot.objects[0].history
        finally:
            stop.set()
            await asyncio.wait_for(task, 1.2)
        await runtime.close()
        await runtime.close()
        assert source.closed and log.closed
    asyncio.run(scenario())


def test_runtime_pre_stopped_does_not_collect():
    async def scenario():
        runtime, source, _ = runtime_fixture()
        stop = asyncio.Event()
        stop.set()
        await runtime.run(stop)
        assert source.calls == 0
    asyncio.run(scenario())


def test_runtime_snapshot_reads_do_not_schedule_samples_or_mutate_revision():
    async def scenario():
        runtime, source, _ = runtime_fixture()
        assert runtime.prepare_log()
        first = runtime.snapshot()
        for _ in range(100):
            assert runtime.snapshot() == first
        assert source.calls == 0
        await runtime.close()
    asyncio.run(scenario())


def test_runtime_wait_updated_uses_real_monitor_notifications_without_sampling():
    async def scenario():
        runtime, source, _ = runtime_fixture()
        assert runtime.prepare_log()
        revision = runtime.snapshot().revision
        waiting = asyncio.create_task(runtime.wait_updated(revision))
        await asyncio.sleep(0)
        assert not waiting.done() and source.calls == 0
        stop = asyncio.Event()
        sampling = asyncio.create_task(runtime.run(stop))
        try:
            await asyncio.wait_for(waiting, 0.5)
            assert runtime.snapshot().revision > revision and source.calls >= 1
            # Updates that precede the wait must not be lost by event clearing.
            await asyncio.wait_for(runtime.wait_updated(revision), 0.1)
        finally:
            stop.set()
            await asyncio.wait_for(sampling, 1.2)
            if not waiting.done():
                waiting.cancel()
                await asyncio.gather(waiting, return_exceptions=True)
    asyncio.run(scenario())


def envelope_source():
    counter = [0]
    def source():
        counter[0] += 1
        return SnapshotEnvelope("instance-a", "config-a", counter[0], time.monotonic(),
                                DisplayMetadata("Host", "Ubuntu 24.04"), StateSnapshot(()))
    return source, counter


async def no_updates(after_revision):
    """An idle external snapshot source; it never requests or produces samples."""
    await asyncio.Future()


def test_publisher_explicit_start_binds_once_without_reading_source():
    async def scenario():
        source, calls = envelope_source()
        listener, reader = MemoryListener(), MemoryPeer()
        publisher = SnapshotPublisher(source, listener, wait_updated=no_updates)
        stop = asyncio.Event()
        task = None
        try:
            await publisher.start()
            await publisher.start()
            assert listener.start_calls == 1 and calls[0] == 0
            await listener.peers.put(reader)
            task = asyncio.create_task(publisher.run(stop))
            await until(lambda: bool(reader.frames), task)
            assert listener.start_calls == 1 and calls[0] == 1
        finally:
            stop.set()
            if task is not None:
                await asyncio.wait_for(task, 1.2)
            await publisher.close()
    asyncio.run(scenario())


def test_service_bind_failure_never_starts_sampling_and_releases_resources(tmp_path):
    class RefusingListener(MemoryListener):
        async def start(self):
            self.start_calls += 1
            raise OSError("private binding diagnostic")

    path = tmp_path / "config.yaml"
    path.write_text("mount_points: []\nsample_interval: 1\n", encoding="utf-8")
    runtime, source, log = runtime_fixture(AppConfig(sample_interval=1, mount_points=()))

    async def scenario():
        listener, lease = RefusingListener(), MemoryLease()
        service = CollectorService(path, runtime_factory=lambda config: runtime,
                                   listener=listener, lease=lease,
                                   host_factory=lambda: ("Host", "Ubuntu 24.04"))
        with pytest.raises(ServiceStartError) as caught:
            await service.run(asyncio.Event())
        assert "private binding diagnostic" not in str(caught.value)
        assert source.calls == 0 and source.closed and log.closed
        assert listener.closed and not lease.held and listener.accept_calls == 0
        await service.close()
    asyncio.run(scenario())


class StateFeed:
    """Real State with an external notification boundary for publisher-only tests."""

    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.state = MonitorState((SampleSource.spec,), clock=clock)
        self.updated = asyncio.Event()
        self.publications = 0

    def envelope(self):
        self.publications += 1
        now = self.clock()
        return SnapshotEnvelope("instance-a", "config-a", self.publications, now,
                                DisplayMetadata("Host", "Ubuntu 24.04"), self.state.snapshot())

    async def wait_updated(self, after_revision):
        while self.state.snapshot().revision <= after_revision:
            self.updated.clear()
            await self.updated.wait()

    def accept(self, *, stale=False):
        failure = Failure(ErrorKind.UNEXPECTED, "collector.unexpected", "Unexpected collector failure.") if stale else None
        result = MetricCollectionResult(SampleSource.spec.key, (Metric("cpu_percent", 25.0, "%"),),
                                        failure=failure)
        self.state.accept(result, sampled_at=self.clock())
        self.updated.set()


def test_state_changes_publish_before_heartbeat_and_preserve_failure_recovery():
    async def scenario():
        feed, listener = StateFeed(), MemoryListener()
        left, right = MemoryPeer(), MemoryPeer()
        await listener.peers.put(left)
        await listener.peers.put(right)
        publisher = SnapshotPublisher(feed.envelope, listener, wait_updated=feed.wait_updated)
        stop = asyncio.Event()
        task = asyncio.create_task(publisher.run(stop))
        try:
            await until(lambda: bool(left.frames) and bool(right.frames), task)
            assert feed.publications == 1  # adding readers did not call the source
            feed.accept(stale=True)
            await until(lambda: len(left.frames) >= 2 and len(right.frames) >= 2, task, timeout=0.5)
            failed = decode_envelope(left.frames[-1])
            assert failed.snapshot.objects[0].stale
            assert left.frames[-1] == right.frames[-1]
            feed.accept()
            await until(lambda: len(left.frames) >= 3 and len(right.frames) >= 3, task, timeout=0.5)
            recovered = decode_envelope(left.frames[-1])
            assert not recovered.snapshot.objects[0].stale
            assert recovered.snapshot.revision > failed.snapshot.revision
            assert any(point.metrics is None for point in recovered.snapshot.objects[0].history)
            assert feed.publications == 3
        finally:
            stop.set()
            await asyncio.wait_for(task, 1.2)
    asyncio.run(scenario())


def large_envelope():
    """Over 8 MiB of valid one-second history, with no fabricated metric fields."""
    metrics = (
        Metric("running", 1, "seq"), Metric("waiting", 0, "seq"), Metric("total", 1, "seq"),
        Metric("decode_rate", 25.0, "tok/s"), Metric("prefill_rate", 50.0, "tok/s"),
        Metric("rate", None, "seq/s", False), Metric("ttft_seconds", 0.1, "s"),
        Metric("queue_seconds", 0.0, "s"), Metric("latency_seconds", None, "s", False),
        Metric("kv_cache_percent", 10.0, "%"),
    )
    history = tuple(HistoryPoint(float(at), metrics) for at in range(61))
    models = tuple(ModelDisplay(f"chat-{i}", ModelType.CHAT, f"Chat {i}", f"served-{i}")
                   for i in range(256))
    objects = tuple(ObjectSnapshot(ObjectKey("vllm", model.id), metrics, False, 60.0, history)
                    for model in models)
    return SnapshotEnvelope("large-instance", "large-config", 1, 60.0,
                            DisplayMetadata("Host", "Ubuntu 24.04", models=models), StateSnapshot(objects))


def test_large_complete_snapshot_is_sent_as_bounded_byte_writes_without_truncation():
    async def scenario():
        value, listener, reader = large_envelope(), MemoryListener(), MemoryPeer()
        await listener.peers.put(reader)
        publisher = SnapshotPublisher(lambda: value, listener, wait_updated=no_updates, clock=lambda: 60.0)
        stop = asyncio.Event()
        task = asyncio.create_task(publisher.run(stop))
        try:
            await until(lambda: bool(reader.frames), task, timeout=2.0)
            assert len(reader.frames[0]) - 8 > 8 * 1024 * 1024
            assert max(reader.writes) <= IO_CHUNK_BYTES and len(reader.writes) > 1
            assert decode_envelope(reader.frames[0]) == value
            assert not reader.closed and not task.done()
        finally:
            stop.set()
            await asyncio.wait_for(task, 1.2)
    asyncio.run(scenario())


def test_two_clients_share_publications_and_disconnect_is_isolated():
    async def scenario():
        source, counter = envelope_source()
        listener = MemoryListener()
        left, right = MemoryPeer(), MemoryPeer()
        await listener.peers.put(left)
        await listener.peers.put(right)
        publisher = SnapshotPublisher(source, listener, wait_updated=no_updates, heartbeat_interval=0.02)
        stop = asyncio.Event()
        task = asyncio.create_task(publisher.run(stop))
        try:
            await until(lambda: len(left.frames) >= 2 and len(right.frames) >= 2, task)
            assert left.frames[0] == right.frames[0]
            assert decode_envelope(left.frames[0]).sequence == 1
            assert counter[0] <= max(len(left.frames), len(right.frames)) + 1
            await left.incoming.put(b"")
            await until(lambda: left.closed, task)
            previous = len(right.frames)
            await until(lambda: len(right.frames) > previous, task)
            assert not right.closed
        finally:
            stop.set()
            await asyncio.wait_for(task, 1.2)
        assert listener.closed and right.closed
    asyncio.run(scenario())


@pytest.mark.parametrize("payload", [b'collect', b'{"command":"exec"}', b'\x00'])
def test_client_input_is_rejected_without_invoking_commands(payload):
    async def scenario():
        source, _ = envelope_source()
        listener = MemoryListener()
        attacker, healthy = MemoryPeer(), MemoryPeer()
        await listener.peers.put(attacker)
        await listener.peers.put(healthy)
        publisher = SnapshotPublisher(source, listener, wait_updated=no_updates, heartbeat_interval=0.02)
        stop = asyncio.Event()
        task = asyncio.create_task(publisher.run(stop))
        try:
            await until(lambda: bool(attacker.frames) and bool(healthy.frames), task)
            await attacker.incoming.put(payload)
            await until(lambda: attacker.closed, task)
            count = len(healthy.frames)
            await until(lambda: len(healthy.frames) > count, task)
            assert not healthy.closed
        finally:
            stop.set()
            await asyncio.wait_for(task, 1.2)
    asyncio.run(scenario())


def test_slow_client_is_closed_while_healthy_client_continues():
    async def scenario():
        source, _ = envelope_source()
        listener = MemoryListener()
        slow, healthy = MemoryPeer(stalled=True), MemoryPeer()
        await listener.peers.put(slow)
        await listener.peers.put(healthy)
        publisher = SnapshotPublisher(source, listener, wait_updated=no_updates,
                                      heartbeat_interval=0.01, write_timeout=0.03)
        stop = asyncio.Event()
        task = asyncio.create_task(publisher.run(stop))
        try:
            await until(lambda: slow.closed and len(healthy.frames) >= 3, task)
            assert not healthy.closed
        finally:
            stop.set()
            await asyncio.wait_for(task, 1.2)
    asyncio.run(scenario())


def test_instance_lock_conflict_then_manual_reacquire(tmp_path):
    path = tmp_path / "service.lock"
    first, second = InstanceLease(path), InstanceLease(path)
    first.acquire()
    try:
        with pytest.raises(ServiceAlreadyRunning):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()
    second.release()
    assert path.is_file()  # keep the inode: unlink would allow split-lock ownership


def test_instance_lock_rejects_symbolic_link(tmp_path):
    target = tmp_path / "ordinary-file"
    target.write_text("preserve", encoding="utf-8")
    link = tmp_path / "service.lock"
    link.symlink_to(target)
    with pytest.raises((ValueError, OSError)):
        InstanceLease(link).acquire()
    assert target.read_text(encoding="utf-8") == "preserve"


def test_invalid_service_config_does_not_construct_runtime(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("sample_interval: invalid\n", encoding="utf-8")
    calls = []
    def factory(config):
        calls.append(config)
        raise AssertionError("Invalid config must be rejected first")
    async def scenario():
        lease = MemoryLease()
        service = CollectorService(config_path, runtime_factory=factory, listener=MemoryListener(),
                                   lease=lease, host_factory=lambda: ("Host", "Ubuntu 24.04"))
        with pytest.raises(ConfigError):
            await service.run(asyncio.Event())
        assert calls == [] and not lease.held
    asyncio.run(scenario())


def test_unwritable_log_warns_once_and_service_keeps_collecting(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("mount_points: []\nsample_interval: 1\n", encoding="utf-8")
    warnings, sources = [], []
    def factory(config):
        runtime, source, _ = runtime_fixture(config, log=MemoryLog(prepare_result=False))
        sources.append(source)
        return runtime

    async def scenario():
        service = CollectorService(config_path, runtime_factory=factory, listener=MemoryListener(),
                                   lease=MemoryLease(), host_factory=lambda: ("Host", "Ubuntu 24.04"),
                                   on_warning=warnings.append)
        stop = asyncio.Event()
        task = asyncio.create_task(service.run(stop))
        try:
            await until(lambda: bool(sources) and sources[0].calls >= 2, task, timeout=2.5)
            assert warnings == ["Error log unavailable; monitoring will continue."]
        finally:
            stop.set()
            await asyncio.wait_for(task, 1.2)
    asyncio.run(scenario())


def test_service_client_disconnect_does_not_stop_sampling_or_other_reader(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("mount_points: []\nsample_interval: 1\n", encoding="utf-8")
    sources = []
    def factory(config):
        runtime, source, _ = runtime_fixture(config)
        sources.append(source)
        return runtime

    async def scenario():
        listener = MemoryListener()
        left, right = MemoryPeer(), MemoryPeer()
        await listener.peers.put(left)
        await listener.peers.put(right)
        service = CollectorService(config_path, runtime_factory=factory, listener=listener,
                                   lease=MemoryLease(), host_factory=lambda: ("Host", "Ubuntu 24.04"))
        stop = asyncio.Event()
        task = asyncio.create_task(service.run(stop))
        try:
            await until(lambda: bool(left.frames) and bool(right.frames), task)
            assert len(sources) == 1
            await left.incoming.put(b"")
            await until(lambda: left.closed, task)
            previous = sources[0].calls
            await until(lambda: sources[0].calls >= previous + 2, task, timeout=2.5)
            assert not right.closed and not task.done()
            assert service.export_snapshot().snapshot.objects[0].metrics[0].value == 25.0
            frame_count = len(right.frames)
            await until(lambda: len(right.frames) > frame_count, task, timeout=1.5)
        finally:
            stop.set()
            await asyncio.wait_for(task, 1.2)
        assert right.closed and sources[0].closed
    asyncio.run(scenario())


def test_running_config_is_frozen_and_restart_creates_fresh_instance_history(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("mount_points: ['/old']\nsample_interval: 1\n", encoding="utf-8")
    configs = []
    sources = []
    def factory(config):
        configs.append(config)
        runtime, source, _ = runtime_fixture(config)
        sources.append(source)
        return runtime

    async def session():
        listener, peer, lease = MemoryListener(), MemoryPeer(), MemoryLease()
        await listener.peers.put(peer)
        service = CollectorService(config_path, runtime_factory=factory, listener=listener,
                                   lease=lease, host_factory=lambda: ("Host", "Ubuntu 24.04"))
        stop = asyncio.Event()
        task = asyncio.create_task(service.run(stop))
        await until(lambda: bool(peer.frames), task)
        return service, stop, task, peer, lease

    async def scenario():
        first, stop, task, peer, lease = await session()
        try:
            initial = decode_envelope(peer.frames[0])
            assert initial.metadata.mount_points == ("/old",)
            config_path.write_text("mount_points: ['/new']\nsample_interval: 1\n", encoding="utf-8")
            await until(lambda: sources[0].calls >= 2, task, timeout=2.5)
            old = first.export_snapshot()
            assert old.metadata.mount_points == ("/old",)
            old_latest = max(point.sampled_at for obj in old.snapshot.objects for point in obj.history)
            assert len(configs) == 1
        finally:
            stop.set()
            await asyncio.wait_for(task, 1.2)
        assert not lease.held
        second, stop2, task2, peer2, lease2 = await session()
        try:
            fresh = decode_envelope(peer2.frames[0])
            assert fresh.instance_id != initial.instance_id
            assert fresh.config_revision != initial.config_revision
            assert fresh.metadata.mount_points == ("/new",)
            assert len(configs) == 2
            assert all(point.sampled_at > old_latest
                       for obj in fresh.snapshot.objects for point in obj.history)
        finally:
            stop2.set()
            await asyncio.wait_for(task2, 1.2)
        assert not lease2.held
    asyncio.run(scenario())


def test_running_publisher_failure_closes_connections_but_sampling_continues(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("mount_points: []\nsample_interval: 1\n", encoding="utf-8")
    sources, warnings = [], []
    def factory(config):
        runtime, source, _ = runtime_fixture(config)
        sources.append(source)
        return runtime

    async def scenario():
        listener, reader, lease = MemoryListener(), MemoryPeer(), MemoryLease()
        await listener.peers.put(reader)
        service = CollectorService(config_path, runtime_factory=factory, listener=listener,
                                   lease=lease, host_factory=lambda: ("Host", "Ubuntu 24.04"),
                                   on_warning=warnings.append)
        stop = asyncio.Event()
        task = asyncio.create_task(service.run(stop))
        try:
            await until(lambda: bool(reader.frames), task)
            await listener.peers.put(OSError("private OS diagnostic"))
            await until(lambda: listener.closed and reader.closed, task)
            previous_calls = sources[0].calls
            accepts = listener.accept_calls
            await until(lambda: sources[0].calls > previous_calls, task, timeout=2.5)
            assert not task.done() and lease.held
            assert warnings == ["Snapshot publishing stopped; collection continues. Restart collector service to restore access."]
            assert listener.accept_calls == accepts  # no automatic publisher restart
            assert service.export_snapshot().snapshot.objects[0].metrics[0].value == 25.0
        finally:
            stop.set()
            await asyncio.wait_for(task, 1.2)
        assert sources[0].closed and not lease.held
    asyncio.run(scenario())


def test_large_service_snapshot_keeps_all_history_and_sampling_after_delivery(tmp_path):
    config_path = tmp_path / "config.yaml"
    models_yaml = "\n".join(
        f"  - {{id: chat-{i}, type: chat, name: 'Chat {i}', base_url: 'http://offline.invalid:8000'}}"
        for i in range(256)
    )
    config_path.write_text(f"mount_points: []\nsample_interval: 1\nmodels:\n{models_yaml}\n", encoding="utf-8")
    sources = []
    template_metrics = large_envelope().snapshot.objects[0].metrics
    def factory(config):
        source, log, updates = SampleSource(), MemoryLog(), asyncio.Event()
        specs = tuple(ObjectSpec(ObjectKey("vllm", model.id), tuple(
            Metric(metric.name, None, metric.unit, metric.applicable) for metric in template_metrics
        )) for model in config.models)
        state = MonitorState((source.spec, *specs))
        first = time.monotonic() - 60
        for spec in specs:
            for second in range(61):
                state.accept(MetricCollectionResult(spec.key, template_metrics), sampled_at=first + second)
        monitor = Monitor((source,), state, log, interval=config.sample_interval, on_update=updates.set)
        sources.append(source)
        return CollectorRuntime(config, components=CollectorComponents(state, monitor, log, updates))

    async def scenario():
        listener, reader = MemoryListener(), MemoryPeer()
        await listener.peers.put(reader)
        service = CollectorService(config_path, runtime_factory=factory, listener=listener,
                                   lease=MemoryLease(), host_factory=lambda: ("Host", "Ubuntu 24.04"))
        stop = asyncio.Event()
        task = asyncio.create_task(service.run(stop))
        try:
            await until(lambda: bool(reader.frames), task, timeout=3.0)
            assert len(reader.frames[0]) - 8 > 8 * 1024 * 1024
            snapshot = decode_envelope(reader.frames[0])
            assert len(snapshot.metadata.models) == 256
            assert len([obj for obj in snapshot.snapshot.objects if obj.key.collector == "vllm"]) == 256
            assert all(obj.history for obj in snapshot.snapshot.objects if obj.key.collector == "vllm")
            previous = sources[0].calls
            await until(lambda: sources[0].calls > previous, task, timeout=2.5)
            assert not task.done() and not reader.closed
        finally:
            stop.set()
            await asyncio.wait_for(task, 1.2)
    asyncio.run(scenario())


def test_new_reader_waits_for_normal_publication_when_cached_frame_is_expired():
    async def scenario():
        publication_time = [100.0]
        feed = StateFeed(clock=lambda: publication_time[0])
        listener, reader = MemoryListener(), MemoryPeer()
        await listener.peers.put(reader)
        publisher = SnapshotPublisher(feed.envelope, listener, wait_updated=feed.wait_updated,
                                      clock=lambda: 106.0)
        stop = asyncio.Event()
        task = asyncio.create_task(publisher.run(stop))
        try:
            await until(lambda: feed.publications == 1 and listener.accept_calls >= 2, task)
            await asyncio.sleep(0)
            assert reader.frames == [] and not reader.closed
            assert feed.publications == 1
            publication_time[0] = 106.0
            feed.accept(stale=True)
            await until(lambda: bool(reader.frames), task, timeout=0.5)
            first = decode_envelope(reader.frames[0])
            assert first.published_at == 106.0 and first.sequence == 2
            assert first.snapshot.objects[0].stale
            assert feed.publications == 2 and not reader.closed
        finally:
            stop.set()
            await asyncio.wait_for(task, 1.2)
    asyncio.run(scenario())


def test_error_log_thread_start_failure_does_not_stop_collection_and_can_retry(monkeypatch, tmp_path):
    from dataclasses import replace
    from joi_observer.error_log import ErrorLog

    path = tmp_path / "config.yaml"
    path.write_text("mount_points: []\nsample_interval: 1\n", encoding="utf-8")
    thread_unavailable = [True]
    real_start = threading.Thread.start

    def start(thread):
        if thread.name == "joi-observer-error-log" and thread_unavailable[0]:
            raise RuntimeError("can't start new thread")
        return real_start(thread)

    monkeypatch.setattr(threading.Thread, "start", start)

    class LogIO:
        def __init__(self):
            self.lines = []

        def prepare(self, directory):
            pass

        def append(self, config, line):
            self.lines.append(line)

    async def scenario():
        io = LogIO()
        sources, logs = [], []

        def runtime_factory(config):
            log = ErrorLog(config.logging, io=io)
            runtime, source, _ = runtime_fixture(replace(config, sample_interval=0.02), log=log)

            async def collect():
                source.calls += 1
                return MetricCollectionResult(source.spec.key, failure=Failure(
                    ErrorKind.UNAVAILABLE, "source.unavailable", "Data source is unavailable."))

            source.collect = collect
            sources.append(source)
            logs.append(log)
            return runtime

        listener, peer, lease = MemoryListener(), MemoryPeer(), MemoryLease()
        await listener.peers.put(peer)
        service = CollectorService(path, runtime_factory=runtime_factory,
                                   listener=listener, lease=lease,
                                   host_factory=lambda: ("Host", "Ubuntu 24.04"))
        stop = asyncio.Event()
        running = asyncio.create_task(service.run(stop))
        try:
            await until(lambda: bool(sources) and sources[0].calls >= 3, running)
            assert lease.held and not running.done()
            assert service.export_snapshot().snapshot.objects[0].stale
            thread_unavailable[0] = False
            await until(lambda: bool(io.lines), running)
            assert not running.done() and sources[0].calls >= 4
            assert await logs[0].flush(timeout=0.5)
        finally:
            stop.set()
            await asyncio.gather(running, return_exceptions=True)
            await service.close()
        assert sources[0].closed and not lease.held
    asyncio.run(scenario())


def test_service_propagates_monitor_internal_error_after_all_resources_close(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("mount_points: []\nsample_interval: 1\n", encoding="utf-8")

    async def scenario():
        runtime, source, log = runtime_fixture()

        async def invalid_result():
            source.calls += 1
            return MetricCollectionResult(source.spec.key, (Metric("undeclared", 1),))

        source.collect = invalid_result
        listener, lease = MemoryListener(), MemoryLease()
        service = CollectorService(path, runtime_factory=lambda config: runtime,
                                   listener=listener, lease=lease,
                                   host_factory=lambda: ("Host", "Ubuntu 24.04"))
        try:
            with pytest.raises(ValueError, match="fields do not match"):
                await asyncio.wait_for(service.run(asyncio.Event()), 1.5)
        finally:
            await service.close()
        assert source.calls == 1 and source.closed and log.closed
        assert listener.closed and not lease.held
    asyncio.run(scenario())


def test_dynamic_gpu_discovery_recovery_and_slow_reader_keep_one_sampling_runtime(tmp_path):
    from joi_observer.collectors.hardware import CommandOutput, GpuCollector, GpuDiscovery
    from test_hardware import DISCOVERY_QUERY, UUIDS, gpu_row

    path = tmp_path / "config.yaml"
    path.write_text("mount_points: []\nsample_interval: 1\n", encoding="utf-8")

    async def scenario():
        phase = [0]
        ports = []
        created = []

        class HardwareIO:
            def __init__(self, uuid=None):
                self.uuid = uuid
                self.calls = 0
                self.closed = False
                ports.append(self)

            async def run(self, argv):
                self.calls += 1
                await asyncio.sleep(0)
                if self.uuid is None:
                    assert argv == DISCOVERY_QUERY
                    if phase[0] == 2:
                        raise OSError("offline inventory failure")
                    order = (0,) if phase[0] == 0 else (1,) if phase[0] == 1 else (1, 0)
                    return CommandOutput(0, "".join(f"{index}, {UUIDS[index]}\n" for index in order))
                assert argv[-1] == f"--id={self.uuid}"
                if phase[0] == 1 and self.uuid == UUIDS[0]:
                    return CommandOutput(1, "")
                index = UUIDS.index(self.uuid)
                return CommandOutput(0, gpu_row(index=index, uuid=self.uuid, temperature="N/A"))

            async def close(self):
                self.closed = True

        discovery = GpuDiscovery(HardwareIO())

        def child(spec):
            created.append(spec.key.object_id)
            return GpuCollector(spec.key.object_id, HardwareIO(spec.key.object_id))

        discovery.create_collector = child
        runtime, cpu, log = runtime_fixture(AppConfig(sample_interval=0.02, mount_points=()))
        runtime.components.monitor.register_discovery(discovery)
        listener, slow, healthy, lease = MemoryListener(), MemoryPeer(stalled=True), MemoryPeer(), MemoryLease()
        await listener.peers.put(slow)
        await listener.peers.put(healthy)
        service = CollectorService(path, runtime_factory=lambda config: runtime,
                                   listener=listener, lease=lease,
                                   host_factory=lambda: ("Host", "Ubuntu 24.04"))
        stop = asyncio.Event()
        running = asyncio.create_task(service.run(stop))

        def current():
            return {item.key: item for item in decode_envelope(healthy.frames[-1]).snapshot.objects} if healthy.frames else {}

        inventory = ObjectKey("gpu_inventory", "local")
        first, second = (ObjectKey("gpu", uuid) for uuid in UUIDS[:2])
        try:
            await until(lambda: first in current() and current()[first].sampled_at is not None, running)
            initial = current()[first]
            assert not initial.stale
            assert {metric.name: metric.value for metric in initial.metrics}["temperature_c"] is None
            phase[0] = 1
            await until(lambda: second in current() and current()[first].stale
                        and current()[second].sampled_at is not None, running)
            removed = current()[first]
            assert removed.history[-1].metrics is None
            phase[0] = 2
            await until(lambda: inventory in current() and current()[inventory].stale
                        and not current()[first].stale, running)
            recovered = current()[first]
            assert any(point.metrics is None for point in recovered.history)
            assert recovered.history[-1].metrics is not None
            phase[0] = 3
            await until(lambda: not current()[inventory].stale
                        and current()[inventory].metrics[0].value == 2, running)
            assert [key.object_id for key in current() if key.collector == "gpu"] == list(UUIDS[:2])
            assert created == list(UUIDS[:2])
            await until(lambda: slow.closed, running, timeout=2.5)
            previous = cpu.calls
            await until(lambda: cpu.calls > previous, running)
            assert lease.held and not running.done() and not healthy.closed
            assert all(port.calls > 1 for port in ports)
        finally:
            stop.set()
            await asyncio.gather(running, return_exceptions=True)
            await service.close()
        assert cpu.closed and log.closed and healthy.closed and all(port.closed for port in ports)
        assert not lease.held
    asyncio.run(scenario())


@pytest.mark.parametrize("field", ["PRETTY_NAME", "NAME"])
@pytest.mark.parametrize("separator", [" ", "\t", "\u202e"], ids=["printable", "tab", "bidi"])
def test_service_preserves_safe_header_presentation_from_local_release(
        tmp_path, monkeypatch, field, separator):
    """A host presentation label must not turn into a fatal collection startup error."""
    from datetime import datetime, timezone

    from joi_observer._host import local_host_info
    from joi_observer.tui.layout import TerminalSize, compose_frame

    release_path = tmp_path / "os-release"
    label = "Ubuntu" + separator + "24.04"
    # NAME has the same fallback behavior when PRETTY_NAME is not supplied.
    release_path.write_text(f'{field}="{label}"\n', encoding="utf-8")
    monkeypatch.setattr("joi_observer._host._OS_RELEASE_PATHS", (release_path,))
    expected_system = "Ubuntu 24.04" + (" —" if field == "NAME" else "")
    config = AppConfig(sample_interval=0.02, mount_points=())

    # The unchanged pure-view path independently demonstrates the established
    # sanitization behavior before the service's new metadata boundary.
    frame = compose_frame(StateSnapshot(()), config, TerminalSize(120, 48),
                          local_host_info(), datetime(2026, 11, 17, tzinfo=timezone.utc))
    assert any(cell.text == " / " + expected_system for cell in frame.cells)
    assert all("\t" not in cell.text and "\u202e" not in cell.text for cell in frame.cells)

    async def scenario():
        path = tmp_path / "config.yaml"
        path.write_text("mount_points: []\nsample_interval: 1\n", encoding="utf-8")
        runtime, source, log = runtime_fixture(config)
        listener, peer, lease = MemoryListener(), MemoryPeer(), MemoryLease()
        await listener.peers.put(peer)
        service = CollectorService(path, runtime_factory=lambda _: runtime,
                                   listener=listener, lease=lease)
        stop = asyncio.Event()
        running = asyncio.create_task(service.run(stop))
        try:
            await until(lambda: source.calls >= 2 and bool(peer.frames), running)
            envelope = decode_envelope(peer.frames[-1])
            assert envelope.metadata.system == expected_system
            assert lease.held and not running.done()
        finally:
            stop.set()
            await asyncio.gather(running, return_exceptions=True)
            await service.close()
        assert source.closed and log.closed and listener.closed and not lease.held

    asyncio.run(scenario())
