"""Raw offline samples across the complete snapshot/client/UI boundary.

Only hardware/process/HTTP bytes, log files, transport and terminal are external
substitutes. Collectors, Monitor, State, metadata projection, codec, client and
ObserverApp remain real. Existing sample/format expectations are reused rather
than reconstructing derived metrics in a transport stub.
"""

import asyncio
from datetime import datetime, timezone

import pytest

from joi_observer.collectors.hardware import (
    CommandOutput, CpuCollector, FileSystemStat, GpuCollector, MemoryCollector,
    StorageCollector,
)
from joi_observer.collectors.docker import DockerCollector
from joi_observer.collectors.vllm import HttpResponse, VllmCollector
from joi_observer.config import AppConfig, ContainerConfig, LogConfig, ModelConfig, ModelType
from joi_observer.data.models import ObjectKey
from joi_observer.data.state import MonitorState
from joi_observer.error_log import ErrorLog
from joi_observer.ipc.client import SnapshotClient
from joi_observer.ipc.protocol import IO_CHUNK_BYTES, SnapshotEnvelope, build_metadata, encode_envelope
from joi_observer.monitor import Monitor
from joi_observer.tui.app import ObserverApp
from joi_observer.tui.layout import HostInfo, TerminalSize, ViewSelection
from joi_observer.tui.navigation import SessionViewActions
from joi_observer.tui.widgets import linked_gpu_ids

from test_docker_integration import RawCommand
from test_hardware import ROOT, UUIDS, RawIO, gpu_row
from test_hardware_runtime import region_text
from test_vllm_full_response_integration import CompleteResponsePort, IDENTITIES, MemoryLogIO


WALL_NOW = datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)


class RecoveringResponsePort(CompleteResponsePort):
    """Deliver complete captured bodies or one explicit HTTP-status failure."""

    failed = False

    async def get(self, url, *, timeout, max_bytes):
        if self.failed and url.endswith("/metrics"):
            self.calls.append((url, timeout, max_bytes))
            await asyncio.sleep(0)
            return HttpResponse(503, b"")
        return await super().get(url, timeout=timeout, max_bytes=max_bytes)


class PipelineStream:
    """Ordered byte transport with deliberately fragmented delivery, no socket."""

    def __init__(self):
        self.pending = asyncio.Queue()
        self.buffer = b""
        self.reads = []
        self.closed = False

    def deliver(self, frame):
        # Splits do not align to either the 8-byte header or JSON boundaries.
        for offset in range(0, len(frame), 997):
            self.pending.put_nowait(frame[offset:offset + 997])

    async def readexactly(self, count):
        assert 0 < count <= IO_CHUNK_BYTES
        self.reads.append(count)
        while len(self.buffer) < count:
            self.buffer += await self.pending.get()
        value, self.buffer = self.buffer[:count], self.buffer[count:]
        return value

    async def close(self):
        self.closed = True


class PipelineConnector:
    def __init__(self, stream):
        self.stream = stream
        self.calls = 0

    async def connect(self, endpoint):
        self.calls += 1
        return self.stream


class OneFrameTerminal:
    """Record the actual frame and leave through ObserverApp's real q path."""

    def __init__(self):
        self.frames = []
        self.events = []

    def enter(self):
        self.events.append("enter")

    def restore(self):
        self.events.append("restore")

    def size(self):
        return TerminalSize(140, 48)

    def render(self, frame):
        self.frames.append(frame)

    async def read_key(self, timeout):
        await asyncio.sleep(0)
        return "q"


def values(item):
    return {metric.name: metric.value for metric in item.metrics}


def pipeline_config(tmp_path):
    models = tuple(
        ModelConfig(kind.value, kind, f"{kind.value} alias",
                    f"http://{kind.value}.invalid:{8000 + index}", (UUIDS[0],), identity)
        for index, (kind, identity) in enumerate(IDENTITIES.items())
    )
    return AppConfig(
        sample_interval=1.0, mount_points=("/",), models=models,
        containers=(ContainerConfig("public-container", "private-container-target"),),
        logging=LogConfig(directory=tmp_path / "unused-log-path"),
    )


