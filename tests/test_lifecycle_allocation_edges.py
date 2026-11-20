"""Resource and cleanup ownership survives one refused bookkeeping allocation."""

import asyncio
import gc
from io import StringIO
import sys
from types import SimpleNamespace
import warnings

import pytest

from joi_observer._shutdown import run_cleanup, spawn
from joi_observer.config import AppConfig
from joi_observer.cli import CommandDependencies, run_command
from joi_observer.data.state import MonitorState
from joi_observer.monitor import Monitor
from joi_observer.runtime import CollectorRuntime
from joi_observer.service import CollectorService
from test_hardware_monitor import OfflineCollector, OfflineDiscovery, gpu_spec
from test_service_contract import MemoryLease, MemoryListener, MemoryLog, SampleSource, runtime_fixture, until
from test_service_outcome_edges import service_for


def setup_service(tmp_path):
    runtime, source, log = runtime_fixture(AppConfig(sample_interval=0.02, mount_points=()))
    service, listener, lease = service_for(tmp_path, runtime)
    return service, runtime, source, log, listener, lease


def assert_no_unawaited(recorded):
    gc.collect()
    assert not [entry for entry in recorded if "was never awaited" in str(entry.message)]


def test_spawn_closes_rejected_coroutine_without_allocator_help(monkeypatch):
    async def scenario():
        async def operation():
            await asyncio.sleep(0)

        def reject(coroutine, *args, **kwargs):
            raise MemoryError("refused ordinary Task allocator")

        pending = operation()
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always", RuntimeWarning)
            monkeypatch.setattr(asyncio, "create_task", reject)
            with pytest.raises(MemoryError, match="ordinary Task allocator"):
                spawn(pending)
            assert pending.cr_frame is None
            del pending
            assert_no_unawaited(recorded)
    asyncio.run(scenario())


@pytest.mark.parametrize("name", ["collector-runtime", "collector-publisher"])
def test_service_start_allocation_failure_does_not_leak_nested_coroutines(tmp_path, monkeypatch, name):
    async def scenario():
        service, runtime, source, log, listener, lease = setup_service(tmp_path)
        original = asyncio.create_task
        rejected = []

        def allocate(coroutine, *args, **kwargs):
            if kwargs.get("name") == name and not rejected:
                rejected.append(coroutine.cr_code.co_qualname)
                # Product code, rather than this allocator, must close it.
                raise MemoryError("refused service startup Task")
            return original(coroutine, *args, **kwargs)

        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always", RuntimeWarning)
            monkeypatch.setattr(asyncio, "create_task", allocate)
            try:
                with pytest.raises(MemoryError, match="service startup Task"):
                    await service.run(asyncio.Event())
                assert len(rejected) == 1
                assert source.closed and log.closed and listener.closed and not lease.held
            finally:
                await asyncio.gather(service.close(), runtime.close(), return_exceptions=True)
            assert_no_unawaited(recorded)
    asyncio.run(scenario())


@pytest.mark.parametrize("operation", [
    "CollectorService._cleanup", "CollectorRuntime._cleanup", "Monitor._cleanup",
])
def test_cleanup_owner_task_rejection_runs_real_cleanup_inline(tmp_path, monkeypatch, operation):
    async def scenario():
        service, runtime, source, log, listener, lease = setup_service(tmp_path)
        stop = asyncio.Event()
        running = asyncio.create_task(service.run(stop))
        original = asyncio.create_task
        rejected = []

        def allocate(coroutine, *args, **kwargs):
            if coroutine.cr_code.co_qualname == operation and not rejected:
                rejected.append(None)
                raise MemoryError("refused owned cleanup Task")
            return original(coroutine, *args, **kwargs)

        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always", RuntimeWarning)
            try:
                await until(lambda: source.calls >= 2, running)
                monkeypatch.setattr(asyncio, "create_task", allocate)
                stop.set()
                with pytest.raises(MemoryError, match="owned cleanup Task"):
                    await asyncio.wait_for(running, 1.2)
                assert rejected == [None]
                assert source.closed and log.closed and listener.closed and not lease.held
                await service.close()
            finally:
                stop.set()
                await asyncio.gather(running, return_exceptions=True)
                await asyncio.gather(service.close(), runtime.close(), return_exceptions=True)
            assert_no_unawaited(recorded)
    asyncio.run(scenario())


