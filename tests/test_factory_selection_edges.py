"""Only None selects a default; explicit IO Callables need no truth value."""

import asyncio
from types import SimpleNamespace

import pytest

from joi_observer.collectors.hardware import CommandOutput, GpuDiscovery
from joi_observer.collectors.vllm import build_vllm_collectors
from joi_observer.config import AppConfig, ContainerConfig, LogConfig
from joi_observer.runtime import CollectorRuntime
from test_docker_integration import RawCommand
from test_hardware import RawIO
from test_vllm_integration import RawHttp, configs, settle


class NoTruthFactory:
    def __init__(self, make):
        self.make = make
        self.calls = 0
        self.truth_queries = 0

    def __bool__(self):
        self.truth_queries += 1
        raise AssertionError("Factory selection must not request a truth value")

    def __call__(self):
        self.calls += 1
        return self.make()


class EmptyLengthFactory:
    def __init__(self, make):
        self.make = make
        self.calls = 0
        self.length_queries = 0

    def __len__(self):
        self.length_queries += 1
        return 0

    def __call__(self):
        self.calls += 1
        return self.make()


def empty_hardware(monkeypatch):
    io = RawIO(outputs=(CommandOutput(0, ""),))
    monkeypatch.setattr("joi_observer.runtime.build_hardware_sources", lambda config: SimpleNamespace(
        collectors=(), discovery=GpuDiscovery(io)))
    return io


def settings(tmp_path, family):
    return AppConfig(mount_points=(),
                     containers=tuple(ContainerConfig(f"docker-{i}", f"actual-{i}") for i in range(2))
                     if family == "docker" else (),
                     models=configs()[:2] if family == "vllm" else (),
                     logging=LogConfig(directory=tmp_path / "logs"))


def port_factory(config, family, ports):
    def make():
        port = RawCommand(status="paused") if family == "docker" else RawHttp(config.models[len(ports)])
        ports.append(port)
        return port
    return make


def forbid_default(*args, **kwargs):
    pytest.fail("An explicitly supplied factory must not use default IO")


async def sample_runtime(runtime, family):
    assert runtime.prepare_log()
    await settle(runtime.components.monitor)
    objects = [item for item in runtime.snapshot().objects if item.key.collector == family]
    assert len(objects) == 2 and all(item.sampled_at is not None and not item.stale for item in objects)
    for item in objects:
        values = {metric.name: metric.value for metric in item.metrics}
        assert values["state" if family == "docker" else "running"] == ("Paused" if family == "docker" else 0)


@pytest.mark.parametrize("family", ["docker", "vllm"])
def test_runtime_explicit_factory_is_called_per_object_without_boolean_queries(tmp_path, monkeypatch, family):
    async def scenario():
        hardware = empty_hardware(monkeypatch)
        config = settings(tmp_path, family)
        ports = []
        factory = NoTruthFactory(port_factory(config, family, ports))
        option, default = ("docker_command_factory", "LocalDockerCommand") if family == "docker" else (
            "vllm_http_factory", "AsyncHttpClient")
        monkeypatch.setattr("joi_observer.runtime." + default, forbid_default)
        runtime = CollectorRuntime(config, **{option: factory})
        try:
            await sample_runtime(runtime, family)
            assert factory.calls == 2 and factory.truth_queries == 0
            assert len({id(port) for port in ports}) == 2
            if family == "docker":
                assert [port.calls[0][0][-1] for port in ports] == [item.name for item in config.containers]
            else:
                assert [port.calls for port in ports] == [
                    [model.base_url + path for path in ("/version", "/v1/models", "/metrics")]
                    for model in config.models]
        finally:
            await runtime.close()
        assert hardware.closed and all(port.closed for port in ports)
    asyncio.run(scenario())


