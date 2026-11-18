"""Stop requests cannot turn real Monitor failures into successful outcomes."""

import asyncio

import pytest

from joi_observer.config import AppConfig
from joi_observer.data.models import Metric, MetricCollectionResult
from joi_observer.service import CollectorService
from test_service_contract import MemoryLease, MemoryListener, MemoryLog, MemoryPeer, runtime_fixture, until


def service_for(tmp_path, runtime, *, listener=None, warnings=None):
    path = tmp_path / "config.yaml"
    path.write_text("mount_points: []\nsample_interval: 1\n", encoding="utf-8")
    listener = listener or MemoryListener()
    lease = MemoryLease()
    service = CollectorService(path, runtime_factory=lambda config: runtime,
                               listener=listener, lease=lease,
                               host_factory=lambda: ("Host", "Ubuntu 24.04"),
                               on_warning=None if warnings is None else warnings.append)
    return service, listener, lease


def invalid_source_result(source):
    async def collect():
        source.calls += 1
        # The real State must reject this undeclared field, after the ordinary
        # raw collection boundary succeeded. This is not a source/STALE error.
        return MetricCollectionResult(source.spec.key, (Metric("undeclared", 1.0),))
    return collect


@pytest.mark.parametrize("layer", ["runtime", "service"])
def test_stop_during_monitor_error_cleanup_keeps_internal_failure(tmp_path, layer):
    async def scenario():
        runtime, source, log = runtime_fixture(AppConfig(sample_interval=0.02, mount_points=()))
        source_closing, release_source = asyncio.Event(), asyncio.Event()
        source.collect = invalid_source_result(source)

        async def close_source():
            source_closing.set()
            try:
                await release_source.wait()
            finally:
                source.closed = True

        source.close = close_source
        listener = lease = None
        if layer == "service":
            owner, listener, lease = service_for(tmp_path, runtime)
        else:
            owner = runtime
        stop = asyncio.Event()
        running = asyncio.create_task(owner.run(stop))
        try:
            # State has already failed, while Monitor is still in its real
            # asynchronous finally and the runtime's capture has not returned.
            await asyncio.wait_for(source_closing.wait(), 0.5)
            assert not running.done()
            stop.set()
            await until(lambda: log.closed, running)
            release_source.set()
            with pytest.raises(ValueError, match="fields do not match"):
                await asyncio.wait_for(running, 1.2)
            assert source.calls == 1 and source.closed and log.closed
            if listener is not None:
                assert listener.closed and not lease.held
        finally:
            release_source.set()
            stop.set()
            await asyncio.gather(running, return_exceptions=True)
            await owner.close()
            await runtime.close()
    asyncio.run(scenario())


def test_service_checks_failed_runtime_after_shared_stop_wakes(tmp_path):
    async def scenario():
        closing_log, release_log = asyncio.Event(), asyncio.Event()

        class GatedLog(MemoryLog):
            async def close(self, *, timeout=1.0):
                closing_log.set()
                await release_log.wait()
                return await super().close(timeout=timeout)

        runtime, source, log = runtime_fixture(AppConfig(sample_interval=0.02, mount_points=()), log=GatedLog())
        source.collect = invalid_source_result(source)
        service, listener, lease = service_for(tmp_path, runtime)
        stop = asyncio.Event()
        running = asyncio.create_task(service.run(stop))
        try:
            await asyncio.wait_for(closing_log.wait(), 0.5)
            # Runtime's error cleanup has set the shared event. Service has a
            # ready stop branch, although the failed runtime is not done yet.
            assert stop.is_set() and source.closed and not running.done()
            assert lease.held
            release_log.set()
            with pytest.raises(ValueError, match="fields do not match"):
                await asyncio.wait_for(running, 1.2)
            assert source.calls == 1 and log.closed and listener.closed
            assert not lease.held
        finally:
            release_log.set()
            stop.set()
            await asyncio.gather(running, return_exceptions=True)
            await service.close()
            await runtime.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("layer", ["runtime", "service"])