@pytest.mark.parametrize("operation", [
    "CollectorService.close", "CollectorRuntime.close", "Monitor.stop",
])
def test_cleanup_completion_future_rejection_still_closes_resources(tmp_path, monkeypatch, operation):
    async def scenario():
        service, runtime, source, log, listener, lease = setup_service(tmp_path)
        stop = asyncio.Event()
        running = asyncio.create_task(service.run(stop))
        loop = asyncio.get_running_loop()
        original = loop.create_future
        rejected = []

        def allocate():
            caller = sys._getframe(1)
            if (caller.f_code.co_name == "run_cleanup"
                    and caller.f_back.f_code.co_qualname == operation and not rejected):
                rejected.append(None)
                raise MemoryError("refused cleanup completion Future")
            return original()

        try:
            await until(lambda: source.calls >= 2, running)
            monkeypatch.setattr(loop, "create_future", allocate)
            stop.set()
            with pytest.raises(MemoryError, match="cleanup completion Future"):
                await asyncio.wait_for(running, 1.2)
            assert rejected == [None]
            assert source.closed and log.closed and listener.closed and not lease.held
            await service.close()
        finally:
            stop.set()
            await asyncio.gather(running, return_exceptions=True)
            await asyncio.gather(service.close(), runtime.close(), return_exceptions=True)
    asyncio.run(scenario())


def test_inline_future_fallback_is_joined_by_concurrent_close_even_if_caller_is_cancelled(tmp_path, monkeypatch):
    async def scenario():
        service, runtime, source, log, listener, lease = setup_service(tmp_path)
        stop = asyncio.Event()
        running = asyncio.create_task(service.run(stop))
        source_closing, release_source = asyncio.Event(), asyncio.Event()
        closed_with_lease = []

        async def close_source():
            source_closing.set()
            try:
                await release_source.wait()
            finally:
                closed_with_lease.append(lease.held)
                source.closed = True

        source.close = close_source
        loop = asyncio.get_running_loop()
        original = loop.create_future
        rejected = []

        def allocate():
            caller = sys._getframe(1)
            if (caller.f_code.co_name == "run_cleanup"
                    and caller.f_back.f_code.co_qualname == "CollectorService.close" and not rejected):
                rejected.append(None)
                raise MemoryError("refused concurrent completion Future")
            return original()

        first = second = None
        try:
            await until(lambda: source.calls >= 2, running)
            monkeypatch.setattr(loop, "create_future", allocate)
            first = asyncio.create_task(service.close())
            await asyncio.wait_for(source_closing.wait(), 0.5)
            second = asyncio.create_task(service.close())
            first.cancel()
            await asyncio.sleep(0)
            assert not first.done() and not second.done() and lease.held
            release_source.set()
            with pytest.raises(MemoryError, match="concurrent completion Future"):
                await asyncio.wait_for(first, 1.2)
            await asyncio.wait_for(second, 1.2)
            await asyncio.wait_for(running, 1.2)
            assert closed_with_lease == [True]
            assert source.closed and log.closed and listener.closed and not lease.held
            await service.close()
        finally:
            release_source.set()
            stop.set()
            jobs = [job for job in (running, first, second) if job is not None]
            await asyncio.gather(*jobs, return_exceptions=True)
            await asyncio.gather(service.close(), runtime.close(), return_exceptions=True)
    asyncio.run(scenario())


