"""Docker command ownership survives refused asyncio bookkeeping allocation.

Only allocation and the subprocess creation port are replaced. Task scheduling,
bounded readers, cancellation, cleanup, and the next sample use the adapter.
"""

import asyncio
import sys

import pytest

from joi_observer.collectors.docker import CommandOutput, DockerOutputLimitError, LocalDockerCommand
from test_docker_command import ARGV, OfflineProcess, replace_process_creation, wait_for_spawn


pytestmark = pytest.mark.usefixtures("no_live_docker_io")


@pytest.mark.parametrize("point", ["owner", "spawn", "first-reader", "second-reader", "wait"])
def test_refused_task_closes_input_and_settles_previously_owned_work(monkeypatch, point):
    async def scenario():
        first = OfflineProcess()
        second = OfflineProcess(stdout=b"next sample", returncode=0)
        selected = first
        processes, created, rejected = [], [], []
        real_task = asyncio.create_task
        error = MemoryError("injected Docker task allocation")
        readers = 0

        async def create_process(*args, **kwargs):
            processes.append(selected)
            return selected

        def allocate(coroutine, *args, **kwargs):
            nonlocal readers
            name = coroutine.cr_code.co_qualname
            if name == "LocalDockerCommand._read_bounded":
                readers += 1
            refuse = (
                point == "owner" and name == "LocalDockerCommand._execute"
                or point == "spawn" and name.endswith("scenario.<locals>.create_process")
                or point == "first-reader" and name == "LocalDockerCommand._read_bounded" and readers == 1
                or point == "second-reader" and name == "LocalDockerCommand._read_bounded" and readers == 2
                or point == "wait" and name == "OfflineProcess.wait"
            )
            if refuse and not rejected:
                rejected.append(coroutine)
                raise error
            task = real_task(coroutine, *args, **kwargs)
            created.append(task)
            return task

        monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
        monkeypatch.setattr(asyncio, "create_task", allocate)
        command = LocalDockerCommand()
        before = asyncio.all_tasks()
        try:
            with pytest.raises(MemoryError) as caught:
                async with asyncio.timeout(1):
                    await command.run(ARGV, timeout=0.5)
            assert caught.value is error
            assert len(rejected) == 1 and rejected[0].cr_frame is None
            assert all(task.done() for task in created)
            if processes:
                assert processes == [first]
                assert first.kill_calls == 1 and first.reaped
            else:
                assert point in {"owner", "spawn"}
            assert not (asyncio.all_tasks() - before)

            # Refused bookkeeping is a failed sample, not permanent closure.
            selected = second
            assert await command.run(ARGV, timeout=0.5) == CommandOutput(0, b"next sample")
            assert processes[-1] is second and second.reaped and second.kill_calls == 0
            await command.close()
            await command.close()
            assert all(task.done() for task in created)
            assert not (asyncio.all_tasks() - before)
        finally:
            # Keep a red baseline offline and avoid leaking its refused input.
            for coroutine in rejected:
                coroutine.close()
            for process in processes:
                if process.returncode is None:
                    process.finish(-9)
            for task in created:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*created, return_exceptions=True)
            await command.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("trigger", ["cancel", "close"])
@pytest.mark.parametrize("persistent", [False, True], ids=["once", "every-shield"])
def test_settle_wait_allocation_failure_joins_before_preserving_outcome(monkeypatch, trigger, persistent):
    async def scenario():
        class DelayedReapProcess(OfflineProcess):
            def kill(self):
                self.kill_calls += 1
                self.killed.set()
                asyncio.get_running_loop().call_later(0.01, self.finish, -9)

        process = DelayedReapProcess()
        _, spawned = replace_process_creation(monkeypatch, process)
        command = LocalDockerCommand()
        before = asyncio.all_tasks()
        running = asyncio.create_task(command.run(ARGV, timeout=2))
        original_shield = asyncio.shield
        refused = []
        error = MemoryError("injected Docker settle wait allocation")

        def shield(awaitable):
            if (sys._getframe(1).f_code.co_name == "_settle"
                    and (persistent or not refused)):
                refused.append(awaitable)
                raise error
            return original_shield(awaitable)

        try:
            await wait_for_spawn(spawned, running)
            monkeypatch.setattr(asyncio, "shield", shield)
            if trigger == "cancel":
                running.cancel()
                with pytest.raises(asyncio.CancelledError):
                    async with asyncio.timeout(1):
                        await running
            else:
                with pytest.raises(MemoryError) as caught:
                    async with asyncio.timeout(1):
                        await command.close()
                assert caught.value is error
                with pytest.raises(asyncio.CancelledError):
                    await running
            assert refused
            assert process.kill_calls == 1 and process.reaped
            assert running.done()
            assert not (asyncio.all_tasks() - before)
            await command.close()
            await command.close()
        finally:
            monkeypatch.setattr(asyncio, "shield", original_shield)
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
            await command.close()

    asyncio.run(scenario())


