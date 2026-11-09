"""离线调度契约：常规场景运行真实 Monitor/MonitorState。

类型分派用例只观察公开状态提交边界，其余替身隔离采集IO与日志端口。
"""

import asyncio
from datetime import datetime, timezone

import pytest

from joi_observer.config import ModelConfig, ModelType
from joi_observer.data.models import (CollectionResult, MetricCollectionResult, Metric,
                                    ObjectKey, ObjectSpec, ObjectSnapshot, StateSnapshot)
from joi_observer.data.state import MonitorState
from joi_observer.data.vllm import (VllmCollectionResult, VllmObservation, ChatEngineSample,
                                  CounterSample, LatencySample, make_vllm_spec)
from joi_observer.error_log import ErrorKind, Failure
from joi_observer.monitor import Monitor


class Source:
    """离线外部采集端口，支持阻塞、异常和受控失败，不访问硬件/服务。"""

    def __init__(self, name, *, block=False, failure=None, crash=False):
        self.spec = ObjectSpec(ObjectKey("vllm", name), (Metric("running", None),))
        self.calls = 0
        self.closed = False
        self.cancelled = False
        self.gate = asyncio.Event()
        if not block:
            self.gate.set()
        self.failure = failure
        self.crash = crash

    async def collect(self):
        self.calls += 1
        try:
            await self.gate.wait()
            if self.crash:
                raise RuntimeError("SECRET raw response must not escape")
            return MetricCollectionResult(self.spec.key, (Metric("running", self.calls),), failure=self.failure)
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def close(self):
        self.closed = True


class LogPort:
    def __init__(self):
        self.errors = []
        self.recoveries = []

    def record(self, collector, object_id, failure, **times):
        self.errors.append((collector, object_id, failure, times))
        return False  # 模拟日志限频/不可写，不得影响 Monitor 的状态提交。

    def recovered(self, collector, object_id):
        self.recoveries.append((collector, object_id))


