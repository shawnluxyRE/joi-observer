"""External IO remains owned when task/stream wrapper allocation is refused."""

import asyncio
import errno
import os

import pytest

from joi_observer.collectors import _local_io
from joi_observer.collectors.hardware import LocalHardwareIO
from joi_observer.collectors.vllm import HttpBodyTooLargeError
from joi_observer.ipc import _worker
from test_ipc_protocol import large_snapshot_fixture
from test_local_hardware_io import INVENTORY, assert_reaped, executable
from test_vllm_httpx import MemoryStream, memory_port


async def eventually(predicate):
    async with asyncio.timeout(0.5):
        while not predicate():
            await asyncio.sleep(0.001)


@pytest.mark.parametrize("point", ["cleanup-owner", "sender-join"])
def test_codec_cleanup_allocation_failure_reaps_actual_process(monkeypatch, point):
    async def scenario():
        expected, _ = large_snapshot_fixture(2)
        processes, rejected = [], []
        real_spawn = asyncio.create_subprocess_exec
        real_task, real_gather = asyncio.create_task, asyncio.gather
        error = MemoryError("injected codec cleanup allocation")

        async def create_process(*args, **kwargs):
            process = await real_spawn(*args, **kwargs)
            processes.append(process)
            return process

        def create_task(coroutine, *args, **kwargs):
            if (point == "cleanup-owner" and not rejected and
                    getattr(coroutine, "__qualname__", "").endswith("_run.<locals>.cleanup")):
                rejected.append(coroutine)
                raise error
            return real_task(coroutine, *args, **kwargs)

        def gather(*tasks, **kwargs):
            if (point == "sender-join" and not rejected and tasks and
                    all(isinstance(task, asyncio.Task) and
                        task.get_coro().__name__ == "_send" for task in tasks)):
                rejected.append(None)
                raise error
            return real_gather(*tasks, **kwargs)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
        monkeypatch.setattr(asyncio, "create_task", create_task)
        monkeypatch.setattr(asyncio, "gather", gather)
        before = asyncio.all_tasks()
        try:
            with pytest.raises(MemoryError) as caught:
                await _worker.encode_async(expected)
            assert caught.value is error and rejected
            assert len(processes) == 1 and processes[0].returncode is not None
            await asyncio.sleep(0)
            assert not [task for task in asyncio.all_tasks() if task not in before and not task.done()]
        finally:
            for coroutine in rejected:
                if coroutine is not None:
                    coroutine.close()
            for process in processes:
                process.stdin.close()
                if process.returncode is None:
                    process.kill()
                await process.wait()

    asyncio.run(scenario())


