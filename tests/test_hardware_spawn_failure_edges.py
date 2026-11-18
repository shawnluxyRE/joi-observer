"""Real pipe ownership survives subprocess-constructor failures and races."""

import asyncio
import errno
import os
import subprocess

import pytest

from joi_observer.collectors import _local_io
from joi_observer.collectors.hardware import LocalHardwareIO
from test_local_hardware_io import LINUX


def descriptor_is_open(descriptor):
    try:
        os.fstat(descriptor)
    except OSError as error:
        assert error.errno == errno.EBADF
        return False
    return True


def observe_pipes(monkeypatch):
    owned = []
    real_open_pipe = _local_io.LocalProcessIO._open_pipe

    async def open_pipe():
        reader, transport, writer = await real_open_pipe()
        owned.append((transport, transport.get_extra_info("pipe").fileno(), writer))
        return reader, transport, writer

    monkeypatch.setattr(_local_io.LocalProcessIO, "_open_pipe", staticmethod(open_pipe))
    return owned


async def assert_pipes_released(owned):
    # Read transports close their underlying fd in a scheduled callback.
    await asyncio.sleep(0)
    assert owned and all(transport.is_closing() for transport, _, _ in owned)
    assert [fd for _, reader, writer in owned for fd in (reader, writer)
            if descriptor_is_open(fd)] == []


async def rescue_pipes(owned):
    # This test owns the observed fds even on a red baseline. Measure before
    # rescue and close only the handles acquired by the failed operation.
    for transport, _, writer in owned:
        transport.close()
        if descriptor_is_open(writer):
            os.close(writer)
    await asyncio.sleep(0)


@LINUX
@pytest.mark.parametrize("failure", [MemoryError(), RuntimeError(), ValueError(),
                                     OSError(errno.EAGAIN, "child creation unavailable")])
