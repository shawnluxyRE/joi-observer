"""Additional discovery transaction and resource-lifetime regressions."""

import asyncio

import pytest

from joi_observer.collectors.base import DiscoveryResult
from joi_observer.data.models import CollectionResult, Metric, ObjectKey, ObjectSpec
from test_hardware_monitor import (
    OfflineCollector, OfflineDiscovery, UNAVAILABLE, entries, gpu_spec,
    objects, running_monitor, tick,
)


@pytest.mark.parametrize("invalid", [
    "mutable_specs", "invalid_template", "missing_inventory_field",
    "extra_inventory_field", "failed_inventory_with_children", "wrong_result_type",
])
def test_invalid_discovery_protocol_never_registers_a_partial_round(tmp_path, invalid):
    async def scenario():
        discovery = OfflineDiscovery((gpu_spec("GPU-new"),))
        good_discover = discovery.discover

        async def invalid_discover():
            result = await good_discover()
            if invalid == "mutable_specs":
                return DiscoveryResult(result.inventory, list(result.specs))
            if invalid == "invalid_template":
                return DiscoveryResult(result.inventory, (*result.specs, ObjectSpec(
                    ObjectKey("gpu", "GPU-bad"), (Metric("utilization_percent", 50),))))
            if invalid == "missing_inventory_field":
                return DiscoveryResult(CollectionResult(discovery.spec.key), result.specs)
            if invalid == "extra_inventory_field":
                return DiscoveryResult(CollectionResult(discovery.spec.key, (
                    Metric("device_count", 1), Metric("undeclared", 2))), result.specs)
            if invalid == "failed_inventory_with_children":
                return DiscoveryResult(CollectionResult(
                    discovery.spec.key, failure=UNAVAILABLE), result.specs)
            return result.inventory

        discovery.discover = invalid_discover
        async with running_monitor(tmp_path) as (monitor, state, log, clock, _):
            monitor.register_discovery(discovery)
            await tick(monitor, clock, 0)
            assert list(objects(state)) == [discovery.spec.key]
            assert discovery.factory_specs == []
            assert objects(state)[discovery.spec.key].stale
            recorded = await entries(log, tmp_path)
            assert len(recorded) == 1 and recorded[0]["kind"] == "unexpected"
            discovery.discover = good_discover
            await tick(monitor, clock, 1)
            assert len(objects(state)) == 2
            assert discovery.factory_specs == list(discovery.specs)
            assert not objects(state)[discovery.spec.key].stale

    asyncio.run(scenario())


def test_factory_exception_releases_prior_children_and_retry_has_no_half_state(tmp_path, capsys):
    async def scenario():
        a, b = gpu_spec("GPU-a"), gpu_spec("GPU-b")
        discovery = OfflineDiscovery((a, b))

        def fail_second(spec):
            if spec == b:
                raise OSError("PRIVATE factory failure")
            return OfflineCollector(spec)

        discovery.factory = fail_second
        async with running_monitor(tmp_path) as (monitor, state, log, clock, _):
            monitor.register_discovery(discovery)
            await tick(monitor, clock, 0)
            rejected = discovery.created[0]
            assert rejected.closed and rejected.calls == 0
            assert list(objects(state)) == [discovery.spec.key]
            assert objects(state)[discovery.spec.key].stale
            assert len(await entries(log, tmp_path)) == 1
            discovery.factory = OfflineCollector
            await tick(monitor, clock, 1)
            assert list(objects(state)) == [discovery.spec.key, a.key, b.key]
            assert discovery.factory_specs == [a, b, a, b]
            assert all(child.calls == 1 for child in discovery.created[1:])
            assert not objects(state)[discovery.spec.key].stale

    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


