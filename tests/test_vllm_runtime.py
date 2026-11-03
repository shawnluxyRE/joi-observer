"""Production composition and raw bytes -> state -> frame recovery, without IO."""

import asyncio
from datetime import datetime, timezone
import re
from types import SimpleNamespace

import pytest

from joi_observer.cli import ApplicationRuntime, RuntimeComponents
from joi_observer.config import AppConfig, LogConfig, ModelType
from joi_observer.data.models import Metric, ObjectKey, ObjectSpec
from joi_observer.data.state import MonitorState
from joi_observer.error_log import ErrorLog
from joi_observer.monitor import Monitor
from joi_observer.collectors.vllm import VllmCollector
from joi_observer.tui.layout import HostInfo, TerminalSize, ViewSelection, compose_frame
from test_vllm_integration import FIXTURES, RawHttp, configs, settle


class PendingDiscovery:
    spec = ObjectSpec(ObjectKey("gpu_inventory", "local"), (Metric("device_count", None),))

    async def discover(self):
        await asyncio.Future()

    async def close(self):
        pass


def test_empty_models_do_not_construct_http_ports(tmp_path, monkeypatch):
    monkeypatch.setattr("joi_observer.cli.build_hardware_sources",
                        lambda cfg: SimpleNamespace(collectors=(), discovery=PendingDiscovery()))

    def forbidden():
        pytest.fail("Empty models must not construct an HTTP port")

    async def scenario():
        runtime = ApplicationRuntime(AppConfig(mount_points=(),
                                     logging=LogConfig(directory=tmp_path / "logs")),
                                     vllm_http_factory=forbidden)
        try:
            assert runtime.prepare_log()
        finally:
            await runtime.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", tuple(ModelType))
def test_wrong_reported_identity_stops_reads_breaks_baseline_and_recovers(tmp_path, kind):
    """A healthy endpoint serving another model must never contaminate this one."""
    async def scenario():
        models = configs()
        ports = tuple(RawHttp(model) for model in models)
        collectors = tuple(VllmCollector(model, port) for model, port in zip(models, ports))
        clock = [0.0]
        state = MonitorState(tuple(collector.spec for collector in collectors), clock=lambda: clock[0])
        log = ErrorLog(LogConfig(directory=tmp_path / "logs"))
        assert log.prepare()
        monitor = Monitor(collectors, state, log, clock=lambda: clock[0])
        index = tuple(ModelType).index(kind)
        port = ports[index]
        matching_identity = port.responses["models.json"]
        primary = "decode_rate" if kind is ModelType.CHAT else "rate"
        try:
            for tick in range(0, 14, 2):
                clock[0] = tick
                mismatched = tick in (4, 6, 12)
                port.responses["models.json"] = (
                    b'{"data":[{"id":"different-private-model"}]}'
                    if mismatched else matching_identity
                )
                for model, other in zip(models, ports):
                    other.metrics_override = sample_bytes(model.type, tick * 3)
                previous_calls = len(port.calls)
                await settle(monitor)
                snapshots = state.snapshot().objects
                selected = snapshots[index]
                expected_paths = ("/version", "/v1/models") if mismatched else (
                    "/version", "/v1/models", "/metrics")
                assert port.calls[previous_calls:] == [models[index].base_url + p for p in expected_paths]
                assert selected.stale is mismatched
                assert (selected.history[-1].metrics is None) is mismatched
                values = {metric.name: metric.value for metric in selected.metrics}
                assert values[primary] == (None if tick in (0, 8) else 3)
                assert values["total"] == 10
                for other_index, other in enumerate(snapshots):
                    assert other.sampled_at == tick
                    if other_index != index:
                        other_primary = "decode_rate" if models[other_index].type is ModelType.CHAT else "rate"
                        assert not other.stale
                        assert {m.name: m.value for m in other.metrics}[other_primary] == (None if tick == 0 else 3)
                assert "different-private-model" not in repr(snapshots)
            assert await log.flush()
            lines = (tmp_path / "logs/error.log").read_text().splitlines()
            assert len(lines) == 2  # repeated fault throttled; after recovery, log immediately
            assert all("object.not_found" in line for line in lines)
            assert all("different-private-model" not in line for line in lines)
        finally:
            await monitor.stop()
            await log.close()
        assert all(port.closed for port in ports)

    asyncio.run(scenario())