async def collect_reference_rounds(config, failed_kind):
    """Use the same raw counts and complete response captures as old regressions."""
    hardware_io = RawIO(
        texts={
            "/proc/stat": [f"cpu {100 * (i + 1)} 0 0 {100 * (i + 1)} 0 0 0 0\n"
                           for i in range(4)],
            "/proc/meminfo": ["MemTotal: 16777216 kB\nMemAvailable: 12582912 kB\n"] * 4,
            "/proc/self/mountinfo": [ROOT] * 8,
        },
        stats=[FileSystemStat(4096, 26214400, 19660800)] * 4,
        outputs=[CommandOutput(0, gpu_row(index=0, utilization="50", used="4096",
                                        total="24576", temperature="61", power="123.5"))] * 4,
    )
    command = RawCommand(status="exited")
    ports = tuple(RecoveringResponsePort(model) for model in config.models)
    collectors = (
        CpuCollector(hardware_io), MemoryCollector(hardware_io),
        StorageCollector(0, "/", hardware_io), GpuCollector(UUIDS[0], hardware_io),
        DockerCollector(config.containers[0], command=command),
        *(VllmCollector(model, port) for model, port in zip(config.models, ports)),
    )
    # Match the real local monotonic domain used by ObserverApp without waiting
    # through four wall-clock sampling intervals. Each round still advances 1s.
    base = asyncio.get_running_loop().time() - 10.0
    clock = [base]
    state = MonitorState(tuple(collector.spec for collector in collectors), clock=lambda: clock[0])
    log_io = MemoryLogIO()
    log = ErrorLog(config.logging, io=log_io)
    assert log.prepare()
    monitor = Monitor(collectors, state, log, interval=1.0, clock=lambda: clock[0])
    snapshots = []
    try:
        for round_index in range(4):
            clock[0] = base + round_index
            for model, port in zip(config.models, ports):
                port.failed = round_index == 2 and model.type is failed_kind
            for _ in range(150):
                await monitor.poll()
                await asyncio.sleep(0)
                snapshot = state.snapshot()
                if all(item.sampled_at == clock[0] for item in snapshot.objects):
                    snapshots.append(snapshot)
                    break
            else:
                raise AssertionError("Raw sources did not finish the deterministic sample round")
        assert await log.flush()
        assert len(log_io.lines) == 1 and b"ERROR" in log_io.lines[0]
    finally:
        await monitor.stop()
        await log.close()
    assert hardware_io.closed and command.closed
    assert all(port.close_calls == 1 for port in ports)
    return snapshots


def assert_reference_values(snapshots, failed_kind):
    for round_index, snapshot in enumerate(snapshots):
        items = {item.key: item for item in snapshot.objects}
        cpu = items[ObjectKey("host", "cpu")]
        assert values(cpu)["cpu_percent"] == (None if round_index == 0 else 50.0)
        assert values(items[ObjectKey("host", "ram")]) == {
            "ram_used_bytes": 4 * 2**30, "ram_total_bytes": 16 * 2**30, "ram_percent": 25.0,
        }
        assert values(items[ObjectKey("storage", "mount-0")]) == {
            "used_bytes": 25 * 2**30, "total_bytes": 100 * 2**30, "used_percent": 25.0,
        }
        assert values(items[ObjectKey("docker", "public-container")]) == {"state": "Exited"}
        gpu = items[ObjectKey("gpu", UUIDS[0])]
        assert values(gpu)["memory_used_bytes"] == 4 * 2**30
        assert values(gpu)["memory_total_bytes"] == 24 * 2**30
        assert values(gpu)["utilization_percent"] == 50
        for kind in ModelType:
            item = items[ObjectKey("vllm", kind.value)]
            data = values(item)
            assert (data["running"], data["waiting"], data["total"]) == (0, 0, 0)
            assert data["queue_seconds"] is None
            assert item.stale is (round_index == 2 and kind is failed_kind)
            assert (item.history[-1].metrics is None) is item.stale
            metrics = {metric.name: metric for metric in item.metrics}
            primary = "decode_rate" if kind is ModelType.CHAT else "rate"
            if round_index == 0:
                assert data[primary] is None
            elif round_index == 1:
                assert data[primary] == 0
            assert metrics[primary].unit == ("tok/s" if kind is ModelType.CHAT else "seq/s")
            if kind is not ModelType.CHAT:
                assert metrics["kv_cache_percent"].value is None
                assert not metrics["kv_cache_percent"].applicable


