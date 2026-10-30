"""REQ-003 subprocess boundary contracts; no real executable or socket is used.

Only OS process creation is replaced. LocalDockerCommand remains the subject;
StreamReader, scheduling, timeout and cancellation use the real event loop.
"""

import asyncio
import os

import pytest

from joi_observer.collectors.docker import (
    CommandOutput,
    DOCKER_INSPECT_TEMPLATE,
    DockerOutputLimitError,
    LocalDockerCommand,
)


pytestmark = pytest.mark.usefixtures("no_live_docker_io")


ARGV = (
    "docker", "--host", "unix:///var/run/docker.sock", "container", "inspect",
    "--format", DOCKER_INSPECT_TEMPLATE, "--", "actual-container",
)


class ObservedReader(asyncio.StreamReader):
    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()

    async def read(self, n=-1):
        self.started.set()
        return await super().read(n)

    async def readexactly(self, n):
        self.started.set()
        return await super().readexactly(n)

    async def readuntil(self, separator=b"\n"):
        self.started.set()
        return await super().readuntil(separator)

    async def readline(self):
        self.started.set()
        return await super().readline()


class OfflineProcess:
    """A process with actual async pipes and observable kill/reap lifecycle."""

    def __init__(self, *, stdout=b"", stderr=b"", returncode=None):
        self.stdout = ObservedReader()
        self.stderr = ObservedReader()
        self.stdin = None
        self.pid = 987654
        self.returncode = None
        self.done = asyncio.Event()
        self.killed = asyncio.Event()
        self.kill_calls = 0
        self.wait_calls = 0
        self.reaped = False
        self.stdout.feed_data(stdout)
        self.stderr.feed_data(stderr)
        if returncode is not None:
            self.finish(returncode)

    def finish(self, returncode):
        self.returncode = returncode
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.done.set()

    def kill(self):
        self.kill_calls += 1
        self.killed.set()
        self.finish(-9)

    async def wait(self):
        self.wait_calls += 1
        await self.done.wait()
        self.reaped = True
        return self.returncode

    async def communicate(self, input=None):
        assert input is None
        streams = await asyncio.gather(self.stdout.read(), self.stderr.read())
        await self.wait()
        return tuple(streams)


def replace_process_creation(monkeypatch, process):
    calls = []
    spawned = asyncio.Event()

    async def spawn(*argv, **kwargs):
        calls.append((argv, kwargs))
        spawned.set()
        return process

    async def no_shell(*args, **kwargs):
        pytest.fail("Docker inspection must never use a shell")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", no_shell)
    return calls, spawned