def test_vllm_builder_preserves_zero_length_factory_for_every_model(tmp_path, monkeypatch):
    async def scenario():
        config = settings(tmp_path, "vllm")
        ports = []
        factory = EmptyLengthFactory(port_factory(config, "vllm", ports))
        monkeypatch.setattr("joi_observer.collectors.vllm.AsyncHttpClient", forbid_default)
        collectors = build_vllm_collectors(config, http_factory=factory)
        try:
            results = [await collector.collect() for collector in collectors]
            assert all(result.failure is None and result.observation.engines[0].running == 0 for result in results)
            assert factory.calls == 2 and factory.length_queries == 0
            assert len({id(port) for port in ports}) == 2
        finally:
            for collector in collectors:
                await collector.close()
        assert all(port.closed for port in ports)
    asyncio.run(scenario())


@pytest.mark.parametrize("entry", ["runtime", "builder"])
def test_empty_configuration_neither_queries_nor_calls_an_explicit_factory(tmp_path, monkeypatch, entry):
    async def scenario():
        factory = NoTruthFactory(forbid_default)
        config = AppConfig(mount_points=(), logging=LogConfig(directory=tmp_path / "logs"))
        if entry == "runtime":
            hardware = empty_hardware(monkeypatch)
            runtime = CollectorRuntime(config, docker_command_factory=factory, vllm_http_factory=factory)
            try:
                assert runtime.prepare_log()
            finally:
                await runtime.close()
            assert hardware.closed
        else:
            assert build_vllm_collectors(config, http_factory=factory) == ()
        assert factory.calls == 0 and factory.truth_queries == 0
    asyncio.run(scenario())


@pytest.mark.parametrize("family", ["docker", "vllm"])
def test_later_explicit_factory_failure_closes_earlier_owned_port_once(tmp_path, monkeypatch, family):
    async def scenario():
        hardware = empty_hardware(monkeypatch)
        config = settings(tmp_path, family)
        ports, closed = [], []
        make_port = port_factory(config, family, ports)

        def make():
            if ports:
                raise RuntimeError("later explicit factory failed")
            port = make_port()
            original_close = port.close

            async def close():
                closed.append(port)
                await original_close()

            port.close = close
            return port

        factory = NoTruthFactory(make)
        option, default = ("docker_command_factory", "LocalDockerCommand") if family == "docker" else (
            "vllm_http_factory", "AsyncHttpClient")
        monkeypatch.setattr("joi_observer.runtime." + default, forbid_default)
        runtime = CollectorRuntime(config, **{option: factory})
        try:
            with pytest.raises(RuntimeError, match="later explicit factory failed"):
                runtime.prepare_log()
        finally:
            await runtime.close()
            await runtime.close()
        assert factory.calls == 2 and factory.truth_queries == 0
        assert len(ports) == 1 and ports[0].closed and closed == ports
        assert hardware.closed
    asyncio.run(scenario())


@pytest.mark.parametrize("entry", ["runtime-docker", "runtime-vllm", "vllm-builder"])
def test_none_still_selects_the_default_factory_once_per_object(tmp_path, monkeypatch, entry):
    async def scenario():
        family = "docker" if entry == "runtime-docker" else "vllm"
        config = settings(tmp_path, family)
        ports = []
        factory = NoTruthFactory(port_factory(config, family, ports))
        if entry.startswith("runtime"):
            hardware = empty_hardware(monkeypatch)
            option, default = ("docker_command_factory", "LocalDockerCommand") if family == "docker" else (
                "vllm_http_factory", "AsyncHttpClient")
            monkeypatch.setattr("joi_observer.runtime." + default, factory)
            runtime = CollectorRuntime(config, **{option: None})
            try:
                await sample_runtime(runtime, family)
            finally:
                await runtime.close()
            assert hardware.closed
        else:
            monkeypatch.setattr("joi_observer.collectors.vllm.AsyncHttpClient", factory)
            collectors = build_vllm_collectors(config, http_factory=None)
            try:
                results = [await collector.collect() for collector in collectors]
                assert all(result.failure is None for result in results)
            finally:
                for collector in collectors:
                    await collector.close()
        assert factory.calls == 2 and factory.truth_queries == 0
        assert len({id(port) for port in ports}) == 2 and all(port.closed for port in ports)
    asyncio.run(scenario())
