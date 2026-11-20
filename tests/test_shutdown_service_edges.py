"""Service shutdown ownership and deadline isolation using only memory ports."""

import asyncio

import pytest

from joi_observer.config import AppConfig
from joi_observer.service import CollectorService
from test_service_contract import (
    MemoryLease, MemoryListener, MemoryPeer, runtime_fixture, until,
)


def write_config(path):
    path.write_text("mount_points: []\nsample_interval: 1\n", encoding="utf-8")
    return path


def test_publication_failure_does_not_expire_later_service_shutdown_budget(tmp_path):
    path = write_config(tmp_path / "config.yaml")

    async def scenario():
        runtime, source, log = runtime_fixture(AppConfig(sample_interval=1, mount_points=()))
        closed_normally = asyncio.Event()

        async def close_source():
            try:
                await asyncio.sleep(0.08)
                closed_normally.set()
            finally:
                source.closed = True

        source.close = close_source
        listener, peer, lease = MemoryListener(), MemoryPeer(), MemoryLease()
        await listener.peers.put(peer)
        warnings = []
        service = CollectorService(path, runtime_factory=lambda config: runtime,
                                   listener=listener, lease=lease,
                                   host_factory=lambda: ("Host", "Ubuntu 24.04"),
                                   on_warning=warnings.append)
        stop = asyncio.Event()
        running = asyncio.create_task(service.run(stop))
        try:
            await until(lambda: bool(peer.frames), running)
            await listener.peers.put(OSError("offline publication failure"))
            await until(lambda: listener.closed and peer.closed, running)
            previous_samples = source.calls
            accepts = listener.accept_calls
            await asyncio.sleep(1.05)
            assert lease.held and not running.done() and not log.closed
            assert source.calls > previous_samples
            assert listener.accept_calls == accepts
            assert warnings == ["Snapshot publishing stopped; collection continues. Restart collector service to restore access."]

            started = asyncio.get_running_loop().time()
            stop.set()
            await asyncio.wait_for(running, 1.15)
            assert asyncio.get_running_loop().time() - started < 1.1
            # A close within a fresh budget must not inherit the old isolated
            # publisher failure's already expired shutdown deadline.
            assert closed_normally.is_set() and source.closed and log.closed
            assert not lease.held
        finally:
            stop.set()
            await asyncio.gather(running, return_exceptions=True)
            await runtime.close()
            await service.close()
    asyncio.run(scenario())


def test_partial_start_close_keeps_lease_through_delayed_source_finally(tmp_path):
    path = write_config(tmp_path / "config.yaml")

    async def scenario():
        finish_start, release_source = asyncio.Event(), asyncio.Event()
        source_closing, source_finalized = asyncio.Event(), asyncio.Event()
        runtime, source, log = runtime_fixture(AppConfig(sample_interval=1, mount_points=()))
        lease = MemoryLease()
        held_during_finally = []

        async def close_source():
            source_closing.set()
            try:
                await release_source.wait()
            finally:
                held_during_finally.append(lease.held)
                await asyncio.sleep(0.02)
                held_during_finally.append(lease.held)
                source.closed = True
                source_finalized.set()

        source.close = close_source

        class SlowStartingListener(MemoryListener):
            async def start(self):
                self.start_calls += 1
                self.started.set()
                await finish_start.wait()

            async def close(self):
                await asyncio.sleep(0.07)
                self.closed = True
                finish_start.set()

        listener = SlowStartingListener()
        service = CollectorService(path, runtime_factory=lambda config: runtime,
                                   listener=listener, lease=lease,
                                   host_factory=lambda: ("Host", "Ubuntu 24.04"))
        running = asyncio.create_task(service.run(asyncio.Event()))
        closing = None
        try:
            await asyncio.wait_for(listener.started.wait(), 0.5)
            started = asyncio.get_running_loop().time()
            closing = asyncio.create_task(service.close())
            await asyncio.wait_for(source_closing.wait(), 0.5)
            await asyncio.wait_for(closing, 1.15)
            assert asyncio.get_running_loop().time() - started < 1.1
            assert source.calls == 0 and listener.closed and log.closed
            assert source_finalized.is_set() and source.closed
            assert held_during_finally == [True, True]
            assert not lease.held
        finally:
            release_source.set()
            finish_start.set()
            jobs = (running,) if closing is None else (running, closing)
            await asyncio.gather(*jobs, return_exceptions=True)
            await runtime.close()
            await service.close()
    asyncio.run(scenario())