def test_shield_future_rejection_still_joins_owned_cleanup_before_reporting_error(tmp_path, monkeypatch):
    async def scenario():
        service, runtime, source, log, listener, lease = setup_service(tmp_path)
        stop = asyncio.Event()
        running = asyncio.create_task(service.run(stop))
        source_closing, release_source = asyncio.Event(), asyncio.Event()
        held_at_source_exit = []

        async def close_source():
            source_closing.set()
            try:
                await release_source.wait()
            finally:
                held_at_source_exit.append(lease.held)
                source.closed = True

        source.close = close_source
        loop = asyncio.get_running_loop()
        original = loop.create_future
        rejected = []

        def allocate():
            if (sys._getframe(1).f_code.co_name == "shield"
                    and asyncio.current_task().get_name() == "shield-allocation-waiter" and not rejected):
                rejected.append(None)
                raise MemoryError("refused shield bookkeeping Future")
            return original()

        closing = None
        try:
            await until(lambda: source.calls >= 2, running)
            monkeypatch.setattr(loop, "create_future", allocate)
            closing = asyncio.create_task(service.close(), name="shield-allocation-waiter")
            await asyncio.wait_for(source_closing.wait(), 0.5)
            assert rejected == [None] and lease.held and not closing.done()
            release_source.set()
            with pytest.raises(MemoryError, match="shield bookkeeping Future"):
                await asyncio.wait_for(closing, 1.2)
            await asyncio.wait_for(running, 1.2)
            assert held_at_source_exit == [True]
            assert source.closed and log.closed and listener.closed and not lease.held
        finally:
            release_source.set()
            stop.set()
            jobs = [job for job in (running, closing) if job is not None]
            await asyncio.gather(*jobs, return_exceptions=True)
            await asyncio.gather(service.close(), runtime.close(), return_exceptions=True)
    asyncio.run(scenario())


def test_gather_allocation_rejection_cannot_detach_previously_registered_cleanup(tmp_path, monkeypatch):
    async def scenario():
        service, runtime, source, log, listener, lease = setup_service(tmp_path)
        stop = asyncio.Event()
        running = asyncio.create_task(service.run(stop))
        source_closing, release_source = asyncio.Event(), asyncio.Event()
        held_at_source_exit = []

        async def close_source():
            source_closing.set()
            try:
                await release_source.wait()
            finally:
                held_at_source_exit.append(lease.held)
                source.closed = True

        source.close = close_source
        original = asyncio.gather
        rejected = []

        def allocate(*args, **kwargs):
            if (sys._getframe(1).f_code.co_name == "join_tasks"
                    and asyncio.current_task().get_name() == "collector-cleanup" and not rejected):
                rejected.append(None)
                raise MemoryError("refused registered-work gather")
            return original(*args, **kwargs)

        try:
            await until(lambda: source.calls >= 2, running)
            monkeypatch.setattr(asyncio, "gather", allocate)
            stop.set()
            await asyncio.wait_for(source_closing.wait(), 0.5)
            assert rejected == [None] and lease.held and not running.done()
            release_source.set()
            with pytest.raises(MemoryError, match="registered-work gather"):
                await asyncio.wait_for(running, 1.2)
            assert held_at_source_exit == [True]
            assert source.closed and log.closed and listener.closed and not lease.held
        finally:
            release_source.set()
            stop.set()
            await asyncio.gather(running, return_exceptions=True)
            await asyncio.gather(service.close(), runtime.close(), return_exceptions=True)
    asyncio.run(scenario())