def test_rejected_factory_resource_cleanup_does_not_block_poll_and_is_joined_on_stop(tmp_path):
    async def scenario():
        host = OfflineCollector(ObjectSpec(
            ObjectKey("host", "cpu"), (Metric("cpu_percent", None),)))
        discovery = OfflineDiscovery((gpu_spec("GPU-a"),))
        close_started, release_close = asyncio.Event(), asyncio.Event()
        close_calls = []

        class Rejected(OfflineCollector):
            async def close(self):
                close_calls.append(self)
                close_started.set()
                await release_close.wait()
                self.closed = True

        discovery.factory = lambda spec: Rejected(gpu_spec("GPU-wrong"))
        async with running_monitor(tmp_path, (host,)) as (monitor, state, _, clock, _):
            monitor.register_discovery(discovery)
            await asyncio.wait_for(tick(monitor, clock, 0), 0.25)
            assert close_started.is_set()
            assert not discovery.created[0].closed
            discovery.specs = ()
            await asyncio.wait_for(tick(monitor, clock, 1), 0.25)
            assert host.calls == 2 and not objects(state)[host.spec.key].stale
            stopping = asyncio.create_task(monitor.stop())
            await asyncio.sleep(0)
            assert not stopping.done()
            release_close.set()
            await asyncio.wait_for(stopping, 0.25)
            assert close_calls == discovery.created
            assert discovery.created[0].closed and host.closed and discovery.closed

    asyncio.run(scenario())


def test_static_dynamic_and_discovery_cleanup_starts_in_parallel_and_runs_once(tmp_path):
    async def scenario():
        started, release = [], asyncio.Event()

        async def close_resource(source):
            started.append(source)
            await release.wait()
            source.closed = True

        class ClosingCollector(OfflineCollector):
            async def close(self):
                await close_resource(self)

        class ClosingDiscovery(OfflineDiscovery):
            async def close(self):
                await close_resource(self)

        host = tuple(ClosingCollector(ObjectSpec(
            ObjectKey("host", name), (Metric(name, None),))) for name in ("cpu", "ram"))
        discovery = ClosingDiscovery(tuple(gpu_spec("GPU-" + name) for name in "abc"))
        discovery.factory = lambda spec: ClosingCollector(spec, blocked=True)
        async with running_monitor(tmp_path, host) as (monitor, state, log, clock, _):
            monitor.register_discovery(discovery)
            await tick(monitor, clock, 0)
            before = state.snapshot()
            stopping = asyncio.create_task(monitor.stop())
            for _ in range(20):
                await asyncio.sleep(0)
                if len(started) == 6:
                    break
            try:
                assert len(started) == 6
                assert len({id(source) for source in started}) == 6
                assert all(child.cancelled for child in discovery.created)
            finally:
                release.set()
                await asyncio.wait_for(stopping, 0.25)
            await monitor.stop()
            assert len(started) == 6 and all(source.closed for source in started)
            assert state.snapshot() == before
            assert await entries(log, tmp_path) == []

    asyncio.run(scenario())


def test_rejected_factory_cannot_close_an_already_registered_source(tmp_path):
    """A bad discovery factory must not take ownership of another live source."""
    async def scenario():
        host = OfflineCollector(ObjectSpec(
            ObjectKey("host", "cpu"), (Metric("cpu_percent", None),)))
        discovery = OfflineDiscovery((gpu_spec("GPU-new"),))
        discovery.factory = lambda spec: host
        async with running_monitor(tmp_path, (host,)) as (monitor, state, log, clock, _):
            monitor.register_discovery(discovery)
            await tick(monitor, clock, 0)
            assert set(objects(state)) == {host.spec.key, discovery.spec.key}
            assert objects(state)[discovery.spec.key].stale
            assert not host.closed and host.calls == 1
            assert len(await entries(log, tmp_path)) == 1
            discovery.factory = OfflineCollector
            await tick(monitor, clock, 1)
            assert host.calls == 2 and not host.closed
            assert not objects(state)[host.spec.key].stale
            assert not objects(state)[discovery.spec.key].stale
            assert objects(state)[gpu_spec("GPU-new").key].sampled_at == 1
        assert host.closed and discovery.closed

    asyncio.run(scenario())
