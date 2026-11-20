"""Collector ownership, update waits and partial assembly stay independent of UI."""

import asyncio
from types import SimpleNamespace

import pytest

from joi_observer.config import AppConfig, ContainerConfig, ModelConfig, ModelType
from joi_observer.runtime import CollectorRuntime
from test_service_contract import MemoryLog, runtime_fixture


@pytest.mark.parametrize("revision", [True, -1, 0.0, "0", None])
def test_wait_updated_rejects_nonrevision_values_without_sampling(revision):
    async def scenario():
        runtime, source, _ = runtime_fixture()
        with pytest.raises(ValueError):
            await runtime.wait_updated(revision)
        assert source.calls == 0
        await runtime.close()
    asyncio.run(scenario())


def test_close_cancels_update_waiters_without_new_samples():
    async def scenario():
        runtime, source, log = runtime_fixture()
        waiting = asyncio.create_task(runtime.wait_updated(runtime.snapshot().revision))
        await asyncio.sleep(0)
        assert not waiting.done()
        await runtime.close()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert source.calls == 0 and source.closed and log.closed
    asyncio.run(scenario())


def test_run_cancellation_preserves_cancel_and_closes_sources():
    async def scenario():
        runtime, source, log = runtime_fixture()
        task = asyncio.create_task(runtime.run(asyncio.Event()))
        while source.calls == 0:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert source.closed and log.closed
        with pytest.raises(RuntimeError):
            await runtime.run(asyncio.Event())
        await runtime.close()
    asyncio.run(scenario())


def test_concurrent_close_waits_for_same_cleanup():
    async def scenario():
        class SlowLog(MemoryLog):
            async def close(self, *, timeout=1.0):
                await asyncio.sleep(0.02)
                return await super().close(timeout=timeout)

        runtime, source, log = runtime_fixture(log=SlowLog())
        first = asyncio.create_task(runtime.close())
        await asyncio.sleep(0)
        await runtime.close()
        assert log.closed and source.closed
        await first
    asyncio.run(scenario())


def test_partial_source_factory_failure_closes_created_ports(tmp_path, monkeypatch):
    class UnusedSource:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    hardware_source, discovery, command = (UnusedSource() for _ in range(3))
    monkeypatch.setattr("joi_observer.runtime.build_hardware_sources",
                        lambda config: SimpleNamespace(collectors=(hardware_source,), discovery=discovery))
    calls = []

    def command_factory():
        calls.append(None)
        if len(calls) == 2:
            raise RuntimeError("factory failed")
        return command

    async def scenario():
        runtime = CollectorRuntime(AppConfig(containers=(ContainerConfig("a", "a"),
                                                        ContainerConfig("b", "b"))),
                                   docker_command_factory=command_factory)
        with pytest.raises(RuntimeError, match="factory failed"):
            runtime.prepare_log()
        await runtime.close()
        assert hardware_source.closed and discovery.closed and command.closed
        assert runtime.components is None
    asyncio.run(scenario())


def test_late_model_factory_failure_closes_adopted_docker_and_partial_http_ports(monkeypatch):
    class UnusedPort:
        def __init__(self):
            self.closes = 0

        async def close(self):
            self.closes += 1

    hardware, discovery, command, http = (UnusedPort() for _ in range(4))
    monkeypatch.setattr("joi_observer.runtime.build_hardware_sources",
                        lambda config: SimpleNamespace(collectors=(hardware,), discovery=discovery))
    calls = []

    def http_factory():
        calls.append(None)
        if len(calls) == 2:
            raise RuntimeError("late model factory failure")
        return http

    async def scenario():
        config = AppConfig(containers=(ContainerConfig("container", "actual-name"),),
                           models=(ModelConfig("first", ModelType.CHAT, "First", "http://offline.invalid:8000"),
                                   ModelConfig("second", ModelType.CHAT, "Second", "http://offline.invalid:8001")))
        runtime = CollectorRuntime(config, docker_command_factory=lambda: command,
                                   vllm_http_factory=http_factory)
        with pytest.raises(RuntimeError, match="late model factory failure"):
            runtime.prepare_log()
        assert runtime.components is None
        await runtime.close()
        await runtime.close()
        assert [port.closes for port in (hardware, discovery, command, http)] == [1, 1, 1, 1]
    asyncio.run(scenario())


@pytest.mark.parametrize("family", ["docker", "vllm"])
@pytest.mark.parametrize("truthy", [True, False], ids=["truthy", "falsey"])
def test_explicit_runtime_io_factory_is_used_regardless_of_its_truth_value(tmp_path, monkeypatch, family, truthy):
    """A provided Callable remains the IO boundary through real sampling."""
    from joi_observer.collectors.hardware import CommandOutput, GpuDiscovery
    from joi_observer.config import LogConfig
    from test_docker_integration import RawCommand
    from test_hardware import RawIO
    from test_service_contract import until
    from test_vllm_integration import RawHttp, configs

    async def scenario():
        model = configs()[0]
        config = AppConfig(mount_points=(),
                           containers=(ContainerConfig("container", "actual-name"),) if family == "docker" else (),
                           models=(model,) if family == "vllm" else (),
                           logging=LogConfig(directory=tmp_path / "logs"))
        discovery_io = RawIO(outputs=(CommandOutput(0, ""),))
        monkeypatch.setattr("joi_observer.runtime.build_hardware_sources", lambda _: SimpleNamespace(
            collectors=(), discovery=GpuDiscovery(discovery_io)))
        provided, defaults = [], []

        def make_port(target):
            port = RawCommand(status="exited") if family == "docker" else RawHttp(model)
            target.append(port)
            return port

        class ProvidedFactory:
            def __bool__(self):
                return truthy

            def __call__(self):
                return make_port(provided)

        selected = ("docker_command_factory", "LocalDockerCommand") if family == "docker" else (
            "vllm_http_factory", "AsyncHttpClient")
        # A mistaken default selection is observable but remains wholly offline.
        monkeypatch.setattr("joi_observer.runtime." + selected[1], lambda: make_port(defaults))
        runtime = CollectorRuntime(config, **{selected[0]: ProvidedFactory()})
        stop = asyncio.Event()
        running = None
        try:
            assert runtime.prepare_log()
            running = asyncio.create_task(runtime.run(stop))
            await until(lambda: all(item.sampled_at is not None for item in runtime.snapshot().objects), running)
            snapshot = runtime.snapshot()
            item = next(item for item in snapshot.objects if item.key.collector == family)
            values = {metric.name: metric.value for metric in item.metrics}
            assert not item.stale
            assert values["state" if family == "docker" else "running"] == ("Exited" if family == "docker" else 0)
            assert len(provided) == 1 and defaults == [], "an explicit falsey Callable was replaced by a default factory"
            if family == "docker":
                assert len(provided[0].calls) == 1 and provided[0].calls[0][0][-1] == "actual-name"
            else:
                assert provided[0].calls == [model.base_url + path for path in ("/version", "/v1/models", "/metrics")]
        finally:
            stop.set()
            if running is not None:
                await asyncio.wait_for(running, 1.2)
            await runtime.close()
        assert discovery_io.closed and all(port.closed for port in provided + defaults)

    asyncio.run(scenario())
