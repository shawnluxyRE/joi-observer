"""Additional public-contract regressions for atomic state and scheduler boundaries."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from joi_observer.data.models import CollectionResult, Metric, ObjectKey, ObjectSpec
from joi_observer.data.state import MonitorState
from joi_observer.error_log import ErrorKind, Failure
from joi_observer.monitor import Monitor


KEY = ObjectKey("vllm", "edge")
SPEC = ObjectSpec(KEY, (Metric("a", None), Metric("b", None)))
FAILURE = Failure(ErrorKind.TIMEOUT, "collection.timeout", "Collection timed out.")


@pytest.mark.parametrize("metrics", [
    (Metric("a", 1),),
    (Metric("a", 1), Metric("a", 2)),
    (Metric("a", float("nan")), Metric("b", 2)),
    (Metric("a", []), Metric("b", 2)),
    (Metric("a", 0, applicable=False), Metric("b", 2)),
    [Metric("a", 1), Metric("b", 2)],
])
def test_invalid_metric_submissions_leave_snapshot_unchanged(metrics):
    state = MonitorState((SPEC,), clock=lambda: 1)
    state.accept(CollectionResult(KEY, (Metric("a", 5), Metric("b", 8))), sampled_at=0)
    before = state.snapshot()
    with pytest.raises(ValueError):
        state.accept(CollectionResult(KEY, metrics), sampled_at=1)
    assert state.snapshot() == before


def test_changed_template_registration_is_atomic():
    state = MonitorState((SPEC,))
    before = state.snapshot()
    with pytest.raises(ValueError):
        state.register(ObjectSpec(KEY, (Metric("different", None),)))
    assert state.snapshot() == before


@pytest.mark.parametrize("kwargs", [
    {"history_seconds": 0}, {"history_seconds": float("inf")},
    {"max_history_points": 0}, {"max_history_points": True},
])
def test_invalid_history_bound_is_rejected(kwargs):
    with pytest.raises(ValueError):
        MonitorState((SPEC,), **kwargs)


def test_duplicate_initial_identity_is_rejected():
    with pytest.raises(ValueError):
        MonitorState((SPEC, SPEC))


class Source:
    spec = ObjectSpec(KEY, (Metric("a", None),))

    def __init__(self, *, gate=None, wrong_key=False, failure=None):
        self.gate = gate
        self.wrong_key = wrong_key
        self.failure = failure
        self.calls = 0
        self.closed = 0

    async def collect(self):
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        key = ObjectKey("gpu", "incorrect") if self.wrong_key else KEY
        return CollectionResult(key, (Metric("a", self.calls),), self.failure)

    async def close(self):
        self.closed += 1


class Log:
    def __init__(self):
        self.events = []

    def record(self, collector, object_id, failure, **times):
        self.events.append((collector, object_id, failure, times))
        return True

    def recovered(self, collector, object_id):
        pass


async def settle(monitor):
    for _ in range(6):
        await monitor.poll()


def test_wrong_result_identity_is_sanitized_for_original_object():
    async def scenario():
        source = Source(wrong_key=True)
        state = MonitorState((source.spec,))
        log = Log()
        monitor = Monitor((source,), state, log)
        try:
            await settle(monitor)
            assert state.snapshot().objects[0].stale
            assert log.events[0][:2] == ("vllm", "edge")
            assert log.events[0][2].code == "collector.unexpected"
        finally:
            await monitor.stop()
    asyncio.run(scenario())


def test_completed_timestamp_and_wall_time_survive_delayed_harvest():
    async def scenario():
        now = [0.0]
        wall = [datetime(2026, 10, 28, 14, tzinfo=timezone(timedelta(hours=8)))]
        source = Source(failure=FAILURE)
        state = MonitorState((source.spec,), clock=lambda: now[0])
        log = Log()
        monitor = Monitor((source,), state, log, clock=lambda: now[0], wall_clock=lambda: wall[0])
        try:
            await monitor.poll()  # Collection finishes during the required yield.
            now[0] = 0.8
            wall[0] += timedelta(days=1)
            await settle(monitor)
            assert state.snapshot().objects[0].sampled_at == 0
            assert log.events[0][3]["monotonic_time"] == 0
            assert log.events[0][3]["occurred_at"].day == 28
        finally:
            await monitor.stop()
    asyncio.run(scenario())


def test_slow_completion_skips_elapsed_slots_without_intermediate_poll():
    async def scenario():
        now = [0.0]
        gate = asyncio.Event()
        source = Source(gate=gate)
        state = MonitorState((source.spec,), clock=lambda: now[0])
        monitor = Monitor((source,), state, Log(), clock=lambda: now[0])
        try:
            await monitor.poll()
            now[0] = 2.2
            gate.set()
            await asyncio.sleep(0)
            await settle(monitor)
            assert source.calls == 1
            now[0] = 3
            await settle(monitor)
            assert source.calls == 2
        finally:
            await monitor.stop()
    asyncio.run(scenario())


def test_poll_cannot_overlap_itself_or_active_run():
    async def scenario():
        state = MonitorState()
        monitor = Monitor((), state, Log())
        polling = asyncio.create_task(monitor.poll())
        await asyncio.sleep(0)
        with pytest.raises(RuntimeError, match="Concurrent"):
            await monitor.poll()
        await polling
        stop = asyncio.Event()
        running = asyncio.create_task(monitor.run(stop))
        await asyncio.sleep(0)
        with pytest.raises(RuntimeError, match="run"):
            await monitor.poll()
        with pytest.raises(RuntimeError, match="running"):
            await monitor.run(stop)
        stop.set()
        await running
    asyncio.run(scenario())


def test_concurrent_stop_closes_once_and_ignores_late_result():
    async def scenario():
        gate = asyncio.Event()
        source = Source(gate=gate)
        state = MonitorState((source.spec,))
        log = Log()
        monitor = Monitor((source,), state, log)
        await monitor.poll()
        before = state.snapshot()
        gate.set()
        await asyncio.gather(monitor.stop(), monitor.stop())
        assert source.closed == 1
        assert state.snapshot() == before
        assert log.events == []
    asyncio.run(scenario())


TIMEOUT = Failure(ErrorKind.TIMEOUT, "collection.timeout", "Collection timed out.")


class LogPort:
    def __init__(self):
        self.errors = []
        self.recoveries = []

    def record(self, collector, object_id, failure, **times):
        self.errors.append((collector, object_id, failure, times))
        return True

    def recovered(self, collector, object_id):
        self.recoveries.append((collector, object_id))


class CooperativeSource:
    def __init__(self, name, *, blocked=False, close_error=False):
        self.spec = ObjectSpec(ObjectKey("vllm", name), (Metric("running", None),))
        self.release = asyncio.Event()
        self.started = asyncio.Event()
        self.cancel_cleanup_finished = asyncio.Event()
        self.closed = 0
        self.calls = 0
        self.close_error = close_error
        if not blocked:
            self.release.set()

    async def collect(self):
        self.calls += 1
        self.started.set()
        try:
            await self.release.wait()
            return CollectionResult(self.spec.key, (Metric("running", self.calls),))
        except asyncio.CancelledError:
            # Exercise real asynchronous cleanup within the 250 ms contract.
            await asyncio.sleep(0.02)
            self.cancel_cleanup_finished.set()
            raise

    async def close(self):
        self.closed += 1
        if self.close_error:
            raise OSError("PRIVATE cleanup failure must not be printed")


def test_run_timeout_recovers_while_fast_source_keeps_sampling(capsys):
    """AC-102/103: timeout cleanup, continued fast sampling, and automatic recovery."""
    async def scenario():
        slow, fast = CooperativeSource("slow", blocked=True), CooperativeSource("fast")
        state = MonitorState((slow.spec, fast.spec))
        log = LogPort()
        timed_out, recovered = asyncio.Event(), asyncio.Event()
        fast_sampled_again = asyncio.Event()

        def updated():
            item, fast_item = state.snapshot().objects
            if item.stale:
                timed_out.set()
            elif timed_out.is_set() and item.sampled_at is not None:
                recovered.set()
            if not fast_item.stale and fast_item.metrics[0].value is not None:
                if fast_item.metrics[0].value >= 2:
                    fast_sampled_again.set()

        monitor = Monitor((slow, fast), state, log, interval=0.01, timeout=0.01,
                          on_update=updated)
        stop = asyncio.Event()
        task = asyncio.create_task(monitor.run(stop))
        try:
            await asyncio.wait_for(timed_out.wait(), timeout=1)
            assert slow.cancel_cleanup_finished.is_set()
            # Timeout completion and the fast source's next dispatch can share
            # one loop tick. Observe the second committed sample, rather than
            # assuming it has already run when the timeout event wakes us.
            await asyncio.wait_for(fast_sampled_again.wait(), timeout=1)
            assert fast.calls >= 2
            fast_item = state.snapshot().objects[1]
            assert not fast_item.stale and fast_item.metrics[0].value >= 2
            slow.release.set()
            await asyncio.wait_for(recovered.wait(), timeout=1)
            item = state.snapshot().objects[0]
            assert not item.stale and item.metrics[0].value >= 2
            assert any(point.metrics is None for point in item.history)
            assert item.history[-1].metrics is not None
            assert log.errors[0][2].code == "collection.timeout"
            assert ("vllm", "slow") in log.recoveries
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=1.1)
        assert slow.closed == fast.closed == 1

    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


def test_run_cancellation_waits_for_cooperative_cleanup_without_failure(capsys):
    """AC-104/110: cancellation is cleanup, with no STALE, ERROR, or late commit."""
    async def scenario():
        source = CooperativeSource("pending", blocked=True)
        state = MonitorState((source.spec,))
        log = LogPort()
        monitor = Monitor((source,), state, log)
        task = asyncio.create_task(monitor.run(asyncio.Event()))
        await asyncio.wait_for(source.started.wait(), timeout=1)
        before = state.snapshot()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1.1)
        assert source.cancel_cleanup_finished.is_set()
        assert source.closed == 1
        assert state.snapshot() == before
        assert log.errors == [] and log.recoveries == []
        await monitor.stop()
        assert source.closed == 1

    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


def test_close_failure_does_not_prevent_other_collectors_cleanup(capsys):
    """One cleanup exception must not strand another object's cancellation."""
    async def scenario():
        bad = CooperativeSource("bad-close", blocked=True, close_error=True)
        other = CooperativeSource("other", blocked=True)
        state = MonitorState((bad.spec, other.spec))
        log = LogPort()
        monitor = Monitor((bad, other), state, log)
        await monitor.poll()
        before = state.snapshot()
        await asyncio.wait_for(monitor.stop(), timeout=1.1)
        assert bad.closed == other.closed == 1
        assert bad.cancel_cleanup_finished.is_set()
        assert other.cancel_cleanup_finished.is_set()
        assert state.snapshot() == before
        assert log.errors == []

    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


