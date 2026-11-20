"""Shutdown waiters cannot leave owned source or queued log work behind."""

import asyncio
import json

import pytest

from joi_observer.config import LogConfig
from joi_observer.error_log import ErrorLog
from test_error_log import GatedIO, record
from test_service_contract import runtime_fixture


def delayed_close(source):
    entered, release, finished = (asyncio.Event() for _ in range(3))
    calls = []

    async def close():
        calls.append(None)
        entered.set()
        try:
            await release.wait()
        finally:
            # Cooperative cancellation still needs an asynchronous finally.
            # Returning from the owner before this ends would release its
            # resource ownership while the source is still being cleaned up.
            await asyncio.sleep(0.02)
            source.closed = True
            finished.set()

    source.close = close
    return entered, release, finished, calls


def active_tasks_since(before):
    return [task for task in asyncio.all_tasks() if task not in before and not task.done()]


@pytest.mark.parametrize("sampling", [False, True])
def test_cancelled_runtime_close_waiter_and_second_close_settle_sources_once(sampling):
    async def scenario():
        before = asyncio.all_tasks()
        runtime, source, log = runtime_fixture()
        entered, release, finished, calls = delayed_close(source)
        running = None
        if sampling:
            running = asyncio.create_task(runtime.run(asyncio.Event()))

            async def sampled():
                while not source.calls:
                    await asyncio.sleep(0)

            await asyncio.wait_for(sampled(), 0.5)

        first = asyncio.create_task(runtime.close())
        second = None
        try:
            await asyncio.wait_for(entered.wait(), 0.5)
            first.cancel()
            second = asyncio.create_task(runtime.close())
            outcomes = await asyncio.wait_for(
                asyncio.gather(first, second, return_exceptions=True), 1.1,
            )
            assert isinstance(outcomes[0], asyncio.CancelledError)
            assert outcomes[1] is None
            assert finished.is_set() and source.closed and log.closed
            assert len(calls) == 1
            if running is not None:
                await asyncio.wait_for(asyncio.gather(running, return_exceptions=True), 0.1)
            await asyncio.sleep(0)
            assert not active_tasks_since(before)
        finally:
            release.set()
            await asyncio.gather(*(task for task in (first, second, running) if task is not None),
                                 return_exceptions=True)
            await runtime.close()

    asyncio.run(scenario())


def test_cancelled_monitor_stop_waiter_and_second_stop_settle_sources_once():
    async def scenario():
        before = asyncio.all_tasks()
        runtime, source, log = runtime_fixture()
        entered, release, finished, calls = delayed_close(source)
        monitor = runtime.components.monitor
        first = asyncio.create_task(monitor.stop())
        second = None
        try:
            await asyncio.wait_for(entered.wait(), 0.5)
            first.cancel()
            second = asyncio.create_task(monitor.stop())
            outcomes = await asyncio.wait_for(
                asyncio.gather(first, second, return_exceptions=True), 1.1,
            )
            assert isinstance(outcomes[0], asyncio.CancelledError)
            assert outcomes[1] is None
            assert finished.is_set() and source.closed and len(calls) == 1
            assert not log.closed  # Monitor does not own the runtime's log.
            await runtime.close()
            assert log.closed and len(calls) == 1
            await asyncio.sleep(0)
            assert not active_tasks_since(before)
        finally:
            release.set()
            await asyncio.gather(*(task for task in (first, second) if task is not None),
                                 return_exceptions=True)
            await runtime.close()

    asyncio.run(scenario())


def test_cancelled_log_close_discards_unstarted_queue_but_allows_current_append(tmp_path):
    async def scenario():
        io = GatedIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        closing = None
        try:
            assert log.prepare()
            assert record(log, 0, target="in-progress")

            async def started():
                while not io.started.is_set():
                    await asyncio.sleep(0.001)

            await asyncio.wait_for(started(), 0.5)
            assert record(log, 1, target="queued-one")
            assert record(log, 2, target="queued-two")
            closing = asyncio.create_task(log.close(timeout=1.0))
            await asyncio.sleep(0)
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(closing, 0.5)
            assert not record(log, 3, target="after-close")
            assert io.lines == []  # Already started IO is allowed to finish later.
            io.release.set()
            assert await log.close(timeout=0.5)
            assert [json.loads(line)["object_id"] for line in io.lines] == ["in-progress"]

            async def worker_exited():
                while log._worker is not None and log._worker.is_alive():
                    await asyncio.sleep(0.001)

            await asyncio.wait_for(worker_exited(), 0.5)
        finally:
            io.release.set()
            if closing is not None:
                await asyncio.gather(closing, return_exceptions=True)
            await log.close(timeout=0.5)

    asyncio.run(scenario())