async def wait_for_spawn(spawned, task):
    """Surface entry-point failures instead of hiding them behind a barrier timeout."""
    barrier = asyncio.create_task(spawned.wait())
    try:
        done, _ = await asyncio.wait({barrier, task}, timeout=1,
                                     return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            await task
        assert barrier in done, "Local command did not reach its OS creation port"
    finally:
        barrier.cancel()
        await asyncio.gather(barrier, return_exceptions=True)


def test_local_inspect_uses_isolated_environment_and_returns_raw_output(monkeypatch):
    async def scenario():
        for key in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CONFIG", "DOCKER_FUTURE_OPTION"):
            monkeypatch.setenv(key, "remote-or-secret")
        monkeypatch.setenv("LC_ALL", "zh_CN.UTF-8")
        monkeypatch.setenv("LANG", "zh_CN.UTF-8")
        monkeypatch.setenv("JOI_OFFLINE_TEST", "preserved")
        environment_before = dict(os.environ)
        process = OfflineProcess(stdout=b"\xffraw-json\n", stderr=b"diagnostic\x00", returncode=7)
        calls, _ = replace_process_creation(monkeypatch, process)
        command = LocalDockerCommand()
        argv = (*ARGV[:-1], "actual;echo-secret")
        output = await asyncio.wait_for(command.run(argv, timeout=0.5), 1)
        assert output == CommandOutput(7, b"\xffraw-json\n", b"diagnostic\x00")
        assert len(calls) == 1 and calls[0][0] == argv
        options = calls[0][1]
        assert options["stdin"] == asyncio.subprocess.DEVNULL
        assert options["stdout"] == options["stderr"] == asyncio.subprocess.PIPE
        assert not options.get("shell", False)
        environment = options["env"]
        assert environment is not os.environ
        assert not any(key.startswith("DOCKER_") for key in environment)
        assert environment["LC_ALL"] == environment["LANG"] == "C"
        assert environment["JOI_OFFLINE_TEST"] == "preserved"
        assert dict(os.environ) == environment_before
        assert process.reaped and process.kill_calls == 0
        await asyncio.wait_for(command.close(), 1)
    asyncio.run(scenario())


@pytest.mark.parametrize("argv", [
    ("docker", "--host", "tcp://remote:2375", *ARGV[3:]),
    ("docker", "--context", "remote", *ARGV[3:]),
    (*ARGV[:4], "restart", *ARGV[5:]),
    (*ARGV[:6], "{{json .}}", *ARGV[7:]),
    (*ARGV, "another-container"),
    (*ARGV[:7], ARGV[-1]),
    ("sh", "-c", "docker inspect actual-container"),
    (*ARGV[:-1], ""),
    (*ARGV[:-1], None),
    (*ARGV[:-1], "actual\x00container"),
])
def test_non_local_or_non_inspect_command_is_rejected_without_spawning(monkeypatch, argv):
    async def scenario():
        calls, _ = replace_process_creation(monkeypatch, OfflineProcess(returncode=0))
        command = LocalDockerCommand()
        with pytest.raises(ValueError):
            await asyncio.wait_for(command.run(argv, timeout=0.5), 1)
        assert calls == []
        await asyncio.wait_for(command.close(), 1)
    asyncio.run(scenario())


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True, False, None, "3"])
def test_invalid_timeout_is_rejected_without_spawning(monkeypatch, timeout):
    async def scenario():
        calls, _ = replace_process_creation(monkeypatch, OfflineProcess(returncode=0))
        command = LocalDockerCommand()
        with pytest.raises(ValueError):
            await asyncio.wait_for(command.run(ARGV, timeout=timeout), 1)
        assert calls == []
        await asyncio.wait_for(command.close(), 1)
    asyncio.run(scenario())


def test_each_stream_accepts_exactly_65536_bytes_and_both_are_drained(monkeypatch):
    async def scenario():
        process = OfflineProcess()
        replace_process_creation(monkeypatch, process)
        command = LocalDockerCommand()

        async def produce():
            # Neither pipe reaches EOF until both drains have started. A serial
            # read of stdout followed by stderr would deadlock this OS boundary.
            await process.stdout.started.wait()
            await process.stderr.started.wait()
            process.stdout.feed_data(b"a" * 65536)
            process.stderr.feed_data(b"b" * 65536)
            process.finish(0)

        producer = asyncio.create_task(produce())
        try:
            output = await asyncio.wait_for(command.run(ARGV, timeout=0.5), 1)
            assert output == CommandOutput(0, b"a" * 65536, b"b" * 65536)
            assert process.reaped
        finally:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)
        await asyncio.wait_for(command.close(), 1)
    asyncio.run(scenario())


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_output_limit_kills_and_reaps_before_pipe_eof(monkeypatch, stream):
    async def scenario():
        process = OfflineProcess(**{stream: b"x" * 65537})
        replace_process_creation(monkeypatch, process)
        command = LocalDockerCommand()
        # The child stays alive and keeps its pipes open until killed; buffering
        # through communicate() and checking size afterwards cannot satisfy this.
        with pytest.raises(DockerOutputLimitError):
            await asyncio.wait_for(command.run(ARGV, timeout=0.5), 1)
        assert process.kill_calls == 1
        assert process.reaped and process.returncode == -9
        await asyncio.wait_for(command.close(), 1)
    asyncio.run(scenario())