def test_history_windows_and_failure_gaps_are_independent_per_object():
    """A busy source's commits may not evict a slow source's still-valid history."""
    now = [0.0]
    first = ObjectKey("gpu", "GPU-a")
    second = ObjectKey("gpu", "GPU-b")
    specs = tuple(ObjectSpec(key, (Metric("util", None, "%"),)) for key in (first, second))
    state = MonitorState(specs, max_history_points=3, clock=lambda: now[0])
    state.accept(CollectionResult(second, (Metric("util", 8, "%"),)), sampled_at=0)
    for stamp in (1, 2, 3, 4):
        state.accept(CollectionResult(first, (Metric("util", stamp, "%"),)), sampled_at=stamp)
    # Completion order and timestamps are per object, rather than global.
    state.accept(CollectionResult(second, failure=TIMEOUT), sampled_at=1)
    now[0] = 4
    before = state.snapshot()
    a, b = before.objects
    assert [point.sampled_at for point in a.history] == [2, 3, 4]
    assert [point.sampled_at for point in b.history] == [0, 1]
    assert b.stale and b.metrics[0].value == 8
    assert b.history[-1].metrics is None
    now[0] = 61
    a, b = state.snapshot().objects
    assert [point.sampled_at for point in a.history] == [2, 3, 4]
    assert [point.sampled_at for point in b.history] == [1]
    assert b.history[0].metrics is None
    assert state.snapshot().revision == before.revision
    assert len(before.objects[1].history) == 2
