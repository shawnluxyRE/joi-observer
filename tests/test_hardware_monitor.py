"""REQ-002 动态硬件来源的公开调度契约；不访问硬件、终端或服务器。

Discovery/Collector 替身只隔离外部来源，实际运行 Monitor、MonitorState 和
ErrorLog。正确业务断言保留为 R4 目标，不把 R2 的未实现异常当作成功。
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json

import pytest

from joi_observer.collectors.base import DiscoveryResult
from joi_observer.config import LogConfig
from joi_observer.data.models import CollectionResult, Metric, ObjectKey, ObjectSpec
from joi_observer.data.state import MonitorState
from joi_observer.error_log import ErrorKind, ErrorLog, Failure
from joi_observer.monitor import Monitor


NOW = datetime(2026, 10, 30, 10, tzinfo=timezone(timedelta(hours=8)))
UNAVAILABLE = Failure(ErrorKind.UNAVAILABLE, "source.unavailable", "PRIVATE driver detail")
NOT_FOUND = Failure(ErrorKind.NOT_FOUND, "object.not_found", "PRIVATE missing GPU")


def gpu_spec(uuid):
    return ObjectSpec(ObjectKey("gpu", uuid), (Metric("utilization_percent", None, "%"),))


class OfflineCollector:
    """可控制单对象正常值/失败/阻塞的采集边界，不模拟 Monitor 状态合并。"""

    def __init__(self, spec, *, value=0, blocked=False):
        self.spec = spec
        self.value = value
        self.calls = 0
        self.failure = None
        self.closed = False
        self.cancelled = False
        self.gate = asyncio.Event()
        if not blocked:
            self.gate.set()

    async def collect(self):
        self.calls += 1
        try:
            await self.gate.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if self.failure:
            return CollectionResult(self.spec.key, failure=self.failure)
        return CollectionResult(self.spec.key, tuple(
            Metric(metric.name, self.value, metric.unit, metric.applicable)
            for metric in self.spec.metrics
        ))

    async def close(self):
        self.closed = True


class OfflineDiscovery:
    """可变发现清单；工厂只创建来源，不采集、不注册状态。"""

    def __init__(self, specs=(), *, name="local", blocked=False):
        self.spec = ObjectSpec(ObjectKey("gpu_inventory", name), (Metric("device_count", None),))
        self.specs = specs
        self.failure = None
        self.calls = 0
        self.created = []
        self.factory_specs = []
        self.factory = OfflineCollector
        self.closed = False
        self.cancelled = False
        self.return_on_cancel = False
        self.gate = asyncio.Event()
        if not blocked:
            self.gate.set()

    async def discover(self):
        self.calls += 1
        try:
            await self.gate.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            if not self.return_on_cancel:
                raise
        if self.failure:
            return DiscoveryResult(CollectionResult(self.spec.key, failure=self.failure))
        return DiscoveryResult(CollectionResult(
            self.spec.key, (Metric("device_count", len(self.specs)),)
        ), self.specs)

    def create_collector(self, spec):
        self.factory_specs.append(spec)
        child = self.factory(spec)
        self.created.append(child)
        return child

    async def close(self):
        self.closed = True


@asynccontextmanager
async def running_monitor(tmp_path, sources=(), *, timeout=3.0):
    clock = [0.0]
    state = MonitorState(tuple(source.spec for source in sources), clock=lambda: clock[0])
    log = ErrorLog(LogConfig(directory=tmp_path / "logs"))
    assert log.prepare()
    updates = []
    monitor = Monitor(tuple(sources), state, log, timeout=timeout,
                      clock=lambda: clock[0], wall_clock=lambda: NOW + timedelta(seconds=clock[0]),
                      on_update=lambda: updates.append(state.snapshot().revision))
    try:
        yield monitor, state, log, clock, updates
    finally:
        await monitor.stop()
        await log.close()


async def tick(monitor, clock, at):
    """固定单调时间内收割非阻塞离线结果，不用真实等待伪造周期。"""
    clock[0] = at
    for _ in range(12):
        await monitor.poll()
        await asyncio.sleep(0)


def objects(state):
    return {obj.key: obj for obj in state.snapshot().objects}


async def entries(log, tmp_path):
    assert await log.flush()
    return [json.loads(line) for line in (tmp_path / "logs" / "error.log").read_text(
        encoding="utf-8").splitlines()]


def test_register_discovery_is_io_free_and_creates_only_unknown_inventory(tmp_path):
    async def scenario():
        discovery = OfflineDiscovery((gpu_spec("GPU-a"),))
        async with running_monitor(tmp_path) as (monitor, state, log, _, _):
            monitor.register_discovery(discovery)
            assert discovery.calls == 0 and discovery.created == []
            initial = state.snapshot().objects
            assert len(initial) == 1 and initial[0].key == discovery.spec.key
            assert initial[0].metrics == (Metric("device_count", None),)
            assert initial[0].sampled_at is None and not initial[0].stale
            assert await entries(log, tmp_path) == []
    asyncio.run(scenario())


def test_first_discovery_adds_every_gpu_in_order_and_samples_immediately(tmp_path):
    async def scenario():
        specs = (gpu_spec("GPU-b"), gpu_spec("GPU-a"), gpu_spec("GPU-c"))
        discovery = OfflineDiscovery(specs)
        async with running_monitor(tmp_path) as (monitor, state, log, clock, updates):
            monitor.register_discovery(discovery)
            await tick(monitor, clock, 0)
            snapshot = state.snapshot()
            assert tuple(obj.key for obj in snapshot.objects) == (
                discovery.spec.key, *(spec.key for spec in specs))
            assert objects(state)[discovery.spec.key].metrics == (Metric("device_count", 3),)
            assert discovery.calls == 1 and discovery.factory_specs == list(specs)
            assert [child.calls for child in discovery.created] == [1, 1, 1]
            assert all(obj.sampled_at == 0 and not obj.stale for obj in snapshot.objects)
            assert all(len(obj.history) == 1 for obj in snapshot.objects)
            assert updates and updates[-1] == snapshot.revision
            assert await entries(log, tmp_path) == []
        assert discovery.closed and all(child.closed for child in discovery.created)
    asyncio.run(scenario())


def test_repeated_discovery_keeps_gpu_origin_history_and_one_factory_call(tmp_path):
    async def scenario():
        discovery = OfflineDiscovery((gpu_spec("GPU-a"),), blocked=True)
        async with running_monitor(tmp_path) as (monitor, state, _, clock, _):
            monitor.register_discovery(discovery)
            await tick(monitor, clock, 0)
            assert discovery.calls == 1 and discovery.created == []
            discovery.gate.set()
            await tick(monitor, clock, 0.2)
            child = discovery.created[0]
            assert child.calls == 1
            await tick(monitor, clock, 1.0)
            assert discovery.calls == 2 and child.calls == 1
            await tick(monitor, clock, 1.199)
            assert child.calls == 1
            await tick(monitor, clock, 1.2)
            assert child.calls == 2
            assert discovery.factory_specs == [child.spec]
            assert [point.sampled_at for point in objects(state)[child.spec.key].history] == [0.2, 1.2]
    asyncio.run(scenario())


def test_failed_discovery_and_one_failed_card_leave_other_sources_updating(tmp_path, capsys):
    async def scenario():
        host = OfflineCollector(ObjectSpec(ObjectKey("host", "cpu"), (Metric("cpu_percent", None, "%"),)), value=10)
        discovery = OfflineDiscovery((gpu_spec("GPU-a"), gpu_spec("GPU-b")))
        async with running_monitor(tmp_path, (host,)) as (monitor, state, log, clock, _):
            monitor.register_discovery(discovery)
            await tick(monitor, clock, 0)
            bad, good = discovery.created
            bad.value, good.value = 25, 75
            await tick(monitor, clock, 1)
            discovery.failure = UNAVAILABLE
            bad.failure = NOT_FOUND
            good.value, host.value = 80, 20
            await tick(monitor, clock, 2)
            current = objects(state)
            assert current[discovery.spec.key].stale
            assert current[bad.spec.key].stale and current[bad.spec.key].metrics[0].value == 25
            assert current[bad.spec.key].history[-1].metrics is None
            assert not current[good.spec.key].stale and current[good.spec.key].metrics[0].value == 80
            assert not current[host.spec.key].stale and current[host.spec.key].metrics[0].value == 20
            assert [source.calls for source in (bad, good, host)] == [3, 3, 3]
            recorded = await entries(log, tmp_path)
            assert {(item["collector"], item["object_id"]) for item in recorded} == {
                ("gpu_inventory", "local"), ("gpu", "GPU-a")}
            assert all(item["level"] == "ERROR" for item in recorded)
            assert "PRIVATE" not in json.dumps(recorded) and "PRIVATE" not in repr(state.snapshot())
            discovery.failure = bad.failure = None
            await tick(monitor, clock, 3)
            assert all(not item.stale for item in state.snapshot().objects)
            assert len(await entries(log, tmp_path)) == 2
    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


def test_removed_gpu_keeps_slot_and_new_gpu_appends_without_reordering(tmp_path):
    async def scenario():
        a, b, c = (gpu_spec("GPU-" + name) for name in "abc")
        discovery = OfflineDiscovery((a, b))
        async with running_monitor(tmp_path) as (monitor, state, log, clock, _):
            monitor.register_discovery(discovery)
            await tick(monitor, clock, 0)
            old_a, old_b = discovery.created
            discovery.specs = (b, c)
            old_a.failure = NOT_FOUND
            await tick(monitor, clock, 1)
            assert [obj.key for obj in state.snapshot().objects if obj.key.collector == "gpu"] == [a.key, b.key, c.key]
            assert discovery.factory_specs == [a, b, c]
            assert objects(state)[a.key].stale and old_a.calls == old_b.calls == 2
            assert discovery.created[2].calls == 1
            discovery.specs = (c, b, a)
            old_a.failure = None
            await tick(monitor, clock, 2)
            assert [obj.key for obj in state.snapshot().objects if obj.key.collector == "gpu"] == [a.key, b.key, c.key]
            assert discovery.factory_specs == [a, b, c]
            assert len(objects(state)[a.key].history) == 3 and not objects(state)[a.key].stale
            assert len(await entries(log, tmp_path)) == 1
    asyncio.run(scenario())


def test_successful_empty_discovery_is_not_failure_and_does_not_delete_old_gpu(tmp_path):
    async def scenario():
        discovery = OfflineDiscovery()
        async with running_monitor(tmp_path) as (monitor, state, log, clock, _):
            monitor.register_discovery(discovery)
            await tick(monitor, clock, 0)
            assert list(objects(state)) == [discovery.spec.key]
            assert objects(state)[discovery.spec.key].metrics[0].value == 0
            assert not objects(state)[discovery.spec.key].stale
            discovery.specs = (gpu_spec("GPU-a"),)
            await tick(monitor, clock, 1)
            child = discovery.created[0]
            discovery.specs = ()
            child.failure = NOT_FOUND
            await tick(monitor, clock, 2)
            assert list(objects(state)) == [discovery.spec.key, child.spec.key]
            assert not objects(state)[discovery.spec.key].stale and objects(state)[child.spec.key].stale
            recorded = await entries(log, tmp_path)
            assert [(item["collector"], item["object_id"]) for item in recorded] == [("gpu", "GPU-a")]
    asyncio.run(scenario())


def test_initial_discovery_failure_keeps_unknown_count_then_recovers_without_fake_card(tmp_path):
    async def scenario():
        discovery = OfflineDiscovery((gpu_spec("GPU-a"),))
        discovery.failure = UNAVAILABLE
        async with running_monitor(tmp_path) as (monitor, state, log, clock, _):
            monitor.register_discovery(discovery)
            await tick(monitor, clock, 0)
            inventory = objects(state)[discovery.spec.key]
            assert list(objects(state)) == [discovery.spec.key]
            assert inventory.stale and inventory.metrics[0].value is None
            assert inventory.history[-1].metrics is None and discovery.created == []
            discovery.failure = None
            await tick(monitor, clock, 1)
            assert len(state.snapshot().objects) == 2 and len(discovery.created) == 1
            assert all(not obj.stale for obj in state.snapshot().objects)
            assert objects(state)[discovery.spec.key].metrics[0].value == 1
            assert len(await entries(log, tmp_path)) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("bad_list", ["duplicate", "static_collision", "inventory_collision"])
def test_invalid_discovery_declarations_are_rejected_before_any_child_registration(tmp_path, bad_list):
    async def scenario():
        static = OfflineCollector(gpu_spec("GPU-static"))
        discovery = OfflineDiscovery()
        new = gpu_spec("GPU-new")
        bad_spec = {"duplicate": new, "static_collision": static.spec,
                    "inventory_collision": discovery.spec}[bad_list]
        discovery.specs = (new, bad_spec)
        async with running_monitor(tmp_path, (static,)) as (monitor, state, log, clock, _):
            monitor.register_discovery(discovery)
            await tick(monitor, clock, 0)
            assert list(objects(state)) == [static.spec.key, discovery.spec.key]
            assert discovery.factory_specs == []
            assert static.calls == 1 and not objects(state)[static.spec.key].stale
            assert objects(state)[discovery.spec.key].stale
            recorded = await entries(log, tmp_path)
            assert len(recorded) == 1 and recorded[0]["kind"] == "unexpected"
            assert recorded[0]["collector"] == "gpu_inventory"
    asyncio.run(scenario())


def test_changed_existing_template_rejects_entire_round_and_preserves_old_collector(tmp_path):
    async def scenario():
        a = gpu_spec("GPU-a")
        discovery = OfflineDiscovery((a,))
        async with running_monitor(tmp_path) as (monitor, state, log, clock, _):
            monitor.register_discovery(discovery)
            await tick(monitor, clock, 0)
            child = discovery.created[0]
            discovery.specs = (gpu_spec("GPU-new"), ObjectSpec(a.key, (Metric("changed", None),)))
            await tick(monitor, clock, 1)
            assert list(objects(state)) == [discovery.spec.key, a.key]
            assert discovery.factory_specs == [a] and child.calls == 2
            assert objects(state)[a.key].metrics[0].name == "utilization_percent"
            assert not objects(state)[a.key].stale and objects(state)[discovery.spec.key].stale
            assert len(await entries(log, tmp_path)) == 1
    asyncio.run(scenario())


def test_cross_discovery_child_collision_cannot_take_over_existing_source(tmp_path):
    async def scenario():
        shared = gpu_spec("GPU-shared")
        first = OfflineDiscovery((shared,), name="first")
        second = OfflineDiscovery((), name="second")
        async with running_monitor(tmp_path) as (monitor, state, log, clock, _):
            monitor.register_discovery(first)
            monitor.register_discovery(second)
            await tick(monitor, clock, 0)
            second.specs = (gpu_spec("GPU-new"), shared)
            await tick(monitor, clock, 1)
            assert second.factory_specs == []
            assert [obj.key for obj in state.snapshot().objects if obj.key.collector == "gpu"] == [shared.key]
            assert first.created[0].calls == 2 and not objects(state)[first.spec.key].stale
            assert objects(state)[second.spec.key].stale
            recorded = await entries(log, tmp_path)
            assert len(recorded) == 1 and recorded[0]["object_id"] == "second"
    asyncio.run(scenario())


def test_factory_identity_mismatch_rolls_back_round_and_closes_unused_sources(tmp_path):
    async def scenario():
        a, b = gpu_spec("GPU-a"), gpu_spec("GPU-b")
        discovery = OfflineDiscovery((a, b))
        discovery.factory = lambda spec: OfflineCollector(spec if spec == a else gpu_spec("GPU-wrong"))
        async with running_monitor(tmp_path) as (monitor, state, log, clock, _):
            monitor.register_discovery(discovery)
            await tick(monitor, clock, 0)
            assert list(objects(state)) == [discovery.spec.key]
            assert discovery.created and all(child.closed for child in discovery.created)
            assert all(child.calls == 0 for child in discovery.created)
            assert objects(state)[discovery.spec.key].stale
            recorded = await entries(log, tmp_path)
            assert len(recorded) == 1 and recorded[0]["kind"] == "unexpected"
    asyncio.run(scenario())


def test_slow_discovery_does_not_block_host_or_duplicate_pending_discoveries(tmp_path):
    async def scenario():
        host = OfflineCollector(ObjectSpec(ObjectKey("host", "ram"), (Metric("ram_percent", None, "%"),)))
        discovery = OfflineDiscovery((gpu_spec("GPU-a"),), blocked=True)
        async with running_monitor(tmp_path, (host,)) as (monitor, state, _, clock, _):
            monitor.register_discovery(discovery)
            for at in (0, 1, 2):
                await asyncio.wait_for(tick(monitor, clock, at), timeout=0.5)
            assert discovery.calls == 1 and host.calls == 3
            assert objects(state)[host.spec.key].sampled_at == 2
            discovery.gate.set()
            await tick(monitor, clock, 2.2)
            assert discovery.calls == 1 and discovery.created[0].calls == 1
            await tick(monitor, clock, 3)
            assert discovery.calls == 2 and host.calls == 4
    asyncio.run(scenario())


def test_discovery_timeout_uses_inventory_error_and_keeps_static_source_healthy(tmp_path, capsys):
    async def scenario():
        host = OfflineCollector(ObjectSpec(ObjectKey("host", "cpu"), (Metric("cpu_percent", None, "%"),)))
        discovery = OfflineDiscovery((gpu_spec("GPU-a"),), blocked=True)
        async with running_monitor(tmp_path, (host,), timeout=0.01) as (monitor, state, log, clock, _):
            monitor.register_discovery(discovery)
            await tick(monitor, clock, 0)
            await asyncio.sleep(0.03)
            await tick(monitor, clock, 0.03)
            assert discovery.cancelled and discovery.created == []
            assert objects(state)[discovery.spec.key].stale
            assert not objects(state)[host.spec.key].stale
            recorded = await entries(log, tmp_path)
            assert len(recorded) == 1 and recorded[0]["kind"] == "timeout"
            assert recorded[0]["collector"] == "gpu_inventory"
    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("late_result", [False, True])
def test_stop_cancels_discovery_and_discards_late_result_without_registration(tmp_path, late_result, capsys):
    async def scenario():
        discovery = OfflineDiscovery((gpu_spec("GPU-late"),), blocked=True)
        discovery.return_on_cancel = late_result
        async with running_monitor(tmp_path) as (monitor, state, log, clock, _):
            monitor.register_discovery(discovery)
            await tick(monitor, clock, 0)
            before = state.snapshot()
            await monitor.stop()
            discovery.gate.set()
            await asyncio.sleep(0)
            assert state.snapshot() == before
            assert discovery.cancelled and discovery.closed and discovery.created == []
            assert await entries(log, tmp_path) == []
            with pytest.raises(RuntimeError) as error:
                await monitor.poll()
            assert type(error.value) is RuntimeError
    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


def test_stop_closes_dynamic_cards_and_inventory_and_cancels_card_io(tmp_path):
    async def scenario():
        discovery = OfflineDiscovery((gpu_spec("GPU-a"), gpu_spec("GPU-b")))
        discovery.factory = lambda spec: OfflineCollector(spec, blocked=True)
        async with running_monitor(tmp_path) as (monitor, state, log, clock, _):
            monitor.register_discovery(discovery)
            await tick(monitor, clock, 0)
            before = state.snapshot()
            assert [child.calls for child in discovery.created] == [1, 1]
            await monitor.stop()
            await monitor.stop()
            assert discovery.closed and all(child.closed and child.cancelled for child in discovery.created)
            assert state.snapshot() == before
            assert await entries(log, tmp_path) == []
    asyncio.run(scenario())


def test_duplicate_inventory_key_is_rejected_without_replacing_registered_discovery(tmp_path):
    async def scenario():
        first, duplicate = OfflineDiscovery(), OfflineDiscovery()
        async with running_monitor(tmp_path) as (monitor, state, _, clock, _):
            monitor.register_discovery(first)
            before = state.snapshot()
            with pytest.raises(ValueError):
                monitor.register_discovery(duplicate)
            assert state.snapshot() == before
            await tick(monitor, clock, 0)
            assert first.calls == 1 and duplicate.calls == 0
    asyncio.run(scenario())


def test_inventory_key_cannot_collide_with_static_collector(tmp_path):
    async def scenario():
        discovery = OfflineDiscovery()
        static = OfflineCollector(discovery.spec)
        async with running_monitor(tmp_path, (static,)) as (monitor, state, _, _, _):
            before = state.snapshot()
            with pytest.raises(ValueError):
                monitor.register_discovery(discovery)
            assert state.snapshot() == before and discovery.calls == 0
    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["poll", "stopped"])
def test_registration_after_scheduling_or_stop_is_rejected_without_state_change(tmp_path, phase):
    async def scenario():
        async with running_monitor(tmp_path) as (monitor, state, _, clock, _):
            if phase == "poll":
                await tick(monitor, clock, 0)
            else:
                await monitor.stop()
            before = state.snapshot()
            with pytest.raises(RuntimeError) as error:
                monitor.register_discovery(OfflineDiscovery())
            assert type(error.value) is RuntimeError
            assert state.snapshot() == before
    asyncio.run(scenario())