def test_stop_notified_by_source_cleanup_keeps_same_turn_failure(tmp_path, layer):
    async def scenario():
        runtime, source, log = runtime_fixture(AppConfig(sample_interval=0.02, mount_points=()))
        source.collect = invalid_source_result(source)
        stop = asyncio.Event()

        async def close_source():
            # A stop arriving in the same cleanup turn must not overtake the
            # already raised real State error and report normal completion.
            stop.set()
            await asyncio.sleep(0)
            source.closed = True

        source.close = close_source
        listener = lease = None
        if layer == "service":
            owner, listener, lease = service_for(tmp_path, runtime)
        else:
            owner = runtime
        try:
            with pytest.raises(ValueError, match="fields do not match"):
                await asyncio.wait_for(owner.run(stop), 1.2)
            assert source.calls == 1 and source.closed and log.closed
            if listener is not None:
                assert listener.closed and not lease.held
        finally:
            stop.set()
            await owner.close()
            await runtime.close()
    asyncio.run(scenario())


def test_publication_failure_does_not_hide_later_monitor_error(tmp_path):
    async def scenario():
        runtime, source, log = runtime_fixture(AppConfig(sample_interval=0.02, mount_points=()))
        invalid = False

        async def collect():
            source.calls += 1
            name = "undeclared" if invalid else "cpu_percent"
            return MetricCollectionResult(source.spec.key, (Metric(name, 25.0, "%"),))

        source.collect = collect
        listener, reader = MemoryListener(), MemoryPeer()
        await listener.peers.put(reader)
        warnings = []
        service, _, lease = service_for(tmp_path, runtime, listener=listener, warnings=warnings)
        stop = asyncio.Event()
        running = asyncio.create_task(service.run(stop))
        try:
            await until(lambda: bool(reader.frames), running)
            await listener.peers.put(OSError("offline publication failure"))
            await until(lambda: listener.closed and reader.closed, running)
            assert not running.done() and lease.held
            accepts = listener.accept_calls
            invalid = True
            with pytest.raises(ValueError, match="fields do not match"):
                await asyncio.wait_for(running, 1.2)
            assert source.closed and log.closed and not lease.held
            assert listener.accept_calls == accepts
            assert warnings == ["Snapshot publishing stopped; collection continues. Restart collector service to restore access."]
        finally:
            stop.set()
            await asyncio.gather(running, return_exceptions=True)
            await service.close()
            await runtime.close()
    asyncio.run(scenario())


def test_external_close_during_monitor_error_cleanup_keeps_internal_failure(tmp_path):
    async def scenario():
        runtime, source, log = runtime_fixture(AppConfig(sample_interval=0.02, mount_points=()))
        source.collect = invalid_source_result(source)
        source_closing, release_source = asyncio.Event(), asyncio.Event()

        async def close_source():
            source_closing.set()
            try:
                await release_source.wait()
            finally:
                source.closed = True

        source.close = close_source
        service, listener, lease = service_for(tmp_path, runtime)
        running = asyncio.create_task(service.run(asyncio.Event()))
        closing = None
        try:
            await asyncio.wait_for(source_closing.wait(), 0.5)
            closing = asyncio.create_task(service.close())
            await until(lambda: log.closed, running)
            assert lease.held and not closing.done()
            release_source.set()
            await asyncio.wait_for(closing, 1.2)
            with pytest.raises(ValueError, match="fields do not match"):
                await asyncio.wait_for(running, 1.2)
            assert source.closed and log.closed and listener.closed and not lease.held
        finally:
            release_source.set()
            jobs = (running,) if closing is None else (running, closing)
            await asyncio.gather(*jobs, return_exceptions=True)
            await service.close()
            await runtime.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("layer", ["runtime", "service"])
def test_run_cancellation_during_monitor_error_cleanup_keeps_internal_failure(tmp_path, layer):
    async def scenario():
        baseline = asyncio.all_tasks()
        runtime, source, log = runtime_fixture(AppConfig(sample_interval=0.02, mount_points=()))
        source.collect = invalid_source_result(source)
        source_closing, release_source = asyncio.Event(), asyncio.Event()
        listener = lease = None
        held_at_source_exit = []

        async def close_source():
            source_closing.set()
            try:
                await release_source.wait()
            finally:
                if lease is not None:
                    held_at_source_exit.append(lease.held)
                source.closed = True

        source.close = close_source
        if layer == "service":
            owner, listener, lease = service_for(tmp_path, runtime)
        else:
            owner = runtime
        stop = asyncio.Event()
        running = asyncio.create_task(owner.run(stop))
        try:
            # The real State failure precedes cancellation of the run owner.
            # Cleanup still owns the source and must retain its failure result.
            await asyncio.wait_for(source_closing.wait(), 0.5)
            running.cancel()
            await until(lambda: log.closed, running)
            assert not running.done() and not source.closed
            if lease is not None:
                assert lease.held
            release_source.set()
            with pytest.raises(ValueError, match="fields do not match"):
                await asyncio.wait_for(running, 1.2)
            assert source.calls == 1 and source.closed and log.closed
            if lease is not None:
                assert listener.closed and not lease.held
                assert held_at_source_exit == [True]
            await owner.close()
            await asyncio.sleep(0)
            assert not {task for task in asyncio.all_tasks() - baseline if not task.done()}
        finally:
            release_source.set()
            stop.set()
            await asyncio.gather(running, return_exceptions=True)
            await owner.close()
            await runtime.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("layer", ["runtime", "service"])
