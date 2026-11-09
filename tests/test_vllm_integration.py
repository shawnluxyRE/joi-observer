"""Raw response ports through the actual collector, Monitor and state; no server."""

import asyncio
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from joi_observer.cli import ApplicationRuntime
from joi_observer.collectors.vllm import HttpResponse, VllmCollector
from joi_observer.config import AppConfig, LogConfig, ModelConfig, ModelType
from joi_observer.data.models import Metric, ObjectKey, ObjectSpec
from joi_observer.data.state import MonitorState
from joi_observer.error_log import ErrorLog
from joi_observer.monitor import Monitor


FIXTURES = Path(__file__).parent / "fixtures" / "vllm" / "0.31.0"
NAMES = {ModelType.CHAT: "qwen3.8-flash-next", ModelType.EMBEDDING: "qwen3-embedding-4b",
         ModelType.RERANKER: "qwen3-reranker-0.6b"}


def configs():
    return tuple(ModelConfig(kind.value, kind, NAMES[kind], f"http://127.0.0.1:{8000+i}")
                 for i, kind in enumerate(ModelType))


class RawHttp:
    """Only HTTP bytes/status and waiting are substituted, never derived metrics."""
    def __init__(self, cfg, *, blocked=False):
        self.cfg = cfg
        self.calls = []
        self.closed = False
        self.blocked = blocked
        self.metrics_override = None
        # The IO substitute delivers already-received bytes. Reading /mnt/d
        # fixtures inside a 10ms request budget measures host filesystem jitter.
        self.responses = {suffix: (FIXTURES / f"{cfg.type.value}-{suffix}").read_bytes()
                          for suffix in ("version.json", "models.json", "metrics-1.prom")}

    async def get(self, url, *, timeout, max_bytes):
        self.calls.append(url)
        if self.blocked:
            await asyncio.Future()
        await asyncio.sleep(0)
        suffix = {"/version": "version.json", "/v1/models": "models.json",
                  "/metrics": "metrics-1.prom"}[url.removeprefix(self.cfg.base_url)]
        if suffix == "metrics-1.prom" and self.metrics_override is not None:
            return HttpResponse(200, self.metrics_override)
        return HttpResponse(200, self.responses[suffix])

    async def close(self):
        self.closed = True


async def settle(monitor, *, rounds=80):
    for _ in range(rounds):
        await monitor.poll()
        await asyncio.sleep(0)


def test_three_models_are_sampled_independently_without_selection(tmp_path):
    async def scenario():
        cfgs = configs()
        ports = tuple(RawHttp(cfg) for cfg in cfgs)
        collectors = tuple(VllmCollector(cfg, http=port) for cfg, port in zip(cfgs, ports))
        clock = [0.0]
        state = MonitorState(tuple(c.spec for c in collectors), clock=lambda: clock[0])
        log = ErrorLog(LogConfig(directory=tmp_path / "logs"))
        assert log.prepare()
        monitor = Monitor(collectors, state, log, clock=lambda: clock[0])
        try:
            await settle(monitor)
            assert all(not item.stale and item.sampled_at == 0 for item in state.snapshot().objects)
            clock[0] = 2
            await settle(monitor)
            for item, cfg in zip(state.snapshot().objects, cfgs):
                metrics = {m.name: m for m in item.metrics}
                rate = "decode_rate" if cfg.type is ModelType.CHAT else "rate"
                assert metrics[rate].value == 0
                assert metrics["queue_seconds"].value is None
                assert not item.stale and len(item.history) == 2
            for cfg, port in zip(cfgs, ports):
                assert port.calls == [cfg.base_url + suffix for _ in range(2)
                                      for suffix in ("/version", "/v1/models", "/metrics")]
        finally:
            await monitor.stop()
            await log.close()
        assert all(port.closed for port in ports)
    asyncio.run(scenario())