class RecordingState(MonitorState):
    """记录公开提交参数，真实状态校验、合并与快照行为仍由父类执行。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.submitted = []

    def accept(self, result, *, sampled_at):
        self.submitted.append(result)
        super().accept(result, sampled_at=sampled_at)


def setup_monitor(sources, *, interval=1, timeout=3):
    now = [0.0]
    state = RecordingState(tuple(s.spec for s in sources), clock=lambda: now[0])
    logs = LogPort()
    updates = []
    monitor = Monitor(tuple(sources), state, logs, interval=interval, timeout=timeout,
                      clock=lambda: now[0], wall_clock=lambda: datetime(2026, 10, 28, tzinfo=timezone.utc),
                      on_update=lambda: updates.append(state.snapshot().revision))
    return monitor, state, logs, now, updates


async def settle(monitor):
    # 多次poll只收割已经完成的任务；不给时钟加秒，不能引入新采样。
    for _ in range(8):
        await monitor.poll()
        await asyncio.sleep(0)


@pytest.mark.parametrize("interval", [1.0, 2.5])
def test_ac102_immediate_then_configured_cadence_without_ui_collection(interval):
    async def scenario():
        source = Source("chat")
        monitor, state, _, now, updates = setup_monitor([source], interval=interval)
        try:
            await settle(monitor)
            assert source.calls == 1
            assert state.snapshot().objects[0].metrics[0].value == 1
            for _ in range(20):
                state.snapshot()
            now[0] = interval - 0.001
            await settle(monitor)
            assert source.calls == 1
            now[0] = interval
            await settle(monitor)
            assert source.calls == 2
            assert len(updates) == 2
        finally:
            await monitor.stop()
    asyncio.run(scenario())


def test_ac103_slow_source_does_not_block_or_accumulate_requests():
    async def scenario():
        slow, fast = Source("slow", block=True), Source("fast")
        monitor, state, _, now, _ = setup_monitor([slow, fast])
        try:
            await asyncio.wait_for(settle(monitor), 0.5)
            assert slow.calls == fast.calls == 1
            now[0] = 1
            await settle(monitor)
            now[0] = 2
            await settle(monitor)
            assert slow.calls == 1 and fast.calls == 3
            assert state.snapshot().objects[1].metrics[0].value == 3
            slow.gate.set()
            now[0] = 2.2
            await settle(monitor)
            assert slow.calls == 1
            now[0] = 3
            await settle(monitor)
            assert slow.calls == 2
        finally:
            await monitor.stop()
    asyncio.run(scenario())


def test_ac103_timeout_marks_only_its_source_stale():
    async def scenario():
        slow, fast = Source("slow", block=True), Source("fast")
        monitor, state, logs, now, _ = setup_monitor([slow, fast], timeout=0.01)
        try:
            await settle(monitor)
            await asyncio.sleep(0.03)
            now[0] = 0.03
            await settle(monitor)
            a, b = state.snapshot().objects
            assert a.stale and not b.stale
            assert logs.errors[0][2].kind == ErrorKind.TIMEOUT
            assert logs.errors[0][2].code == "collection.timeout"
            submitted = [result for result in state.submitted if result.key == slow.spec.key]
            assert len(submitted) == 1 and type(submitted[0]) is CollectionResult
            assert not hasattr(submitted[0], "metrics") and not hasattr(submitted[0], "observation")
            assert submitted[0].failure is logs.errors[0][2]
            assert slow.cancelled
        finally:
            await monitor.stop()
    asyncio.run(scenario())


def test_ac110_unexpected_exception_is_sanitized_and_other_source_continues(capsys):
    async def scenario():
        monitor, state, logs, _, _ = setup_monitor([Source("bad", crash=True), Source("ok")])
        try:
            await settle(monitor)
            assert state.snapshot().objects[0].stale
            assert not state.snapshot().objects[1].stale
            failure = logs.errors[0][2]
            assert failure.code == "collector.unexpected"
            assert "SECRET" not in repr(failure)
            submitted = [result for result in state.submitted if result.key == ObjectKey("vllm", "bad")]
            assert len(submitted) == 1 and type(submitted[0]) is CollectionResult
            assert not hasattr(submitted[0], "metrics") and not hasattr(submitted[0], "observation")
            assert submitted[0].failure is failure
        finally:
            await monitor.stop()
    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


def test_ac112_log_suppression_does_not_reduce_sampling_or_stale_updates():
    async def scenario():
        failure = Failure(ErrorKind.UNAVAILABLE, "source.unavailable", "Data source is unavailable.")
        source = Source("chat", failure=failure)
        monitor, state, logs, now, updates = setup_monitor([source])
        try:
            for tick in range(61):
                now[0] = tick
                await settle(monitor)
            assert source.calls == len(updates) == len(logs.errors) == 61
            assert state.snapshot().objects[0].stale
            source.failure = None
            now[0] = 61
            await settle(monitor)
            assert not state.snapshot().objects[0].stale
            assert logs.recoveries[-1] == ("vllm", "chat")
        finally:
            await monitor.stop()
    asyncio.run(scenario())


def test_ac104_shutdown_cancels_pending_work_without_logging_cancellation():
    async def scenario():
        source = Source("pending", block=True)
        monitor, _, logs, _, _ = setup_monitor([source])
        await settle(monitor)
        await asyncio.wait_for(monitor.stop(), 1.1)
        await monitor.stop()
        assert source.cancelled and source.closed
        assert not logs.errors
        with pytest.raises(RuntimeError):
            await monitor.poll()
    asyncio.run(scenario())


def test_run_with_stop_already_set_never_starts_collection():
    async def scenario():
        source = Source("unused")
        monitor, _, logs, _, _ = setup_monitor([source])
        stop = asyncio.Event()
        stop.set()
        await asyncio.wait_for(monitor.run(stop), 0.5)
        assert source.calls == 0
        assert not logs.errors
    asyncio.run(scenario())


@pytest.mark.parametrize("cancel", [False, True])
def test_running_monitor_stops_and_closes_pending_source(cancel):
    async def scenario():
        source = Source("pending", block=True)
        monitor, _, logs, _, _ = setup_monitor([source])
        stop = asyncio.Event()
        running = asyncio.create_task(monitor.run(stop))
        try:
            for _ in range(30):
                if running.done():
                    await running  # 未实现/真实缺陷直接暴露，不伪装成等待超时。
                if source.calls:
                    break
                await asyncio.sleep(0.002)
            assert source.calls == 1
            if cancel:
                running.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(running, 1.1)
            else:
                stop.set()
                await asyncio.wait_for(running, 1.1)
            assert source.cancelled and source.closed
            assert not logs.errors
        finally:
            if not running.done():
                running.cancel()
                await asyncio.gather(running, return_exceptions=True)
    asyncio.run(scenario())


@pytest.mark.parametrize("value,applicable", [(0, True), (None, True), (None, False), ("Exited", True)])
def test_ac108_normal_zero_unsupported_inapplicable_and_exited_do_not_log(value, applicable):
    class SuccessfulSource(Source):
        async def collect(self):
            self.calls += 1
            return MetricCollectionResult(self.spec.key, (Metric("running", value, applicable=applicable),))

    async def scenario():
        monitor, state, logs, _, _ = setup_monitor([SuccessfulSource("normal")])
        try:
            await settle(monitor)
            assert not state.snapshot().objects[0].stale
            assert logs.errors == []
        finally:
            await monitor.stop()
    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["metric", "vllm"])
def test_monitor_forwards_concrete_success_result_unchanged(kind):
    """仅检验Monitor提交边界，不以spy替代尚未实现的vLLM状态业务验收。"""
    if kind == "metric":
        spec = ObjectSpec(ObjectKey("host", "cpu"), (Metric("usage", None, "%"),))
        produced = MetricCollectionResult(spec.key, (Metric("usage", 25, "%"),))
    else:
        config = ModelConfig("chat", ModelType.CHAT, "model", "http://offline.invalid")
        spec = make_vllm_spec(config)
        sample = ChatEngineSample("0", running=0, waiting=0, queue=LatencySample(0, 0),
                                  kv_cache_fraction=0, prompt_tokens=CounterSample(0),
                                  generation_tokens=CounterSample(0), ttft=LatencySample(0, 0))
        produced = VllmCollectionResult(spec.key, VllmObservation(ModelType.CHAT, "model", (sample,)))

    class SubmissionPort:
        def __init__(self):
            self.submitted = []

        def snapshot(self):
            return StateSnapshot((ObjectSnapshot(spec.key, spec.metrics),))

        def accept(self, result, *, sampled_at):
            self.submitted.append(result)

    class ReturningSource:
        def __init__(self):
            self.spec = spec

        async def collect(self):
            return produced

        async def close(self):
            pass

    async def scenario():
        state, logs = SubmissionPort(), LogPort()
        monitor = Monitor((ReturningSource(),), state, logs, clock=lambda: 0)
        try:
            await settle(monitor)
            assert len(state.submitted) == 1 and state.submitted[0] is produced
            assert produced.failure is None
            assert logs.errors == []
            assert logs.recoveries == [(spec.key.collector, spec.key.object_id)]
        finally:
            await monitor.stop()

    asyncio.run(scenario())