@pytest.mark.parametrize("selected_kind", tuple(ModelType))
def test_raw_sources_through_snapshot_transport_keep_original_values_and_frame_contracts(tmp_path, selected_kind):
    async def scenario():
        config = pipeline_config(tmp_path)
        snapshots = await collect_reference_rounds(config, selected_kind)
        assert_reference_values(snapshots, selected_kind)
        metadata = build_metadata(config, hostname="Offline Host", system="Ubuntu 24.04")
        stream = PipelineStream()
        connector = PipelineConnector(stream)
        client = SnapshotClient(connector=connector)
        try:
            for sequence, reference in enumerate(snapshots, start=1):
                published_at = max(item.sampled_at for item in reference.objects)
                envelope = SnapshotEnvelope("pipeline-instance", "pipeline-config", sequence,
                                            published_at, metadata, reference)
                stream.deliver(encode_envelope(envelope))
                if sequence == 1:
                    await client.connect()
                else:
                    async def receive_sequence():
                        while client.envelope().sequence != sequence:
                            await asyncio.sleep(0)
                    await asyncio.wait_for(receive_sequence(), 0.5)
                assert client.snapshot() == reference
                assert client.envelope().metadata == metadata
                view = ViewSelection(selected_kind.value)
                assert linked_gpu_ids(client.snapshot(), metadata, view) == (UUIDS[0],)
                terminal = OneFrameTerminal()
                actions = SessionViewActions(metadata.models)
                for _ in range(tuple(ModelType).index(selected_kind)):
                    actions.on_key("down")
                app = ObserverApp(metadata, client, terminal,
                                  host=HostInfo(metadata.hostname, metadata.system),
                                  wall_clock=lambda: WALL_NOW, actions=actions)
                await asyncio.wait_for(app.run(), 0.5)
                assert terminal.events == ["enter", "restore"]
                assert len(terminal.frames) == 1 and not terminal.frames[0].too_small
                frame = terminal.frames[0]
                gpu_text = region_text(frame, "gpu")
                assert "Offline GPU 0" in gpu_text and "4.0 / 24.0 GiB" in gpu_text
                assert "4 / 16 GiB" in region_text(frame, "host")
                assert "25 / 100 GiB" in region_text(frame, "storage")
                docker_text = region_text(frame, "docker")
                assert "public-container" in docker_text and "Exited" in docker_text
                assert "private-container-target" not in docker_text
                service_text = region_text(frame, "service")
                assert IDENTITIES[selected_kind] in service_text
                assert "RUNNING" in service_text and "WAITING" in service_text
                assert "Total 0 seq" in service_text
                if selected_kind is not ModelType.CHAT:
                    assert "N/A" in service_text and "seq/s" in service_text
                selected = next(item for item in reference.objects
                                if item.key == ObjectKey("vllm", selected_kind.value))
                if selected.stale:
                    assert "STALE" in service_text and selected.history[-1].metrics is None
            assert connector.calls == 1
            assert max(stream.reads) <= IO_CHUNK_BYTES
            assert all(point.metrics is not None for point in snapshots[1].objects[-1].history)
        finally:
            await client.close()
        assert stream.closed
    asyncio.run(scenario())


