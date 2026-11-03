"""Complete captured responses through the real collector, Monitor and State.

Each complete first-capture body is replayed twice through an in-memory HTTP
port. These are simulated sampling rounds, not additional server observations.
No excerpt fixture or precomputed collector/state result is substituted.
"""

import asyncio
from pathlib import Path

from joi_observer.collectors.vllm import HttpResponse, MAX_RESPONSE_BYTES, VllmCollector
from joi_observer.config import LogConfig, ModelConfig, ModelType
from joi_observer.data.state import MonitorState
from joi_observer.error_log import ErrorLog
from joi_observer.monitor import Monitor


FIXTURES = Path(__file__).parent / "fixtures" / "vllm" / "0.31.0"
IDENTITIES = {
    ModelType.CHAT: "qwen3.8-flash-next",
    ModelType.EMBEDDING: "qwen3-embedding-4b",
    ModelType.RERANKER: "qwen3-reranker-0.6b",
}
PATHS = ("/version", "/v1/models", "/metrics")


class CompleteResponsePort:
    """Read fixture files once; get only delivers already-received bytes."""
    def __init__(self, config):
        kind = config.type.value
        self.responses = {
            config.base_url + "/version": (FIXTURES / f"{kind}-version.json").read_bytes(),
            config.base_url + "/v1/models": (FIXTURES / f"{kind}-models.json").read_bytes(),
            config.base_url + "/metrics": (FIXTURES / f"{kind}-metrics-full.prom").read_bytes(),
        }
        self.calls = []
        self.close_calls = 0

    async def get(self, url, *, timeout, max_bytes):
        self.calls.append((url, timeout, max_bytes))
        assert url in self.responses
        await asyncio.sleep(0)
        return HttpResponse(200, self.responses[url])

    async def close(self):
        self.close_calls += 1


class MemoryLogIO:
    """Only the log's file boundary is replaced; actual ErrorLog still runs."""
    def __init__(self):
        self.lines = []

    def prepare(self, directory):
        pass

    def append(self, config, line):
        self.lines.append(line)


def test_three_complete_profiles_sample_twice_without_stale_or_error_logs(tmp_path):
    async def case():
        configs = tuple(
            ModelConfig(kind.value, kind, identity, f"http://{kind.value}.invalid:{8000 + index}")
            for index, (kind, identity) in enumerate(IDENTITIES.items())
        )
        ports = tuple(CompleteResponsePort(config) for config in configs)
        collectors = tuple(VllmCollector(config, port) for config, port in zip(configs, ports))
        clock = [0.0]
        state = MonitorState(tuple(collector.spec for collector in collectors), clock=lambda: clock[0])
        log_io = MemoryLogIO()
        log = ErrorLog(LogConfig(directory=tmp_path / "unused-log-path"), io=log_io)
        assert log.prepare()
        monitor = Monitor(collectors, state, log, clock=lambda: clock[0])
        snapshots = []
        try:
            for sampled_at in (0.0, 2.0):
                clock[0] = sampled_at
                for _ in range(100):
                    await monitor.poll()
                    await asyncio.sleep(0)
                    snapshot = state.snapshot()
                    if all(item.sampled_at == sampled_at for item in snapshot.objects):
                        break
                else:
                    raise AssertionError("All configured profiles must finish their sampling round.")
                snapshots.append(snapshot)

            assert await log.flush()
            for round_index, snapshot in enumerate(snapshots):
                assert tuple(item.key.object_id for item in snapshot.objects) == tuple(
                    config.id for config in configs)
                for config, item in zip(configs, snapshot.objects):
                    assert not item.stale
                    assert item.sampled_at == (0.0, 2.0)[round_index]
                    assert len(item.history) == round_index + 1
                    assert all(point.metrics is not None for point in item.history)
                    assert tuple(point.sampled_at for point in item.history) == (0.0, 2.0)[:round_index + 1]
                    values = {metric.name: metric.value for metric in item.metrics}
                    primary = "decode_rate" if config.type is ModelType.CHAT else "rate"
                    assert values[primary] == (None if round_index == 0 else 0.0)
                    assert (values["running"], values["waiting"], values["total"]) == (0, 0, 0)
                    assert values["queue_seconds"] is None
                    latency = "ttft_seconds" if config.type is ModelType.CHAT else "latency_seconds"
                    assert values[latency] is None
                    history_values = {metric.name: metric.value for metric in item.history[-1].metrics}
                    assert history_values[primary] == values[primary]
            assert log_io.lines == []
            for config, port in zip(configs, ports):
                assert [url for url, _, _ in port.calls] == [
                    config.base_url + path for _ in range(2) for path in PATHS]
                assert all(0 < timeout <= 3.0 and limit == MAX_RESPONSE_BYTES
                           for _, timeout, limit in port.calls)
        finally:
            await monitor.stop()
            await log.close()
        assert all(port.close_calls == 1 for port in ports)

    asyncio.run(case())