def test_one_timeout_logs_stale_while_other_models_refresh_and_recovery_resumes(tmp_path):
    async def scenario():
        cfgs = configs()
        ports = tuple(RawHttp(cfg, blocked=(i == 1)) for i, cfg in enumerate(cfgs))
        collectors = tuple(VllmCollector(cfg, http=port, timeout=0.01)
                           for cfg, port in zip(cfgs, ports))
        state = MonitorState(tuple(c.spec for c in collectors))
        log = ErrorLog(LogConfig(directory=tmp_path / "logs"))
        assert log.prepare()
        monitor = Monitor(collectors, state, log, interval=0.05, timeout=0.02)
        try:
            await settle(monitor)
            await asyncio.sleep(0.03)
            await settle(monitor)
            first = state.snapshot()
            assert [s.stale for s in first.objects] == [False, True, False]
            assert first.objects[1].history[-1].metrics is None
            assert await log.flush()
            recorded = (tmp_path / "logs/error.log").read_text()
            assert "embedding" in recorded and "ERROR" in recorded
            assert "body.prom" not in recorded and "qwen3" not in recorded
            ports[1].blocked = False
            await asyncio.sleep(0.06)
            await settle(monitor)
            assert all(not s.stale for s in state.snapshot().objects)
        finally:
            await monitor.stop()
            await log.close()
    asyncio.run(scenario())


def test_valid_large_counter_cannot_stop_other_models_or_monitor(tmp_path):
    async def scenario():
        cfgs = configs()
        ports = tuple(RawHttp(cfg) for cfg in cfgs)
        collectors = tuple(VllmCollector(cfg, http=p) for cfg, p in zip(cfgs, ports))
        clock = [0.0]
        state = MonitorState(tuple(c.spec for c in collectors), clock=lambda: clock[0])
        log = ErrorLog(LogConfig(directory=tmp_path / "logs"))
        assert log.prepare()
        monitor = Monitor(collectors, state, log, clock=lambda: clock[0])
        try:
            await settle(monitor)
            raw = (FIXTURES / "chat-metrics-1.prom").read_bytes()
            ports[0].metrics_override, changed = re.subn(
                rb'(^vllm:generation_tokens_total\{[^\n]+\} )[^\s]+',
                rb'\g<1>1e399', raw, flags=re.MULTILINE)
            assert changed == 1
            clock[0] = 2
            await settle(monitor)
            items = state.snapshot().objects
            assert all(not item.stale and item.sampled_at == 2 for item in items)
            assert {m.name: m.value for m in items[0].metrics}["decode_rate"] is None
            assert all({m.name: m.value for m in item.metrics}["rate"] == 0 for item in items[1:])
        finally:
            await monitor.stop()
            await log.close()
    asyncio.run(scenario())


def test_runtime_assembles_all_model_ports_without_network_during_prepare(tmp_path, monkeypatch):
    class IdleDiscovery:
        spec = ObjectSpec(ObjectKey("gpu_inventory", "local"), (Metric("device_count", None),))

        async def discover(self):
            await asyncio.Future()

        async def close(self):
            pass

    monkeypatch.setattr("joi_observer.cli.build_hardware_sources",
                        lambda cfg: SimpleNamespace(collectors=(), discovery=IdleDiscovery()))
    cfgs = configs()
    created = []

    def factory():
        port = RawHttp(cfgs[len(created)])
        created.append(port)
        return port

    async def scenario():
        runtime = ApplicationRuntime(AppConfig(models=cfgs, mount_points=(),
                                      logging=LogConfig(directory=tmp_path / "logs")),
                                      vllm_http_factory=factory)
        try:
            assert created == []
            assert runtime.prepare_log()
            assert len(created) == 3 and all(not p.calls for p in created)
            await settle(runtime.components.monitor)
            assert all(p.calls for p in created)
        finally:
            await runtime.close()
        assert all(p.closed for p in created)
    asyncio.run(scenario())
