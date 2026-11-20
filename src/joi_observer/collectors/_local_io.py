"""Cancellable local processes shared by the public hardware IO adapter."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import errno
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys

from joi_observer.collectors._hardware_worker import LIMIT, PROC_FILES
from joi_observer._shutdown import await_owner, cancel_once, join_tasks, run_cleanup, spawn


_WORKER = Path(__file__).with_name("_hardware_worker.py")
_INVENTORY = ("nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader,nounits")
_GPU_QUERY = "--query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"
_CLEANUP_SECONDS = 0.25


class LocalProcessIO:
    """One owner's processes, with independent deadlines and idempotent cleanup."""

    def __init__(self, *, timeout: float = 3.0) -> None:
        if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        self.timeout = timeout
        self._operations: set[asyncio.Task] = set()
        self._closed = False
        self._close_task: asyncio.Future | None = None
        self._cleanup_tasks: set[asyncio.Future] = set()

    async def read_text(self, path: str) -> str:
        if path not in PROC_FILES:
            raise ValueError("Only the hardware proc files may be read")
        return await self._worker("read", path)

    async def statvfs(self, path: str):
        from joi_observer.collectors.hardware import FileSystemStat

        if not isinstance(path, str) or not path.startswith("/") or "\x00" in path:
            raise ValueError("An absolute local path is required")
        raw = await self._worker("statvfs", path)
        try:
            values = json.loads(raw)
            if not isinstance(values, list) or len(values) != 3 or any(type(v) is not int for v in values):
                raise ValueError("Invalid counts")
        except (ValueError, TypeError) as error:
            raise OSError(errno.EINVAL, "Invalid worker response") from error
        return FileSystemStat(*values)

    async def run(self, argv: tuple[str, ...]):
        from joi_observer.collectors.hardware import CommandOutput

        valid = argv == _INVENTORY or (
            isinstance(argv, tuple) and len(argv) == 4
            and argv[:3] == ("nvidia-smi", _GPU_QUERY, _INVENTORY[2])
            and isinstance(argv[3], str)
            and re.fullmatch(r"--id=GPU-[A-Za-z0-9-]{1,124}", argv[3]) is not None
        )
        if not valid:
            raise ValueError("Only fixed NVIDIA read-only queries are allowed")
        return CommandOutput(*(await self._execute(argv)))

    async def _worker(self, operation: str, path: str) -> str:
        code, output, error = await self._execute((sys.executable, str(_WORKER), operation, path))
        if code:
            number = int(error) if error.strip().isdigit() else errno.EIO
            raise OSError(number, "Local hardware IO failed")
        return output

    @staticmethod
    async def _read(stream: asyncio.StreamReader) -> bytes:
        output = bytearray()
        while chunk := await stream.read(65536):
            if len(output) + len(chunk) > LIMIT:
                raise OSError(errno.EFBIG, "Hardware output exceeds limit")
            output.extend(chunk)
        return bytes(output)

    @staticmethod
    async def _open_pipe():
        """Own the parent's read transport separately from subprocess exit.

        Process.wait() must not depend on stdout/stderr EOF: an executable can
        leave a detached descendant holding its inherited output handles.
        Windows requires an overlapped read handle for the Proactor loop.
        """
        read_descriptor = writer = None
        read_pipe = None
        try:
            if os.name == "nt":
                import msvcrt
                from asyncio.windows_utils import PipeHandle, pipe

                read_handle, write_handle = pipe(overlapped=(True, False))
                read_pipe = PipeHandle(read_handle)
                try:
                    writer = msvcrt.open_osfhandle(write_handle, 0)
                except BaseException:
                    PipeHandle(write_handle).close()
                    raise
            else:
                read_descriptor, writer = os.pipe()
                read_pipe = os.fdopen(read_descriptor, "rb", buffering=0)
                read_descriptor = None  # The file now owns the read descriptor.
            reader = asyncio.StreamReader(limit=65536)
            transport, _ = await asyncio.get_running_loop().connect_read_pipe(
                lambda: asyncio.StreamReaderProtocol(reader), read_pipe,
            )
        except BaseException:
            if read_pipe is not None:
                with suppress(OSError):
                    read_pipe.close()
            if read_descriptor is not None:
                with suppress(OSError):
                    os.close(read_descriptor)
            if writer is not None:
                with suppress(OSError):
                    os.close(writer)
            raise
        return reader, transport, writer

    @staticmethod
    def _terminate(process: asyncio.subprocess.Process) -> None:
        # Only the owned session and direct child are signalled. A descendant
        # that created a different session is outside this port's ownership.
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            if process.returncode is None:
                process.kill()
        except ProcessLookupError:
            pass

    def _track_cleanup(self, task: asyncio.Future) -> asyncio.Future:
        self._cleanup_tasks.add(task)

        def completed(done):
            self._cleanup_tasks.discard(done)
            if not done.cancelled():
                done.exception()

        task.add_done_callback(completed)
        return task

    async def _reap(self, process: asyncio.subprocess.Process, deadline: float) -> None:
        # No PIPE streams belong to Process, so this waits only for its direct
        # child watcher, even if an external descendant keeps writing forever.
        try:
            reaped = self._track_cleanup(spawn(process.wait()))
        except BaseException:
            # No auxiliary task exists, so this cleanup owner must reap inline
            # before reporting the allocation error to its caller.
            async with asyncio.timeout_at(deadline):
                interrupted = False
                while True:
                    try:
                        await process.wait()
                        break
                    except asyncio.CancelledError:
                        interrupted = True
                if interrupted:
                    raise asyncio.CancelledError
            raise
        try:
            async with asyncio.timeout_at(deadline):
                await asyncio.shield(reaped)
        except BaseException:
            # Cancelling a wrapper cannot detach the already registered reaper.
            with suppress(BaseException):
                await await_owner(reaped)
            raise

    async def _execute(self, argv: tuple[str, ...]) -> tuple[int, str, str]:
        if self._closed:
            raise RuntimeError("Hardware IO is closed")
        operation = asyncio.current_task()
        self._operations.add(operation)
        process = None
        child_start = None
        readers: list[asyncio.Task] = []
        streams = []
        transports = []
        writers: list[int] = []
        failure = None

        def close_writers():
            while writers:
                os.close(writers.pop())

        try:
            options = {"start_new_session": True} if os.name == "posix" else {
                "creationflags": subprocess.CREATE_NO_WINDOW,
            }
            async with asyncio.timeout(self.timeout):
                for _ in range(2):
                    stream, transport, writer = await self._open_pipe()
                    streams.append(stream)
                    transports.append(transport)
                    writers.append(writer)
                child_start = spawn(asyncio.create_subprocess_exec(
                    *argv, stdin=asyncio.subprocess.DEVNULL, stdout=writers[0],
                    stderr=writers[1], **options,
                ))
                # Cancellation must not lose ownership during subprocess setup.
                process = await asyncio.shield(child_start)
                close_writers()
                for stream in streams:
                    readers.append(spawn(self._read(stream)))
                stdout, stderr = await asyncio.gather(*readers)
                code = await process.wait()
                try:
                    return code, stdout.decode("utf-8"), stderr.decode("utf-8")
                except UnicodeError as error:
                    raise OSError(errno.EINVAL, "Invalid hardware output encoding") from error
        except BaseException as error:
            failure = error
            raise
        finally:
            async def cleanup():
                deadline = asyncio.get_running_loop().time() + _CLEANUP_SECONDS
                join_error = None
                for reader in readers:
                    if not reader.done():
                        cancel_once(reader)
                if readers:
                    try:
                        await join_tasks(set(readers))
                    except BaseException as error:
                        join_error = error
                owned = process
                if owned is None and child_start is not None:
                    try:
                        async with asyncio.timeout_at(deadline):
                            owned = await asyncio.shield(child_start)
                    except BaseException as error:
                        if join_error is None:
                            join_error = error
                        if child_start.done():
                            # A failed constructor owns no child, but its pipes
                            # still belong to this cleanup. A cancelled waiter
                            # may also race with successful creation; inspect
                            # the settled result before releasing any writer.
                            with suppress(BaseException):
                                owned = child_start.result()
                        else:
                            for transport in transports:
                                transport.close()
                            # A refused wait or the cleanup deadline can leave
                            # creation pending. Keep its writers in a registered
                            # late owner until the actual spawn has settled.
                            async def finish_spawn():
                                try:
                                    late_process = await child_start
                                    self._terminate(late_process)
                                    await self._reap(late_process, asyncio.get_running_loop().time()
                                                     + _CLEANUP_SECONDS)
                                finally:
                                    close_writers()
                            try:
                                self._track_cleanup(spawn(finish_spawn()))
                            except BaseException:
                                await finish_spawn()
                                raise
                            raise
                close_writers()
                if owned is not None:
                    self._terminate(owned)

                async def discard(stream):
                    while await stream.read(65536):
                        pass

                try:
                    # Allow the killed, owned group to close its handles. This
                    # grace period is bounded independently of EOF: a detached
                    # writer cannot delay direct-child reaping or port close.
                    async with asyncio.timeout_at(min(
                            deadline, asyncio.get_running_loop().time() + 0.025)):
                        for stream in streams:
                            await discard(stream)
                except (TimeoutError, OSError):
                    pass
                finally:
                    for transport in transports:
                        transport.close()
                    if owned is not None:
                        await self._reap(owned, deadline)
                if join_error is not None:
                    raise join_error

            try:
                await run_cleanup(cleanup, publish=self._track_cleanup)
            except BaseException:
                if failure is None:
                    raise
            finally:
                self._operations.discard(operation)

    async def close(self) -> None:
        self._closed = True
        if self._close_task is None:
            active = tuple(self._operations)

            async def finish():
                for task in active:
                    cancel_once(task)
                try:
                    if active:
                        await join_tasks(set(active))
                finally:
                    # An earlier operation may have retained a late spawn/reap
                    # owner after its bounded wait; close must join that ownership.
                    remaining = {task for task in self._cleanup_tasks if not task.done()}
                    if remaining:
                        await join_tasks(remaining)

            await run_cleanup(finish, publish=lambda owner: setattr(self, "_close_task", owner))
        else:
            await await_owner(self._close_task)