def test_cancelled_close_waiter_does_not_release_lease_or_restart_cleanup(tmp_path):
    path = write_config(tmp_path / "config.yaml")

    async def scenario():
        release_source, source_closing = asyncio.Event(), asyncio.Event()
        runtime, source, log = runtime_fixture(AppConfig(sample_interval=1, mount_points=()))
        close_calls = 0
        lease = MemoryLease()
        held_at_source_exit = []

        async def close_source():
            nonlocal close_calls
            close_calls += 1
            source_closing.set()
            try:
                await release_source.wait()
            finally:
                held_at_source_exit.append(lease.held)
                source.closed = True

        source.close = close_source
        service = CollectorService(path, runtime_factory=lambda config: runtime,
                                   listener=MemoryListener(), lease=lease,
                                   host_factory=lambda: ("Host", "Ubuntu 24.04"))
        stop = asyncio.Event()
        running = asyncio.create_task(service.run(stop))
        first = second = None
        try:
            await until(lambda: source.calls >= 1, running)
            first = asyncio.create_task(service.close())
            await asyncio.wait_for(source_closing.wait(), 0.5)
            first.cancel()
            await asyncio.sleep(0)
            assert not first.done() and lease.held and not source.closed

            second = asyncio.create_task(service.close())
            await asyncio.sleep(0)
            assert lease.held and close_calls == 1
            release_source.set()
            await asyncio.wait_for(second, 0.5)
            result = await asyncio.gather(first, return_exceptions=True)
            assert isinstance(result[0], asyncio.CancelledError)
            assert source.closed and log.closed and not lease.held
            assert held_at_source_exit == [True] and close_calls == 1
        finally:
            release_source.set()
            stop.set()
            jobs = tuple(job for job in (running, first, second) if job is not None)
            await asyncio.gather(*jobs, return_exceptions=True)
            await runtime.close()
            await service.close()
    asyncio.run(scenario())


def test_independent_service_instances_have_separate_cleanup_deadlines(tmp_path):
    first_path = write_config(tmp_path / "first.yaml")
    second_path = write_config(tmp_path / "second.yaml")

    async def scenario():
        first_runtime, first_source, first_log = runtime_fixture(AppConfig(sample_interval=1, mount_points=()))
        second_runtime, second_source, second_log = runtime_fixture(AppConfig(sample_interval=1, mount_points=()))
        first_closing, release_first = asyncio.Event(), asyncio.Event()
        second_closed_normally = asyncio.Event()

        async def close_first():
            first_closing.set()
            try:
                await release_first.wait()
            finally:
                first_source.closed = True

        async def close_second():
            try:
                await asyncio.sleep(0.55)
                second_closed_normally.set()
            finally:
                second_source.closed = True

        first_source.close, second_source.close = close_first, close_second
        first_lease, second_lease = MemoryLease(), MemoryLease()
        first = CollectorService(first_path, runtime_factory=lambda config: first_runtime,
                                 listener=MemoryListener(), lease=first_lease,
                                 host_factory=lambda: ("Host", "Ubuntu 24.04"))
        second = CollectorService(second_path, runtime_factory=lambda config: second_runtime,
                                  listener=MemoryListener(), lease=second_lease,
                                  host_factory=lambda: ("Host", "Ubuntu 24.04"))
        first_stop, second_stop = asyncio.Event(), asyncio.Event()
        first_task = asyncio.create_task(first.run(first_stop))
        second_task = asyncio.create_task(second.run(second_stop))
        try:
            await until(lambda: first_source.calls >= 1, first_task)
            await until(lambda: second_source.calls >= 1, second_task)
            first_stop.set()
            await asyncio.wait_for(first_closing.wait(), 0.5)
            await asyncio.sleep(0.30)
            assert first_lease.held and second_lease.held
            second_stop.set()
            await asyncio.wait_for(second_task, 1.15)
            await asyncio.wait_for(first_task, 0.5)
            assert second_closed_normally.is_set()
            assert first_source.closed and second_source.closed
            assert first_log.closed and second_log.closed
            assert not first_lease.held and not second_lease.held
        finally:
            release_first.set()
            first_stop.set()
            second_stop.set()
            await asyncio.gather(first_task, second_task, return_exceptions=True)
            await first_runtime.close()
            await second_runtime.close()
            await first.close()
            await second.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("trigger", ["stop", "cancel", "close"])