def test_retirement_allocation_failure_keeps_all_rejected_factory_children_owned(monkeypatch):
    async def scenario():
        specs = tuple(gpu_spec(f"GPU-{index}") for index in range(3))
        discovery = OfflineDiscovery(specs)

        def factory(spec):
            if spec == specs[-1]:
                raise OSError("offline discovery factory failure")
            return OfflineCollector(spec)

        discovery.factory = factory
        state = MonitorState(())
        monitor = Monitor((), state, MemoryLog(), interval=0.02)
        monitor.register_discovery(discovery)
        original = asyncio.create_task
        rejected = []

        def allocate(coroutine, *args, **kwargs):
            if coroutine.cr_code.co_qualname == "Monitor._close_source" and not rejected:
                rejected.append(None)
                raise MemoryError("refused rejected-source retirement Task")
            return original(coroutine, *args, **kwargs)

        monkeypatch.setattr(asyncio, "create_task", allocate)
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always", RuntimeWarning)
            try:
                with pytest.raises(MemoryError, match="retirement Task"):
                    await asyncio.wait_for(monitor.run(asyncio.Event()), 1.2)
                assert rejected == [None] and discovery.closed
                assert len(discovery.created) == 2
                assert all(child.closed and child.calls == 0 for child in discovery.created)
                assert [obj.key for obj in state.snapshot().objects] == [discovery.spec.key]
            finally:
                await monitor.stop()
            assert_no_unawaited(recorded)
    asyncio.run(scenario())


def install_callback_refusal(loop, rejected):
    previous = loop.get_task_factory()

    class RefusingTask(asyncio.Task):
        def add_done_callback(self, callback, *, context=None):
            if (getattr(callback, "__qualname__", "") == "run_cleanup.<locals>.settled"
                    and not rejected):
                rejected.append(None)
                raise MemoryError("refused cleanup completion callback")
            return super().add_done_callback(callback, context=context)

    loop.set_task_factory(lambda loop, coroutine, context=None:
                          RefusingTask(coroutine, loop=loop, context=context))
    return previous


def test_cleanup_callback_refusal_joins_real_owner_and_completes_placeholder():
    async def scenario():
        loop = asyncio.get_running_loop()
        rejected, published, closed = [], [], []
        entered, release = asyncio.Event(), asyncio.Event()

        async def cleanup():
            entered.set()
            await release.wait()
            closed.append(True)

        previous = install_callback_refusal(loop, rejected)
        running = asyncio.create_task(run_cleanup(cleanup, publish=published.append))
        try:
            await asyncio.wait_for(entered.wait(), 0.5)
            assert rejected == [None] and not running.done() and closed == []
            assert len(published) == 2 and not published[0].done()
            release.set()
            with pytest.raises(MemoryError, match="completion callback"):
                await asyncio.wait_for(running, 0.5)
            assert closed == [True] and all(owner.done() for owner in published)
            assert published[0].result() is None
        finally:
            loop.set_task_factory(previous)
            release.set()
            await asyncio.gather(running, return_exceptions=True)
    asyncio.run(scenario())


def test_public_client_callback_refusal_closes_stream_before_returning_error():
    from joi_observer.ipc.client import ConnectionState, SnapshotClient
    from test_ipc_client import MemoryConnector, MemoryStream, frame

    async def scenario():
        stream = MemoryStream(frame())
        client = SnapshotClient(connector=MemoryConnector(stream))
        await client.connect()
        loop = asyncio.get_running_loop()
        rejected = []
        previous = install_callback_refusal(loop, rejected)
        try:
            with pytest.raises(MemoryError, match="completion callback"):
                await client.close()
            assert rejected == [None] and stream.closed
            assert client.state is ConnectionState.CLOSED and client._close_task.done()
            await client.close()
        finally:
            loop.set_task_factory(previous)
            await client.close()
    asyncio.run(scenario())


def reject_cleanup_owner(monkeypatch, selected):
    original = asyncio.create_task
    rejected = []

    def allocate(coroutine, *args, **kwargs):
        if kwargs.get("name") == selected and not rejected:
            rejected.append(None)
            raise MemoryError("secondary cleanup owner allocation failure")
        return original(coroutine, *args, **kwargs)

    monkeypatch.setattr(asyncio, "create_task", allocate)
    return rejected