def test_timeout_kills_and_reaps_without_console_output(monkeypatch, capsys):
    async def scenario():
        process = OfflineProcess()
        replace_process_creation(monkeypatch, process)
        command = LocalDockerCommand()
        started_at = asyncio.get_running_loop().time()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(command.run(ARGV, timeout=0.02), 1)
        assert asyncio.get_running_loop().time() - started_at < 0.27
        assert process.kill_calls == 1
        assert process.reaped and process.returncode == -9
        await asyncio.wait_for(command.close(), 1)
    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


def test_cancellation_propagates_after_kill_and_reap(monkeypatch, capsys):
    async def scenario():
        process = OfflineProcess()
        _, spawned = replace_process_creation(monkeypatch, process)
        command = LocalDockerCommand()
        task = asyncio.create_task(command.run(ARGV, timeout=10))
        try:
            await wait_for_spawn(spawned, task)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 0.25)
            assert process.kill_calls == 1
            assert process.reaped and process.returncode == -9
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await asyncio.wait_for(command.close(), 1)
    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


def test_close_cancels_running_command_is_idempotent_and_prevents_reuse(monkeypatch):
    async def scenario():
        process = OfflineProcess()
        calls, spawned = replace_process_creation(monkeypatch, process)
        command = LocalDockerCommand()
        task = asyncio.create_task(command.run(ARGV, timeout=10))
        try:
            await wait_for_spawn(spawned, task)
            await asyncio.wait_for(command.close(), 0.25)
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 0.25)
            assert process.kill_calls == 1
            assert process.reaped and process.returncode == -9
            await asyncio.wait_for(command.close(), 0.25)
            with pytest.raises(RuntimeError):
                await asyncio.wait_for(command.run(ARGV, timeout=0.5), 1)
            assert len(calls) == 1 and process.kill_calls == 1
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