def test_service_reaps_real_suspended_encoder_before_releasing_lease(tmp_path, monkeypatch, trigger):
    """Real sampling/encoding stays owned through every service exit route."""
    import os
    import signal

    async def scenario():
        runtime, source, log = runtime_fixture(AppConfig(sample_interval=0.02, mount_points=()))
        listener, peer, lease = MemoryListener(), MemoryPeer(), MemoryLease()
        listener.peers.put_nowait(peer)
        service = CollectorService(write_config(tmp_path / "config.yaml"),
                                   runtime_factory=lambda config: runtime,
                                   listener=listener, lease=lease,
                                   host_factory=lambda: ("Host", "Ubuntu 24.04"))
        real_spawn = asyncio.create_subprocess_exec
        children, lease_at_reap = [], []
        stopped = asyncio.Event()

        async def suspend_actual_encoder(*args, **kwargs):
            assert args[1:] == ("-m", "joi_observer.ipc._worker", "encode")
            child = await real_spawn(*args, **kwargs)
            children.append(child)
            # Input has not been sent yet, so the real encoder cannot finish
            # before suspension. No listening socket or server is involved.
            os.kill(child.pid, signal.SIGSTOP)
            wait = child.wait

            async def observe_reap():
                result = await wait()
                lease_at_reap.append(lease.held)
                return result

            child.wait = observe_reap
            stopped.set()
            return child

        monkeypatch.setattr(asyncio, "create_subprocess_exec", suspend_actual_encoder)
        stop = asyncio.Event()
        baseline = asyncio.all_tasks()
        running = asyncio.create_task(service.run(stop))
        try:
            await asyncio.wait_for(stopped.wait(), 3)
            # Real Monitor samples naturally crossed the small-codec history
            # threshold. The source and initial publications remain real.
            assert source.calls >= 9 and peer.frames and lease.held
            previous_calls = source.calls
            await until(lambda: source.calls > previous_calls, running)
            assert not running.done()
            began = asyncio.get_running_loop().time()
            if trigger == "stop":
                stop.set()
            elif trigger == "cancel":
                running.cancel()
            else:
                await asyncio.wait_for(service.close(), 1.2)
            result, = await asyncio.wait_for(asyncio.gather(running, return_exceptions=True), 1.2)
            if trigger == "cancel":
                assert isinstance(result, asyncio.CancelledError)
            else:
                assert result is None
            assert asyncio.get_running_loop().time() - began < 1.1
            assert len(children) == 1 and children[0].returncode == -signal.SIGKILL
            assert lease_at_reap and all(lease_at_reap)
            assert not lease.held and listener.closed and peer.closed
            assert source.closed and log.closed
            assert not (asyncio.all_tasks() - baseline)
        finally:
            # Even a failing regression must leave no stopped OS child behind.
            for child in children:
                if child.returncode is None:
                    child.kill()
                await child.wait()
            stop.set()
            if not running.done():
                running.cancel()
            await asyncio.gather(running, return_exceptions=True)
            await service.close()

    asyncio.run(scenario())