def test_formal_config_error_keeps_exit_two_when_cleanup_owner_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("sample_interval: true\n", encoding="utf-8")
    lease, calls = MemoryLease(), []

    def forbidden_runtime(config):
        calls.append(config)
        pytest.fail("Invalid configuration must not construct a runtime")

    service = CollectorService(path, runtime_factory=forbidden_runtime, lease=lease)
    stdout, stderr = StringIO(), StringIO()
    dependencies = CommandDependencies(tmp_path, tmp_path, False, False, "dumb", stdout, stderr,
                                       lambda endpoint: pytest.fail("Service cannot construct a TUI"),
                                       lambda config, endpoint: service)
    rejected = reject_cleanup_owner(monkeypatch, "collector-service-close")
    assert run_command(["service", "--config", str(path)], dependencies=dependencies) == 2
    assert rejected == [None] and calls == [] and not lease.held
    assert stdout.getvalue() == "" and "sample_interval" in stderr.getvalue()
    assert "secondary cleanup" not in stderr.getvalue()


@pytest.mark.parametrize("owner", ["snapshot-publisher-close", "collector-service-close"])
def test_formal_start_error_keeps_exit_five_when_cleanup_owner_is_refused(tmp_path, monkeypatch, owner):
    class RefusingListener(MemoryListener):
        async def start(self):
            raise OSError("private primary bind failure")

    runtime, source, log = runtime_fixture(AppConfig(sample_interval=1, mount_points=()))
    path = tmp_path / "config.yaml"
    path.write_text("mount_points: []\nsample_interval: 1\n", encoding="utf-8")
    listener, lease = RefusingListener(), MemoryLease()
    service = CollectorService(path, runtime_factory=lambda config: runtime,
                               listener=listener, lease=lease,
                               host_factory=lambda: ("Host", "Ubuntu 24.04"))
    stdout, stderr = StringIO(), StringIO()
    dependencies = CommandDependencies(tmp_path, tmp_path, False, False, "dumb", stdout, stderr,
                                       lambda endpoint: pytest.fail("Service cannot construct a TUI"),
                                       lambda config, endpoint: service)
    rejected = reject_cleanup_owner(monkeypatch, owner)
    assert run_command(["service", "--config", str(path)], dependencies=dependencies) == 5
    assert rejected == [None] and source.calls == 0
    assert source.closed and log.closed and listener.closed and not lease.held
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "Collector service could not start.\n"


@pytest.mark.parametrize("layer", ["runtime", "service"])
def test_early_factory_error_is_not_replaced_by_cleanup_allocation(tmp_path, monkeypatch, layer):
    async def scenario():
        primary = RuntimeError("primary factory failure")
        resources = []
        lease = None
        if layer == "runtime":
            source, discovery = SampleSource(), OfflineDiscovery()
            resources.extend((source, discovery))
            monkeypatch.setattr("joi_observer.runtime.build_hardware_sources",
                                lambda config: SimpleNamespace(collectors=(source,), discovery=discovery))

            def fail_factory(*args, **kwargs):
                raise primary

            monkeypatch.setattr("joi_observer.runtime.build_docker_collectors", fail_factory)
            owner = CollectorRuntime(AppConfig(mount_points=()))
            rejected = reject_cleanup_owner(monkeypatch, "collector-cleanup")
        else:
            path = tmp_path / "config.yaml"
            path.write_text("mount_points: []\nsample_interval: 1\n", encoding="utf-8")
            lease = MemoryLease()

            def fail_factory(config):
                raise primary

            owner = CollectorService(path, runtime_factory=fail_factory, lease=lease)
            rejected = reject_cleanup_owner(monkeypatch, "collector-service-close")
        try:
            with pytest.raises(RuntimeError, match="primary factory failure") as caught:
                await owner.run(asyncio.Event())
            assert caught.value is primary and rejected == [None]
            assert all(resource.closed for resource in resources)
            if lease is not None:
                assert not lease.held
        finally:
            await owner.close()
    asyncio.run(scenario())