def test_explicit_stop_after_valid_samples_keeps_normal_outcome(tmp_path, layer):
    async def scenario():
        runtime, source, log = runtime_fixture(AppConfig(sample_interval=0.02, mount_points=()))
        listener = lease = None
        if layer == "service":
            owner, listener, lease = service_for(tmp_path, runtime)
        else:
            owner = runtime
        stop = asyncio.Event()
        running = asyncio.create_task(owner.run(stop))
        try:
            await until(lambda: source.calls >= 2, running)
            stop.set()
            assert await asyncio.wait_for(running, 1.2) is None
            assert source.closed and log.closed
            if listener is not None:
                assert listener.closed and not lease.held
        finally:
            stop.set()
            await asyncio.gather(running, return_exceptions=True)
            await owner.close()
            await runtime.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("signum", ["SIGINT", "SIGTERM"])
@pytest.mark.parametrize("fatal_first", [False, True], ids=["normal-signal", "fatal-before-signal"])
def test_formal_service_cli_preserves_fatal_or_signal_outcome(
        tmp_path, monkeypatch, signum, fatal_first):
    """Signal delivery must not convert a failed real service into a signal exit."""
    from io import StringIO
    import signal
    from joi_observer.cli import CommandDependencies, run_command

    number = getattr(signal, signum)
    original_handlers = {selected: signal.getsignal(selected)
                         for selected in (signal.SIGINT, signal.SIGTERM)}
    installed = dict(original_handlers)
    deliveries = []

    def signal_boundary(selected, handler):
        previous = installed.get(selected, signal.SIG_DFL)
        installed[selected] = handler
        return previous

    monkeypatch.setattr(signal, "signal", signal_boundary)
    monkeypatch.setattr(signal, "getsignal", lambda selected: installed[selected])
    runtime, source, log = runtime_fixture(AppConfig(sample_interval=0.02, mount_points=()))
    path = tmp_path / "config.yaml"
    path.write_text("mount_points: []\nsample_interval: 1\n", encoding="utf-8")
    listener, lease = MemoryListener(), MemoryLease()
    service = CollectorService(path, runtime_factory=lambda config: runtime,
                               listener=listener, lease=lease,
                               host_factory=lambda: ("Host", "Ubuntu 24.04"))

    def deliver():
        deliveries.append(number)
        installed[number](number, None)

    if fatal_first:
        source.collect = invalid_source_result(source)

        async def close_source():
            # State has already rejected the undeclared result. Deliver the
            # OS signal while its original error is inside Monitor's finally.
            assert source.calls == 1
            deliver()
            await asyncio.sleep(0)
            source.closed = True

        source.close = close_source
    else:
        async def collect():
            source.calls += 1
            deliver()
            return MetricCollectionResult(source.spec.key, (Metric("cpu_percent", 25.0, "%"),))

        source.collect = collect

    def forbidden_client(endpoint):
        pytest.fail("The headless service command must never create a TUI")

    stdout, stderr = StringIO(), StringIO()
    dependencies = CommandDependencies(tmp_path, tmp_path, False, False, "dumb", stdout, stderr,
                                       forbidden_client, lambda config, endpoint: service)
    assert run_command(["service", "--config", str(path)], dependencies=dependencies) == (
        1 if fatal_first else 128 + number)
    assert source.closed and log.closed and listener.closed and not lease.held
    assert deliveries == [number]
    assert installed == original_handlers
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == ("Observer stopped unexpectedly.\n" if fatal_first else "")