def test_refused_cleanup_retry_task_closes_input_and_finishes_cleanup_inline(monkeypatch):
    async def scenario():
        process = OfflineProcess(stdout=b"x" * 65537)

        class RetryablePipe:
            def __init__(self):
                self.calls = 0
                self.closed = False

            def close(self):
                self.calls += 1
                if self.calls == 1:
                    raise TimeoutError("offline first cleanup failure")
                self.closed = True
                process.stdout.feed_eof()

        pipe = RetryablePipe()
        process.stdout.set_transport(pipe)
        replace_process_creation(monkeypatch, process)
        real_task = asyncio.create_task
        rejected = []
        error = MemoryError("injected Docker cleanup retry allocation")

        def allocate(coroutine, *args, **kwargs):
            if coroutine.cr_code.co_qualname == "LocalDockerCommand._cleanup" and not rejected:
                rejected.append(coroutine)
                raise error
            return real_task(coroutine, *args, **kwargs)

        command = LocalDockerCommand()
        before = asyncio.all_tasks()
        try:
            with pytest.raises(DockerOutputLimitError):
                await command.run(ARGV, timeout=0.5)
            assert pipe.calls == 1 and not pipe.closed
            monkeypatch.setattr(asyncio, "create_task", allocate)
            with pytest.raises(MemoryError) as caught:
                async with asyncio.timeout(1):
                    await command.close()
            assert caught.value is error
            assert len(rejected) == 1 and rejected[0].cr_frame is None
            assert pipe.calls == 2 and pipe.closed
            assert process.kill_calls == 1 and process.reaped
            assert not (asyncio.all_tasks() - before)
            await command.close()
            await command.close()
            assert pipe.calls == 2
        finally:
            for coroutine in rejected:
                coroutine.close()
            await command.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("point", ["cleanup-task", "completion-future"])
def test_refused_inline_cleanup_stays_owned_through_cancel_and_concurrent_close(monkeypatch, point):
    async def scenario():
        reaping, release = asyncio.Event(), asyncio.Event()
        retrying = False

        class PausedRetryProcess(OfflineProcess):
            async def wait(self):
                if retrying:
                    reaping.set()
                    await release.wait()
                return await super().wait()

        process = PausedRetryProcess(stdout=b"x" * 65537)

        class RetryablePipe:
            def __init__(self):
                self.calls = 0

            def close(self):
                self.calls += 1
                if self.calls == 1:
                    raise TimeoutError("offline initial cleanup failure")
                process.stdout.feed_eof()

        pipe = RetryablePipe()
        process.stdout.set_transport(pipe)
        replace_process_creation(monkeypatch, process)
        real_task = asyncio.create_task
        loop = asyncio.get_running_loop()
        real_future = loop.create_future
        rejected, closing = [], []
        error = MemoryError("injected concurrent Docker cleanup owner allocation")

        def allocate(coroutine, *args, **kwargs):
            if (point == "cleanup-task"
                    and coroutine.cr_code.co_qualname == "LocalDockerCommand._cleanup" and not rejected):
                rejected.append(coroutine)
                raise error
            return real_task(coroutine, *args, **kwargs)

        def create_future():
            caller = sys._getframe(1)
            if (point == "completion-future" and not rejected
                    and caller.f_code.co_name == "run_cleanup"
                    and caller.f_back.f_code.co_qualname == "LocalDockerCommand.close"):
                rejected.append(None)
                raise error
            return real_future()

        command = LocalDockerCommand()
        before = asyncio.all_tasks()
        try:
            with pytest.raises(DockerOutputLimitError):
                await command.run(ARGV, timeout=0.5)
            assert pipe.calls == 1 and not process.reaped
            retrying = True
            monkeypatch.setattr(asyncio, "create_task", allocate)
            monkeypatch.setattr(loop, "create_future", create_future)
            first = real_task(command.close())
            closing.append(first)
            async with asyncio.timeout(1):
                await reaping.wait()
            second = real_task(command.close())
            closing.append(second)
            await asyncio.sleep(0)
            first.cancel()
            for _ in range(4):
                await asyncio.sleep(0)
            assert not first.done(), "inline cleanup returned before its owned reap finished"
            assert not second.done(), "concurrent close lost its shared cleanup completion"
            assert pipe.calls == 2 and not process.reaped
            release.set()
            async with asyncio.timeout(1):
                results = await asyncio.gather(*closing, return_exceptions=True)
            assert results == [error, None]
            assert rejected and all(coroutine is None or coroutine.cr_frame is None for coroutine in rejected)
            assert pipe.calls == 2 and process.kill_calls == 1 and process.reaped
            assert not (asyncio.all_tasks() - before)
            await command.close()
            assert pipe.calls == 2
        finally:
            release.set()
            for task in closing:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*closing, return_exceptions=True)
            for coroutine in rejected:
                if coroutine is not None:
                    coroutine.close()
            await command.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("persistent", [False, True], ids=["owner-only", "owner-and-settle"])