@pytest.mark.parametrize("error", [FileNotFoundError, PermissionError, OSError])
def test_spawn_error_is_preserved_and_next_run_can_succeed(monkeypatch, error):
    async def scenario():
        calls = 0
        process = OfflineProcess(stdout=b"next sample", returncode=0)

        async def spawn(*argv, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise error("private OS diagnostic")
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        command = LocalDockerCommand()
        with pytest.raises(error, match="private OS diagnostic"):
            await command.run(ARGV, timeout=0.5)
        assert await command.run(ARGV, timeout=0.5) == CommandOutput(0, b"next sample")
        assert calls == 2 and process.reaped and process.kill_calls == 0
        await command.close()
    asyncio.run(scenario())


def test_cancel_during_spawn_reaps_child_returned_by_creation_race(monkeypatch):
    async def scenario():
        process = OfflineProcess()
        creating = asyncio.Event()

        async def spawn(*argv, **kwargs):
            creating.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                # Creation succeeded just as its awaiter was cancelled. A child
                # returned by the OS boundary still belongs to this command.
                return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        command = LocalDockerCommand()
        run = asyncio.create_task(command.run(ARGV, timeout=10))
        await wait_for_spawn(creating, run)
        run.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(run, 0.25)
        assert process.kill_calls == 1 and process.reaped
        await command.close()
    asyncio.run(scenario())


def test_simultaneous_cancel_and_repeated_close_finish_delayed_reaping(monkeypatch):
    async def scenario():
        class DelayedReapProcess(OfflineProcess):
            def kill(self):
                self.kill_calls += 1
                self.killed.set()
                asyncio.get_running_loop().call_later(0.02, self.finish, -9)

        process = DelayedReapProcess()
        _, spawned = replace_process_creation(monkeypatch, process)
        command = LocalDockerCommand()
        existing_tasks = asyncio.all_tasks()
        run = asyncio.create_task(command.run(ARGV, timeout=10))
        await wait_for_spawn(spawned, run)
        run.cancel()
        close_one = asyncio.create_task(command.close())
        await process.killed.wait()
        # Monitor cancellation and direct close may overlap while wait() has
        # not returned; neither may interrupt the owner's reap operation.
        run.cancel()
        close_two = asyncio.create_task(command.close())
        await asyncio.wait_for(asyncio.gather(close_one, close_two), 0.25)
        with pytest.raises(asyncio.CancelledError):
            await run
        assert process.kill_calls == 1 and process.reaped
        assert not (asyncio.all_tasks() - existing_tasks)
    asyncio.run(scenario())


def test_cancelled_close_still_reaps_and_propagates_its_cancellation(monkeypatch):
    async def scenario():
        class DelayedReapProcess(OfflineProcess):
            def kill(self):
                self.kill_calls += 1
                self.killed.set()
                asyncio.get_running_loop().call_later(0.02, self.finish, -9)

        process = DelayedReapProcess()
        _, spawned = replace_process_creation(monkeypatch, process)
        command = LocalDockerCommand()
        run = asyncio.create_task(command.run(ARGV, timeout=10))
        await wait_for_spawn(spawned, run)
        closing = asyncio.create_task(command.close())
        await process.killed.wait()
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(closing, 0.25)
        with pytest.raises(asyncio.CancelledError):
            await run
        assert process.kill_calls == 1 and process.reaped
        await command.close()
    asyncio.run(scenario())


def test_close_cancellation_is_preserved_when_reaping_finishes_same_turn(monkeypatch):
    async def scenario():
        closing = None

        class CancelAtReapProcess(OfflineProcess):
            async def wait(self):
                returncode = await super().wait()
                if self.killed.is_set():
                    # Arrange an external cancellation in the exact turn that
                    # the task reaping this child completes. This is distinct
                    # from the child's own cancellation and must propagate.
                    asyncio.current_task().add_done_callback(lambda _: closing.cancel())
                return returncode

        process = CancelAtReapProcess()
        _, spawned = replace_process_creation(monkeypatch, process)
        command = LocalDockerCommand()
        run = asyncio.create_task(command.run(ARGV, timeout=10))
        await wait_for_spawn(spawned, run)
        closing = asyncio.create_task(command.close())
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(closing, 0.25)
        with pytest.raises(asyncio.CancelledError):
            await run
        assert process.kill_calls == 1 and process.reaped
        await command.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize("trigger", ["output_limit", "cancel", "close"])
def test_backpressured_pipe_is_released_before_command_cleanup_returns(monkeypatch, stream, trigger):
    """Model asyncio's pipe backpressure and delayed child-exit notification.

    Process.wait started before child exit waits for pipe disconnection too.
    Killing the child alone cannot disconnect a paused pipe; cleanup must
    release the pipe before returning or forgetting the owned process.
    """
    async def scenario():
        class PipeTransport:
            def __init__(self, process, reader):
                self.process = process
                self.reader = reader
                self.paused = False
                self.closed = False

            def pause_reading(self):
                self.paused = True

            def resume_reading(self):
                self.paused = False
                if self.process.returncode is not None:
                    self.close()

            def close(self):
                self.closed = True
                self.paused = False
                self.reader.feed_eof()
                if self.process.returncode is not None:
                    self.process.done.set()

            def is_closing(self):
                return self.closed

        class BackpressuredProcess(OfflineProcess):
            def __init__(self):
                super().__init__()
                reader = getattr(self, stream)
                self.pipe = PipeTransport(self, reader)
                reader.set_transport(self.pipe)
                # More than twice StreamReader's 64 KiB limit pauses its OS
                # transport. An overflow read leaves >64 KiB still buffered.
                reader.feed_data(b"x" * (3 * 65536))
                assert self.pipe.paused
                # The process transport closes its owned pipes when closed.
                self._transport = self.pipe

            def kill(self):
                self.kill_calls += 1
                self.killed.set()
                # A real SIGKILL does not synchronously set returncode. The
                # child watcher runs later, after cleanup has entered wait().
                asyncio.get_running_loop().call_soon(self.child_exited)

            def child_exited(self):
                self.returncode = -9
                getattr(self, "stderr" if stream == "stdout" else "stdout").feed_eof()
                if not self.pipe.paused:
                    self.pipe.close()

            async def wait(self):
                self.wait_calls += 1
                if self.returncode is None:
                    await self.done.wait()
                self.reaped = True
                return self.returncode

        process = BackpressuredProcess()
        _, spawned = replace_process_creation(monkeypatch, process)
        command = LocalDockerCommand()
        existing_tasks = asyncio.all_tasks()
        run = asyncio.create_task(command.run(ARGV, timeout=2))
        try:
            if trigger == "output_limit":
                with pytest.raises(DockerOutputLimitError):
                    await asyncio.wait_for(run, 1)
            else:
                await wait_for_spawn(spawned, run)
                if trigger == "cancel":
                    run.cancel()
                else:
                    await asyncio.wait_for(command.close(), 1)
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(run, 1)
            assert process.kill_calls == 1 and process.reaped
            assert process.pipe.closed and not process.pipe.paused
            assert not (asyncio.all_tasks() - existing_tasks)
        finally:
            # Release the test double even when the contract assertion fails.
            process.pipe.close()
            if process.returncode is None:
                process.kill()
                await asyncio.sleep(0)
            run.cancel()
            await asyncio.gather(run, return_exceptions=True)
            await command.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("trigger", ["output_limit", "cancel", "close"])
def test_cleanup_failure_keeps_original_outcome_and_close_retries_owned_resources(monkeypatch, trigger):
    async def scenario():
        process = OfflineProcess(stdout=b"x" * 65537 if trigger == "output_limit" else b"")

        class RetryablePipe:
            def __init__(self):
                self.attempts = 0
                self.closed = False

            def close(self):
                self.attempts += 1
                if self.attempts == 1:
                    raise TimeoutError("offline cleanup fault")
                self.closed = True
                process.stdout.feed_eof()

        pipe = RetryablePipe()
        process.stdout.set_transport(pipe)
        _, spawned = replace_process_creation(monkeypatch, process)
        command = LocalDockerCommand()
        existing_tasks = asyncio.all_tasks()
        run = asyncio.create_task(command.run(ARGV, timeout=2))
        if trigger == "output_limit":
            with pytest.raises(DockerOutputLimitError):
                await run
        else:
            await wait_for_spawn(spawned, run)
            if trigger == "cancel":
                run.cancel()
            else:
                await command.close()
            with pytest.raises(asyncio.CancelledError):
                await run
        assert pipe.attempts == 1 and not pipe.closed
        # Resources must still be owned after the failed cleanup, allowing a
        # later close to finish them without starting or killing another child.
        await asyncio.gather(command.close(), command.close())
        assert pipe.attempts == 2 and pipe.closed
        assert process.kill_calls == 1 and process.reaped
        assert not (asyncio.all_tasks() - existing_tasks)
        await command.close()
        assert pipe.attempts == 2
    asyncio.run(scenario())


def test_cleanup_closes_read_pipes_before_reaping_and_parent_after_reaping(monkeypatch, caplog, capsys):
    async def scenario():
        import logging

        process = OfflineProcess()
        events = []

        class ReadPipe:
            def __init__(self, name):
                self.name = name

            def close(self):
                events.append(self.name)
                getattr(process, self.name).feed_eof()

        class ParentTransport:
            def close(self):
                events.append("parent")
                # Mirror asyncio's debug warning if parent.close precedes the
                # child watcher recording process exit.
                if process.returncode is None:
                    logging.getLogger("asyncio").warning("Close running child process")

        def kill():
            process.kill_calls += 1
            process.killed.set()
            events.append("kill")
            asyncio.get_running_loop().call_soon(process.finish, -9)

        process.kill = kill
        process.stdout.set_transport(ReadPipe("stdout"))
        process.stderr.set_transport(ReadPipe("stderr"))
        process._transport = ParentTransport()
        _, spawned = replace_process_creation(monkeypatch, process)
        command = LocalDockerCommand()
        run = asyncio.create_task(command.run(ARGV, timeout=2))
        await wait_for_spawn(spawned, run)
        await command.close()
        with pytest.raises(asyncio.CancelledError):
            await run
        assert events == ["kill", "stdout", "stderr", "parent"]
        assert process.reaped
    asyncio.run(scenario(), debug=True)
    assert not [record for record in caplog.records if record.levelname in ("WARNING", "ERROR", "CRITICAL")]
    assert capsys.readouterr() == ("", "")


def test_close_retries_finished_cleanup_before_run_caller_resumes(monkeypatch):
    async def scenario():
        cleanup_failed = asyncio.Event()
        process = OfflineProcess(stdout=b"x" * 65537)

        class RetryablePipe:
            def __init__(self):
                self.attempts = 0
                self.closed = False

            def close(self):
                self.attempts += 1
                if self.attempts == 1:
                    # Wake close before the run caller receives its failed
                    # sample, covering the finished-operation ownership window.
                    cleanup_failed.set()
                    raise TimeoutError("offline cleanup fault")
                self.closed = True
                process.stdout.feed_eof()

        pipe = RetryablePipe()
        process.stdout.set_transport(pipe)
        replace_process_creation(monkeypatch, process)
        command = LocalDockerCommand()

        async def close_on_failure():
            await cleanup_failed.wait()
            await command.close()

        closing = asyncio.create_task(close_on_failure())
        with pytest.raises(DockerOutputLimitError):
            await command.run(ARGV, timeout=2)
        await closing
        assert pipe.attempts == 2 and pipe.closed
        assert process.kill_calls == 1 and process.reaped
    asyncio.run(scenario())


@pytest.mark.parametrize("trigger", ["timeout", "output_limit", "cancel"])
def test_completed_failure_cleanup_allows_next_sample_on_same_command(monkeypatch, trigger):
    """Transient collection failure must not permanently poison its owned port."""
    async def scenario():
        first = OfflineProcess(stdout=b"x" * 65537 if trigger == "output_limit" else b"")
        second = OfflineProcess(stdout=b"next sample", returncode=0)
        pipes = []

        class ReadPipe:
            def __init__(self, reader):
                self.reader = reader
                self.closed = False

            def close(self):
                self.closed = True
                self.reader.feed_eof()

        for process in (first, second):
            for reader in (process.stdout, process.stderr):
                pipe = ReadPipe(reader)
                reader.set_transport(pipe)
                pipes.append(pipe)

        calls, spawned = replace_process_creation(monkeypatch, first)
        command = LocalDockerCommand()
        existing_tasks = asyncio.all_tasks()
        run = asyncio.create_task(command.run(ARGV, timeout=0.02 if trigger == "timeout" else 2))
        if trigger == "cancel":
            await wait_for_spawn(spawned, run)
            run.cancel()
            expected = asyncio.CancelledError
        else:
            expected = TimeoutError if trigger == "timeout" else DockerOutputLimitError
        with pytest.raises(expected):
            await asyncio.wait_for(run, 1)
        assert len(calls) == 1 and first.kill_calls == 1 and first.reaped
        assert all(pipe.closed for pipe in pipes[:2])

        next_calls, _ = replace_process_creation(monkeypatch, second)
        assert await command.run(ARGV, timeout=0.5) == CommandOutput(0, b"next sample")
        assert len(next_calls) == 1 and second.kill_calls == 0 and second.reaped
        assert first.kill_calls == 1 and all(pipe.closed for pipe in pipes)
        await command.close()
        assert not (asyncio.all_tasks() - existing_tasks)
    asyncio.run(scenario())