def test_service_runtime_join_allocation_failure_does_not_release_live_sources(tmp_path, monkeypatch):
    """Even a failed cleanup helper allocation must retain the instance lease."""
    async def scenario():
        runtime, source, log = runtime_fixture(AppConfig(sample_interval=0.02, mount_points=()))
        source_closing, release_source = asyncio.Event(), asyncio.Event()
        held_at_source_exit = []
        lease = MemoryLease()

        async def close_source():
            source_closing.set()
            try:
                await release_source.wait()
            finally:
                held_at_source_exit.append(lease.held)
                source.closed = True

        source.close = close_source

        class ClosingListener(MemoryListener):
            async def close(self):
                await source_closing.wait()
                self.closed = True

        path = tmp_path / "config.yaml"
        path.write_text("mount_points: []\nsample_interval: 1\n", encoding="utf-8")
        listener = ClosingListener()
        service = CollectorService(path, runtime_factory=lambda config: runtime,
                                   listener=listener, lease=lease,
                                   host_factory=lambda: ("Host", "Ubuntu 24.04"))
        stop = asyncio.Event()
        running = asyncio.create_task(service.run(stop))
        original_create = asyncio.create_task
        rejected = []

        def allocate(coroutine, *args, **kwargs):
            if (coroutine.cr_code.co_qualname == "CollectorRuntime.close"
                    and asyncio.current_task().get_name() == "collector-service-close"
                    and not rejected):
                rejected.append(None)
                coroutine.close()
                raise MemoryError("injected runtime-join allocation failure")
            return original_create(coroutine, *args, **kwargs)

        try:
            await until(lambda: source.calls >= 2, running)
            monkeypatch.setattr(asyncio, "create_task", allocate)
            stop.set()
            with pytest.raises(MemoryError, match="runtime-join allocation"):
                await asyncio.wait_for(running, 1.2)
            assert rejected == [None] and source_closing.is_set()
            assert source.closed, "service returned and released its lease while source cleanup was active"
            assert held_at_source_exit == [True]
            assert log.closed and listener.closed and not lease.held
        finally:
            release_source.set()
            stop.set()
            await asyncio.gather(running, return_exceptions=True)
            await runtime.close()
            await asyncio.gather(service.close(), return_exceptions=True)
            if lease.held:
                lease.release()

    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["runtime-log-close", "runtime-log-settle", "monitor-source-close"])
def test_formal_service_cleanup_allocation_failure_still_joins_all_resources(tmp_path, monkeypatch, stage):
    """Every previously acquired source/log stays owned on cleanup task failure."""
    async def scenario():
        class BoundedLog(MemoryLog):
            async def close(self, *, timeout=1.0):
                # A cooperative, bounded drain can still be unfinished when
                # an allocation failure abandons its just-created owner task.
                await asyncio.sleep(min(timeout, 0.05))
                return await super().close(timeout=timeout)

        log = BoundedLog() if stage == "runtime-log-settle" else MemoryLog()
        runtime, source, _ = runtime_fixture(AppConfig(sample_interval=0.02, mount_points=()), log=log)
        service, listener, lease = service_for(tmp_path, runtime)
        stop = asyncio.Event()
        running = asyncio.create_task(service.run(stop))
        original_create = asyncio.create_task
        rejected = []

        def allocate(coroutine, *args, **kwargs):
            caller = asyncio.current_task().get_name()
            operation = coroutine.cr_code.co_qualname
            selected = (
                stage == "runtime-log-close" and caller == "collector-cleanup"
                and operation == "MemoryLog.close"
                or stage == "runtime-log-settle" and caller == "collector-cleanup"
                and operation == "settle"
                or stage == "monitor-source-close" and operation == "Monitor._close_source"
            )
            if selected and not rejected:
                rejected.append(None)
                coroutine.close()
                raise MemoryError("injected owned cleanup-task allocation failure")
            return original_create(coroutine, *args, **kwargs)

        try:
            await until(lambda: source.calls >= 2, running)
            monkeypatch.setattr(asyncio, "create_task", allocate)
            stop.set()
            with pytest.raises(MemoryError, match="owned cleanup-task allocation"):
                await asyncio.wait_for(running, 1.2)
            assert rejected == [None]
            assert source.closed, "a Monitor cleanup allocation failure abandoned its owned source"
            assert log.closed, "a Runtime cleanup allocation failure abandoned its owned log"
            assert listener.closed and not lease.held
        finally:
            stop.set()
            await asyncio.gather(running, return_exceptions=True)
            await asyncio.gather(runtime.close(), service.close(), return_exceptions=True)
            # Test hygiene after the expected production leak: do not leave a
            # cooperative port task for asyncio.run's implicit global cleanup.
            await log.close()
            if not source.closed:
                await source.close()
            if lease.held:
                lease.release()

    asyncio.run(scenario())