def test_dynamic_gpu_discovery_partial_failure_and_recovery_share_one_snapshot_connection(tmp_path, monkeypatch):
    """Real discovery additions and partial GPU values remain valid wire data."""
    from joi_observer.collectors.hardware import GpuDiscovery
    from joi_observer.ipc.client import ConnectionState

    async def scenario():
        model = ModelConfig("chat", ModelType.CHAT, "Local chat", "http://chat.invalid:8000",
                            ("0", UUIDS[1]), IDENTITIES[ModelType.CHAT])
        config = AppConfig(sample_interval=1.0, mount_points=(), models=(model,),
                           logging=LogConfig(directory=tmp_path / "unused-log-path"))
        first, second = UUIDS[:2]
        inventory_io = RawIO(outputs=(
            CommandOutput(0, f"0, {first}\n"),
            *(CommandOutput(0, f"1, {second}\n0, {first}\n") for _ in range(3)),
        ))
        first_io = RawIO(outputs=tuple(CommandOutput(0, gpu_row(
            index=0, power=power, utilization=utilization))
            for power, utilization in (("123.5", "50"), ("125.5", "60"),
                                       ("PRIVATE-invalid", "75"), ("127.5", "80"))))
        second_io = RawIO(outputs=tuple(CommandOutput(0, gpu_row(index=1, used="2048"))
                                       for _ in range(3)))
        ports = iter((first_io, second_io))
        monkeypatch.setattr("joi_observer.collectors.hardware.LocalHardwareIO",
                            lambda **options: next(ports))
        discovery = GpuDiscovery(inventory_io)
        http = CompleteResponsePort(model)
        collector = VllmCollector(model, http)
        clock = [asyncio.get_running_loop().time() - 10.0]
        base = clock[0]
        state = MonitorState((collector.spec,), clock=lambda: clock[0])
        log_io = MemoryLogIO()
        log = ErrorLog(config.logging, io=log_io)
        assert log.prepare()
        monitor = Monitor((collector,), state, log, interval=1.0, clock=lambda: clock[0])
        monitor.register_discovery(discovery)
        metadata = build_metadata(config, hostname="Offline Host", system="Ubuntu 24.04")
        stream, sequence = PipelineStream(), [1]
        connector = PipelineConnector(stream)
        client = SnapshotClient(connector=connector)

        async def publish():
            original = SnapshotEnvelope("discovery-instance", "discovery-config", sequence[0],
                                        clock[0], metadata, state.snapshot())
            stream.deliver(encode_envelope(original))
            if sequence[0] == 1:
                await client.connect()
            else:
                async def installed():
                    while client.envelope().sequence != sequence[0]:
                        await asyncio.sleep(0)
                await asyncio.wait_for(installed(), 0.5)
            assert client.envelope() == original
            sequence[0] += 1
            return client.envelope()

        def gpu_objects(envelope):
            return tuple(item for item in envelope.snapshot.objects if item.key.collector == "gpu")

        references = []
        try:
            initial = await publish()
            assert gpu_objects(initial) == () and len(initial.snapshot.objects) == 2
            for phase in range(4):
                clock[0] = base + phase
                for _ in range(100):
                    await monitor.poll()
                    await asyncio.sleep(0)
                    current = state.snapshot()
                    gpus = tuple(item for item in current.objects if item.key.collector == "gpu")
                    if (len(gpus) == (1 if phase == 0 else 2)
                            and all(item.sampled_at == clock[0] for item in current.objects)):
                        break
                else:
                    raise AssertionError("The real discovery/collection round did not settle")
                received = await publish()
                references.append(received)
                assert received.metadata == initial.metadata
                assert received.snapshot.revision > (initial if phase == 0 else references[-2]).snapshot.revision
                gpus = gpu_objects(received)
                assert tuple(item.key.object_id for item in gpus) == ((first,) if phase == 0 else (first, second))
                assert gpus[0].stale is (phase == 2)
                assert (gpus[0].history[-1].metrics is None) is (phase == 2)
                data = values(gpus[0])
                assert data["utilization_percent"] == (50, 60, 75, 80)[phase]
                assert data["power_w"] == (123.5, 125.5, 125.5, 127.5)[phase]
                expected_links = ((first,) if phase == 0 else
                                  (second,) if phase == 2 else (first, second))
                assert linked_gpu_ids(received.snapshot, received.metadata,
                                      ViewSelection("chat")) == expected_links
                calls_before_ui = (len(inventory_io.calls), len(first_io.calls),
                                   len(second_io.calls), len(http.calls))
                terminal = OneFrameTerminal()
                app = ObserverApp(received.metadata, client, terminal,
                                  host=HostInfo(metadata.hostname, metadata.system),
                                  wall_clock=lambda: WALL_NOW)
                await app.run()
                assert terminal.events == ["enter", "restore"] and terminal.frames
                assert (len(inventory_io.calls), len(first_io.calls),
                        len(second_io.calls), len(http.calls)) == calls_before_ui
                assert client.state is ConnectionState.CONNECTED
            assert gpu_objects(initial) == ()
            assert not gpu_objects(references[1])[0].stale
            assert values(gpu_objects(references[1])[0])["power_w"] == 125.5
            assert gpu_objects(references[2])[0].stale
            assert gpu_objects(references[2])[0].history[-1].metrics is None
            assert not gpu_objects(references[3])[0].stale
            assert connector.calls == 1
            assert await log.flush()
            assert len(log_io.lines) == 1 and b"response.invalid" in log_io.lines[0]
            assert b"PRIVATE" not in log_io.lines[0]
        finally:
            await client.close()
            await monitor.stop()
            await log.close()
        assert stream.closed and all(port.closed for port in (inventory_io, first_io, second_io))
        assert http.close_calls == 1

    asyncio.run(scenario())