def test_injected_components_bypass_all_source_factories(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Complete components must not rebuild sources")

    for name in ("build_hardware_sources", "build_docker_collectors", "build_vllm_collectors"):
        monkeypatch.setattr("joi_observer.cli." + name, forbidden)

    async def scenario():
        config = AppConfig(models=configs(), logging=LogConfig(directory=tmp_path / "logs"))
        state = MonitorState()
        log = ErrorLog(config.logging)
        monitor = Monitor((), state, log)
        components = RuntimeComponents(monitor, SimpleNamespace(), log)
        runtime = ApplicationRuntime(config, components=components,
                                     docker_command_factory=forbidden, vllm_http_factory=forbidden)
        assert runtime.prepare_log()
        assert runtime.components is components
        await runtime.close()
        await runtime.close()

    asyncio.run(scenario())


def sample_bytes(kind, rate_counter, *, invalid_waiting=False):
    raw = (FIXTURES / f"{kind.value}-metrics-1.prom").read_bytes()
    changes = {"num_requests_running": "3", "num_requests_waiting": "NaN" if invalid_waiting else "7"}
    counter = "generation_tokens_total" if kind is ModelType.CHAT else "request_success_total"
    changes[counter] = str(rate_counter)
    for name, value in changes.items():
        labels = rb'[^\n]+' if name != "request_success_total" else rb'[^\n]*finished_reason="stop"[^\n]*'
        raw, changed = re.subn(rb'(^vllm:' + name.encode() + rb'\{' + labels + rb'\} )[^\s]+',
                               lambda match: match[1] + value.encode(), raw, flags=re.MULTILINE)
        assert changed == 1
    return raw


@pytest.mark.parametrize("kind", tuple(ModelType))
def test_raw_metrics_partial_failure_recovery_keeps_frame_slots_and_other_models(tmp_path, kind):
    async def scenario():
        models = configs()
        ports = tuple(RawHttp(model) for model in models)
        collectors = tuple(VllmCollector(model, port) for model, port in zip(models, ports))
        clock = [0.0]
        state = MonitorState(tuple(collector.spec for collector in collectors), clock=lambda: clock[0])
        log = ErrorLog(LogConfig(directory=tmp_path / "logs"))
        assert log.prepare()
        monitor = Monitor(collectors, state, log, clock=lambda: clock[0])
        index = tuple(ModelType).index(kind)
        primary = "decode_rate" if kind is ModelType.CHAT else "rate"
        frames = []
        try:
            for tick, counter, invalid in ((0, 0, False), (2, 6, False), (4, 12, True),
                                           (6, 18, False), (8, 24, False)):
                clock[0] = tick
                ports[index].metrics_override = sample_bytes(kind, counter, invalid_waiting=invalid)
                await settle(monitor)
                snapshot = state.snapshot()
                item = snapshot.objects[index]
                values = {metric.name: metric.value for metric in item.metrics}
                assert values[primary] == (None if tick == 0 else 3)
                assert values["total"] == 10
                assert item.stale is invalid
                assert (item.history[-1].metrics is None) is invalid
                assert all(other.sampled_at == tick and not other.stale
                           for i, other in enumerate(snapshot.objects) if i != index)
                frame = compose_frame(snapshot, AppConfig(models=models), TerminalSize(120, 40),
                                      HostInfo("offline", "Ubuntu"), datetime(2026, 11, 2, tzinfo=timezone.utc),
                                      view=ViewSelection(models[index].id), monotonic_now=tick)
                frames.append(frame)
                text = " ".join(cell.text for cell in frame.cells)
                assert ("STALE" in text) is invalid
                assert "response.invalid" not in text and "NaN" not in text
                status = "STALE" if invalid else "QUEUED"
                assert any(cell.text == status for cell in frame.cells)
                # A view change uses the same accumulated snapshots and retains every history.
                before = state.snapshot()
                compose_frame(before, AppConfig(models=models), TerminalSize(120, 40),
                              HostInfo("offline", "Ubuntu"), datetime(2026, 11, 2, tzinfo=timezone.utc),
                              view=ViewSelection(models[(index + 1) % 3].id), monotonic_now=tick)
                assert state.snapshot() == before
            assert all(frame.regions == frames[0].regions for frame in frames)
            assert await log.flush()
            lines = (tmp_path / "logs/error.log").read_text().splitlines()
            assert len(lines) == 1 and "response.invalid" in lines[0]
        finally:
            await monitor.stop()
            await log.close()
        assert all(port.closed for port in ports)

    asyncio.run(scenario())