def test_failed_subprocess_constructor_releases_pipes_before_same_port_recovers(monkeypatch, failure):
    async def scenario():
        owned = observe_pipes(monkeypatch)
        real_popen = subprocess.Popen
        calls, children = [], []

        def popen(*args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                raise failure
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child

        monkeypatch.setattr(subprocess, "Popen", popen)
        port = LocalHardwareIO(timeout=1)
        baseline = asyncio.all_tasks()
        try:
            with pytest.raises(type(failure)) as caught:
                await port.read_text("/proc/meminfo")
            assert caught.value is failure
            assert len(calls) == 1 and not children and len(owned) == 2
            await assert_pipes_released(owned)
            assert not (asyncio.all_tasks() - baseline)

            # A source failure must not close the port or poison later samples.
            assert "MemTotal:" in await port.read_text("/proc/meminfo")
            assert len(calls) == 2 and len(children) == 1 and children[0].returncode == 0
            assert len(owned) == 4
            await assert_pipes_released(owned[2:])
            await port.close()
            await port.close()
            assert not (asyncio.all_tasks() - baseline)
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.wait()
            await rescue_pipes(owned)
            await port.close()

    asyncio.run(scenario())


@LINUX
@pytest.mark.parametrize("trigger", ["cancel", "close"])
def test_cancelled_spawn_wait_still_releases_pipes_when_constructor_fails(monkeypatch, trigger):
    async def scenario():
        owned = observe_pipes(monkeypatch)
        real_start, real_popen = asyncio.create_subprocess_exec, subprocess.Popen
        starting, release = asyncio.Event(), asyncio.Event()
        failure = MemoryError("injected delayed hardware constructor failure")
        calls = []

        async def delayed_start(*args, **kwargs):
            starting.set()
            await release.wait()
            return await real_start(*args, **kwargs)

        def popen(*args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                raise failure
            return real_popen(*args, **kwargs)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_start)
        monkeypatch.setattr(subprocess, "Popen", popen)
        port = LocalHardwareIO(timeout=1)
        baseline = asyncio.all_tasks()
        running = asyncio.create_task(port.read_text("/proc/meminfo"))
        closing = None
        try:
            await asyncio.wait_for(starting.wait(), 1)
            assert len(owned) == 2 and not calls
            if trigger == "cancel":
                running.cancel()
            else:
                closing = asyncio.create_task(port.close())
            # Let the operation's finally acquire its existing spawn Task.
            for _ in range(3):
                await asyncio.sleep(0)
            assert not running.done()
            release.set()
            jobs = {running} if closing is None else {running, closing}
            _, pending = await asyncio.wait(jobs, timeout=0.5)
            assert not pending, "Constructor failure left its cancelled IO owner pending"
            with pytest.raises(asyncio.CancelledError):
                running.result()
            if closing is not None:
                closing.result()
            assert len(calls) == 1
            await assert_pipes_released(owned)
            assert not (asyncio.all_tasks() - baseline)
            if trigger == "cancel":
                assert "MemTotal:" in await port.read_text("/proc/meminfo")
                assert len(calls) == 2
                await assert_pipes_released(owned[2:])
            await port.close()
            await port.close()
            assert not (asyncio.all_tasks() - baseline)
        finally:
            release.set()
            for job in (running, closing):
                if job is not None and not job.done() and not job.cancelling():
                    job.cancel()
            await asyncio.gather(*(job for job in (running, closing) if job is not None),
                                 return_exceptions=True)
            await rescue_pipes(owned)
            await port.close()

    asyncio.run(scenario())


@LINUX
@pytest.mark.parametrize("trigger", ["cancel", "timeout", "close"])
@pytest.mark.parametrize("outcome", ["child", "constructor-failure"])
def test_pending_spawn_keeps_writers_until_late_child_or_failure_settles(monkeypatch, trigger, outcome):
    """Cross the operation cleanup deadline without detaching spawn ownership.

    The gate controls only when a real asyncio/Popen construction proceeds; it
    does not replace child creation, pipe transport, termination, or reaping.
    Closing readers early is safe, but writers must remain valid for Popen.
    """
    async def scenario():
        owned = observe_pipes(monkeypatch)
        real_start, real_popen = asyncio.create_subprocess_exec, subprocess.Popen
        starting, release = asyncio.Event(), asyncio.Event()
        starts, calls, children = [], [], []
        failure = RuntimeError("injected late hardware constructor failure")

        async def delayed_start(*args, **kwargs):
            starts.append(args)
            if len(starts) == 1:
                starting.set()
                await release.wait()
            return await real_start(*args, **kwargs)

        def popen(*args, **kwargs):
            calls.append(args)
            # The pending owner must preserve both handles until actual spawn.
            assert descriptor_is_open(kwargs["stdout"])
            assert descriptor_is_open(kwargs["stderr"])
            if len(calls) == 1 and outcome == "constructor-failure":
                raise failure
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child

        monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_start)
        monkeypatch.setattr(subprocess, "Popen", popen)
        port = LocalHardwareIO(timeout=0.05 if trigger == "timeout" else 1)
        baseline = asyncio.all_tasks()
        running = asyncio.create_task(port.read_text("/proc/meminfo"))
        closing = second_close = None
        try:
            await asyncio.wait_for(starting.wait(), 1)
            assert len(owned) == 2 and not calls
            if trigger == "cancel":
                running.cancel()
            elif trigger == "close":
                closing = asyncio.create_task(port.close())
            _, pending = await asyncio.wait({running}, timeout=0.8)
            assert not pending, "The operation did not retain its bounded cleanup wait"
            with pytest.raises(TimeoutError if trigger == "timeout" else asyncio.CancelledError):
                running.result()
            await asyncio.sleep(0)
            assert all(transport.is_closing() for transport, _, _ in owned)
            assert all(not descriptor_is_open(reader) for _, reader, _ in owned)
            assert all(descriptor_is_open(writer) for _, _, writer in owned)
            assert not calls, "Only the test gate may allow child construction"
            if closing is not None:
                assert not closing.done(), "Close detached the registered late-spawn owner"
                second_close = asyncio.create_task(port.close())
                closing.cancel()
                await asyncio.sleep(0)
                assert not closing.done() and not second_close.done()
            release.set()
            if closing is not None:
                _, pending = await asyncio.wait({closing, second_close}, timeout=0.5)
                assert not pending
                with pytest.raises(asyncio.CancelledError):
                    closing.result()
                second_close.result()
            else:
                async with asyncio.timeout(0.5):
                    while any(descriptor_is_open(writer) for _, _, writer in owned):
                        await asyncio.sleep(0.001)
            await assert_pipes_released(owned)
            await asyncio.sleep(0)
            assert len(calls) == 1
            assert len(children) == (1 if outcome == "child" else 0)
            assert all(child.poll() is not None for child in children)
            assert not (asyncio.all_tasks() - baseline)
            if trigger != "close":
                # A timed-out or cancelled attempt does not retire its port.
                assert "MemTotal:" in await port.read_text("/proc/meminfo")
                assert len(calls) == 2
                await assert_pipes_released(owned[2:])
            await port.close()
            await port.close()
            assert not (asyncio.all_tasks() - baseline)
        finally:
            release.set()
            for job in (running, closing, second_close):
                if job is not None and not job.done() and not job.cancelling():
                    job.cancel()
            await asyncio.gather(*(job for job in (running, closing, second_close) if job is not None),
                                 return_exceptions=True)
            await port.close()
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.wait()
            await rescue_pipes(owned)

    asyncio.run(scenario())