@pytest.mark.parametrize("point", ["first-reader", "second-reader", "reap", "close-owner", "reader-join"])
def test_hardware_partial_task_allocation_still_reaps_owned_child(tmp_path, monkeypatch, point):
    executable(tmp_path, monkeypatch, "import time\ntime.sleep(30)\n")

    async def scenario():
        children, refused = [], []
        reader_count = [0]
        real_spawn = asyncio.create_subprocess_exec
        real_task, real_gather = asyncio.create_task, asyncio.gather
        error = MemoryError("injected hardware ownership allocation")

        async def create_process(*args, **kwargs):
            process = await real_spawn(*args, **kwargs)
            children.append(process)
            return process

        def create_task(coroutine, *args, **kwargs):
            name = getattr(coroutine, "__qualname__", "")
            if name == "LocalProcessIO._read":
                reader_count[0] += 1
            target = ((point == "first-reader" and name == "LocalProcessIO._read" and reader_count[0] == 1)
                      or (point == "second-reader" and name == "LocalProcessIO._read" and reader_count[0] == 2)
                      or (point == "reap" and name == "Process.wait")
                      or (point == "close-owner" and name.endswith("LocalProcessIO.close.<locals>.finish")))
            if target and not refused:
                refused.append(coroutine)
                raise error
            return real_task(coroutine, *args, **kwargs)

        def gather(*tasks, **kwargs):
            if (point == "reader-join" and not refused and tasks and
                    all(isinstance(task, asyncio.Task) and
                        task.get_coro().__qualname__ == "LocalProcessIO._read" for task in tasks)):
                refused.append(None)
                raise error
            return real_gather(*tasks, **kwargs)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
        monkeypatch.setattr(asyncio, "create_task", create_task)
        monkeypatch.setattr(asyncio, "gather", gather)
        port = LocalHardwareIO(timeout=0.05 if point == "reap" else 1.0)
        before = asyncio.all_tasks()
        operation = asyncio.create_task(port.run(INVENTORY))
        try:
            await eventually(lambda: bool(children))
            if point == "close-owner":
                with pytest.raises(MemoryError) as caught:
                    await port.close()
                assert caught.value is error
                with pytest.raises(asyncio.CancelledError):
                    await operation
            else:
                with pytest.raises(TimeoutError if point == "reap" else MemoryError) as caught:
                    await asyncio.wait_for(operation, 0.5)
                if point != "reap":
                    assert caught.value is error
            assert refused and len(children) == 1
            await port.close()
            assert children[0].returncode is not None
            assert_reaped(children[0].pid)
            await asyncio.sleep(0)
            assert not [task for task in asyncio.all_tasks() if task not in before and not task.done()]
        finally:
            for coroutine in refused:
                if coroutine is not None:
                    coroutine.close()
            for process in children:
                if process.returncode is None:
                    process.kill()
                await process.wait()
            await port.close()
            await asyncio.gather(operation, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("point", ["protocol", "connect"])
def test_pipe_transport_wrapper_failure_closes_real_descriptor_pair(monkeypatch, point):
    async def scenario():
        descriptors = []
        real_pipe = os.pipe

        def pipe():
            pair = real_pipe()
            descriptors.extend(pair)
            return pair

        def protocol(*args, **kwargs):
            raise MemoryError("injected pipe protocol allocation")

        async def connect(*args, **kwargs):
            raise MemoryError("injected read transport allocation")

        monkeypatch.setattr(os, "pipe", pipe)
        if point == "protocol":
            monkeypatch.setattr(asyncio, "StreamReaderProtocol", protocol)
        else:
            monkeypatch.setattr(asyncio.get_running_loop(), "connect_read_pipe", connect)
        try:
            with pytest.raises(MemoryError):
                await _local_io.LocalProcessIO._open_pipe()
            assert len(descriptors) == 2
            for descriptor in descriptors:
                with pytest.raises(OSError) as caught:
                    os.fstat(descriptor)
                assert caught.value.errno == errno.EBADF
        finally:
            for descriptor in descriptors:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    asyncio.run(scenario())


@pytest.mark.parametrize("point", ["cleanup-task", "cleanup-wait"])
def test_http_cleanup_allocation_failure_releases_stream_and_preserves_parse(monkeypatch, point):
    async def scenario():
        stream = MemoryStream((b"x" * 65536, b"not-read"))
        port, clients, _ = memory_port(stream)
        refused = []
        real_future, real_wait = asyncio.ensure_future, asyncio.wait

        def ensure_future(awaitable, *args, **kwargs):
            if (point == "cleanup-task" and not refused and
                    getattr(awaitable, "__qualname__", "").endswith("__aexit__")):
                refused.append(awaitable)
                raise MemoryError("injected HTTP context cleanup allocation")
            return real_future(awaitable, *args, **kwargs)

        async def wait(*args, **kwargs):
            if point == "cleanup-wait" and not refused:
                refused.append(None)
                raise MemoryError("injected HTTP release wait allocation")
            return await real_wait(*args, **kwargs)

        monkeypatch.setattr(asyncio, "ensure_future", ensure_future)
        monkeypatch.setattr(asyncio, "wait", wait)
        before = asyncio.all_tasks()
        try:
            with pytest.raises(HttpBodyTooLargeError):
                await port.get("https://model.invalid/metrics", timeout=1.0, max_bytes=1024)
            assert refused and stream.closed
            await port.close()
            assert clients[0].is_closed
            await asyncio.sleep(0)
            assert not [task for task in asyncio.all_tasks() if task not in before and not task.done()]
        finally:
            for coroutine in refused:
                if coroutine is not None:
                    coroutine.close()
            await port.close()
            await stream.aclose()

    asyncio.run(scenario())


def test_http_direct_release_fallback_can_finish_after_read_is_cancelled(monkeypatch):
    async def scenario():
        class Stream(MemoryStream):
            def __init__(self):
                super().__init__((b"ok",))
                self.closing = asyncio.Event()

            async def aclose(self):
                self.closing.set()
                await asyncio.sleep(0.02)
                self.closed = True

        stream = Stream()
        port, clients, _ = memory_port(stream)
        real_task = asyncio.create_task
        refused = []

        def create_task(coroutine, *args, **kwargs):
            if getattr(coroutine, "__qualname__", "") == "Response.aclose" and not refused:
                refused.append(coroutine)
                raise MemoryError("injected first response release allocation")
            return real_task(coroutine, *args, **kwargs)

        monkeypatch.setattr(asyncio, "create_task", create_task)
        reading = asyncio.create_task(port.get("https://model.invalid/metrics", timeout=1, max_bytes=1024))
        try:
            await asyncio.wait_for(stream.closing.wait(), 0.5)
            reading.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(reading, 0.5)
            assert refused and stream.closed
            await port.close()
            assert clients[0].is_closed
        finally:
            for coroutine in refused:
                coroutine.close()
            await port.close()
            await asyncio.gather(reading, return_exceptions=True)
            await stream.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("resource", ["codec", "hardware"])
def test_inline_cleanup_cancel_cannot_complete_before_its_reaper(tmp_path, monkeypatch, resource):
    if resource == "hardware":
        executable(tmp_path, monkeypatch, "import time\ntime.sleep(30)\n")

    async def scenario():
        children, refused = [], []
        reaping, release_reaper = asyncio.Event(), asyncio.Event()
        real_spawn, real_task = asyncio.create_subprocess_exec, asyncio.create_task
        allocation_error = MemoryError("injected inline cleanup owner allocation")

        async def create_process(*args, **kwargs):
            process = await real_spawn(*args, **kwargs)
            children.append(process)
            original_wait = process.wait

            async def wait():
                # A controlled OS wait boundary exposes ownership independently
                # of how quickly SIGKILL is observed by this test machine.
                reaping.set()
                await release_reaper.wait()
                return await original_wait()

            process.wait = wait
            return process

        def create_task(coroutine, *args, **kwargs):
            name = getattr(coroutine, "__qualname__", "")
            expected = ("_run.<locals>.cleanup" if resource == "codec" else
                        "LocalProcessIO._execute.<locals>.cleanup")
            if name.endswith(expected) and not refused:
                refused.append(coroutine)
                raise allocation_error
            return real_task(coroutine, *args, **kwargs)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
        monkeypatch.setattr(asyncio, "create_task", create_task)
        port = None
        if resource == "codec":
            expected, _ = large_snapshot_fixture(2)
            operation = asyncio.create_task(_worker.encode_async(expected))
        else:
            port = LocalHardwareIO(timeout=0.05)
            operation = asyncio.create_task(port.run(INVENTORY))
        try:
            await asyncio.wait_for(reaping.wait(), 0.5)
            assert refused
            operation.cancel()
            await asyncio.sleep(0)
            assert not operation.done(), "cancel cannot publish settlement before the reaper ends"
            release_reaper.set()
            with pytest.raises(MemoryError if resource == "codec" else TimeoutError) as caught:
                await asyncio.wait_for(operation, 0.5)
            if resource == "codec":
                assert caught.value is allocation_error
            assert children and all(process.returncode is not None for process in children)
            if port is not None:
                await port.close()
        finally:
            release_reaper.set()
            for coroutine in refused:
                coroutine.close()
            for process in children:
                if process.stdin is not None:
                    process.stdin.close()
                if process.returncode is None:
                    process.kill()
                await process.wait()
            if port is not None:
                await port.close()
            await asyncio.gather(operation, return_exceptions=True)

    asyncio.run(scenario())