def test_owner_wait_allocation_failure_preserves_original_and_allows_next_sample(monkeypatch, persistent):
    async def scenario():
        process = OfflineProcess(stdout=b"next sample", returncode=0)
        calls, _ = replace_process_creation(monkeypatch, process)
        real_task, real_shield = asyncio.create_task, asyncio.shield
        owners, rejected = [], []
        original_error = MemoryError("injected first Docker owner wait allocation")
        secondary_error = MemoryError("injected later Docker settle allocation")

        def allocate(coroutine, *args, **kwargs):
            task = real_task(coroutine, *args, **kwargs)
            if coroutine.cr_code.co_qualname == "LocalDockerCommand._execute":
                owners.append(task)
            return task

        def shield(awaitable):
            if awaitable in owners and (persistent or not rejected):
                error = original_error if not rejected else secondary_error
                rejected.append(awaitable)
                raise error
            return real_shield(awaitable)

        monkeypatch.setattr(asyncio, "create_task", allocate)
        monkeypatch.setattr(asyncio, "shield", shield)
        command = LocalDockerCommand()
        before = asyncio.all_tasks()
        try:
            with pytest.raises(MemoryError) as caught:
                async with asyncio.timeout(1):
                    await command.run(ARGV, timeout=0.5)
            assert caught.value is original_error
            assert rejected and owners and all(task.done() for task in owners)
            assert calls == []
            assert not (asyncio.all_tasks() - before)
            monkeypatch.setattr(asyncio, "shield", real_shield)
            assert await command.run(ARGV, timeout=0.5) == CommandOutput(0, b"next sample")
            assert len(calls) == 1 and process.reaped and process.kill_calls == 0
            await command.close()
            assert not (asyncio.all_tasks() - before)
        finally:
            monkeypatch.setattr(asyncio, "shield", real_shield)
            for task in owners:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*owners, return_exceptions=True)
            await command.close()

    asyncio.run(scenario())


def test_inline_cleanup_external_cancel_cannot_postpone_its_deadline(monkeypatch, record_testsuite_property):
    async def scenario():
        reaping, release = asyncio.Event(), asyncio.Event()
        retrying = False

        class PausedRetryProcess(OfflineProcess):
            async def wait(self):
                if retrying:
                    reaping.set()
                    await release.wait()
                return await super().wait()

        process = PausedRetryProcess(stdout=b"x" * 65537)

        class RetryablePipe:
            def __init__(self):
                self.calls = 0

            def close(self):
                self.calls += 1
                if self.calls == 1:
                    raise TimeoutError("offline initial cleanup failure")
                process.stdout.feed_eof()

        process.stdout.set_transport(RetryablePipe())
        replace_process_creation(monkeypatch, process)
        real_task = asyncio.create_task
        rejected = []
        error = MemoryError("injected bounded Docker inline cleanup allocation")

        def allocate(coroutine, *args, **kwargs):
            if coroutine.cr_code.co_qualname == "LocalDockerCommand._cleanup" and not rejected:
                rejected.append(coroutine)
                raise error
            return real_task(coroutine, *args, **kwargs)

        command = LocalDockerCommand()
        before = asyncio.all_tasks()
        closing = None
        try:
            with pytest.raises(DockerOutputLimitError):
                await command.run(ARGV, timeout=0.5)
            retrying = True
            monkeypatch.setattr(asyncio, "create_task", allocate)
            closing = real_task(command.close())
            async with asyncio.timeout(0.5):
                await reaping.wait()
                started = asyncio.get_running_loop().time()
                for _ in range(6):
                    closing.cancel()
                    await asyncio.sleep(0.015)
                with pytest.raises(MemoryError) as caught:
                    await closing
            elapsed = asyncio.get_running_loop().time() - started
            record_testsuite_property("docker_inline_cleanup_seconds", elapsed)
            assert caught.value is error
            # The production deadline remains 250ms. This small scheduling
            # allowance detects swallowing/restarting it without a tight CI race.
            assert 0.20 <= elapsed < 0.35
            assert rejected and rejected[0].cr_frame is None
            assert not process.reaped
            # An expired attempt retains actual resources for a later close.
            release.set()
            await command.close()
            assert process.kill_calls == 1 and process.reaped
            assert not (asyncio.all_tasks() - before)
            await command.close()
        finally:
            release.set()
            if closing is not None:
                closing.cancel()
                await asyncio.gather(closing, return_exceptions=True)
            for coroutine in rejected:
                coroutine.close()
            await command.close()

    asyncio.run(scenario())
