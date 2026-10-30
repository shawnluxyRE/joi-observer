"""Linux resource ownership and contention at the real local process boundary."""

import asyncio
import errno
import os
from pathlib import Path
import time

import pytest

from joi_observer.collectors import _local_io
from joi_observer.collectors.hardware import LocalHardwareIO
from test_local_hardware_io import INVENTORY, LINUX, assert_reaped, executable, wait_marker


@pytest.mark.parametrize("finish", ["normal", "cancel", "close"])
def test_owned_output_pipes_work_on_native_event_loop(tmp_path, monkeypatch, capsys, finish):
    """Exercise actual POSIX/Windows pipes, including Proactor overlapped handles."""
    marker = tmp_path / "native-pid"
    worker = tmp_path / "native-worker.py"
    worker.write_text("import os, sys, time\nfrom pathlib import Path\n"
        f"marker = Path({str(marker)!r})\n"
        "pending = marker.with_name(marker.name + '.pending')\n"
        "pending.write_text(str(os.getpid()))\npending.replace(marker)\n"
        + ("sys.stdout.write('captured output')\nsys.stderr.write('captured diagnostic')\n"
           if finish == "normal" else "time.sleep(30)\n"), encoding="utf-8")
    monkeypatch.setattr(_local_io, "_WORKER", worker)

    async def scenario():
        port = LocalHardwareIO()
        operation = asyncio.create_task(port.read_text("/proc/stat"))
        handle = None
        try:
            pid = await wait_marker(marker)
            if os.name == "nt":
                import ctypes
                from ctypes import wintypes

                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
                kernel.OpenProcess.restype = wintypes.HANDLE
                kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
                kernel.WaitForSingleObject.restype = wintypes.DWORD
                kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
                kernel.CloseHandle.restype = wintypes.BOOL
                handle = kernel.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE only
                if finish != "normal":
                    assert handle
            started = time.monotonic()
            if finish == "normal":
                assert await operation == "captured output"
            else:
                if finish == "cancel":
                    operation.cancel()
                else:
                    await port.close()
                with pytest.raises(asyncio.CancelledError):
                    await operation
                assert time.monotonic() - started < 0.25
            if os.name == "nt":
                assert not handle or kernel.WaitForSingleObject(handle, 0) == 0
            else:
                assert_reaped(pid)
        finally:
            await port.close()
            await asyncio.gather(operation, return_exceptions=True)
            if handle:
                kernel.CloseHandle(handle)

    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


@LINUX
def test_many_local_ports_close_concurrently_and_reap_all_children(tmp_path, monkeypatch, capsys):
    markers = tmp_path / "pids"
    markers.mkdir()
    executable(tmp_path, monkeypatch,
        "import os, time\nfrom pathlib import Path\n"
        f"Path({str(markers)!r}, str(os.getpid())).write_text('ready')\n"
        "time.sleep(30)\n")

    async def scenario():
        ports = [LocalHardwareIO() for _ in range(8)]
        tasks = [asyncio.create_task(port.run(INVENTORY)) for port in ports]
        async with asyncio.timeout(3):
            while len(list(markers.iterdir())) < len(ports):
                await asyncio.sleep(0.005)
        pids = [int(path.name) for path in markers.iterdir()]
        start = time.monotonic()
        await asyncio.gather(*(port.close() for port in ports))
        elapsed = time.monotonic() - start
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(result, asyncio.CancelledError) for result in results)
        assert elapsed < 0.25
        for pid in pids:
            assert_reaped(pid)
        await asyncio.gather(*(port.close() for port in ports))

    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


@LINUX
def test_slow_command_does_not_delay_independent_proc_reader_or_heartbeat(tmp_path, monkeypatch):
    marker = tmp_path / "pid"
    executable(tmp_path, monkeypatch,
        "import os, time\nfrom pathlib import Path\n"
        f"Path({str(marker)!r}).write_text(str(os.getpid()))\ntime.sleep(30)\n")

    async def scenario():
        slow, fast = LocalHardwareIO(), LocalHardwareIO()
        task = asyncio.create_task(slow.run(INVENTORY))
        pid = await wait_marker(marker)
        turns = []

        async def heartbeat():
            for _ in range(4):
                turns.append(time.monotonic())
                await asyncio.sleep(0.01)

        raw, _ = await asyncio.wait_for(asyncio.gather(
            fast.read_text("/proc/meminfo"), heartbeat(),
        ), timeout=0.5)
        assert "MemTotal:" in raw and len(turns) == 4
        assert not task.done()
        await slow.close()
        assert_reaped(pid)
        assert (await fast.read_text("/proc/stat")).startswith("cpu ")
        await fast.close()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


@LINUX
@pytest.mark.parametrize("finish", ["timeout", "cancel", "close"])
def test_worker_blocked_opening_fifo_is_killed_and_reaped(tmp_path, monkeypatch, finish):
    marker, fifo = tmp_path / "pid", tmp_path / "blocked-fifo"
    os.mkfifo(fifo)
    worker = tmp_path / "fifo_worker.py"
    worker.write_text("import os\nfrom pathlib import Path\n"
        f"Path({str(marker)!r}).write_text(str(os.getpid()))\n"
        f"with open({str(fifo)!r}, 'rb') as stream:\n    stream.read()\n")
    monkeypatch.setattr(_local_io, "_WORKER", worker)

    async def scenario():
        port = LocalHardwareIO(timeout=0.2 if finish == "timeout" else 3)
        task = asyncio.create_task(port.read_text("/proc/stat"))
        pid = await wait_marker(marker)
        start = time.monotonic()
        if finish == "cancel":
            task.cancel()
        elif finish == "close":
            await port.close()
        with pytest.raises(TimeoutError if finish == "timeout" else asyncio.CancelledError):
            await task
        assert time.monotonic() - start < 0.25
        assert_reaped(pid)
        await port.close()

    asyncio.run(scenario())


@LINUX
def test_each_output_stream_can_reach_exactly_its_limit(tmp_path, monkeypatch, capsys):
    executable(tmp_path, monkeypatch,
        "import os\n"
        "for _ in range(256):\n    os.write(1, b'o' * 4096)\n    os.write(2, b'e' * 4096)\n")

    async def scenario():
        port = LocalHardwareIO()
        output = await port.run(INVENTORY)
        assert output.returncode == 0
        assert output.stdout == "o" * (1024 * 1024)
        assert output.stderr == "e" * (1024 * 1024)
        await port.close()

    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


@LINUX
def test_invalid_utf8_is_controlled_and_process_is_reaped(tmp_path, monkeypatch, capsys):
    marker = tmp_path / "pid"
    executable(tmp_path, monkeypatch,
        "import os\nfrom pathlib import Path\n"
        f"Path({str(marker)!r}).write_text(str(os.getpid()))\nos.write(1, b'\\xff')\n")

    async def scenario():
        port = LocalHardwareIO()
        with pytest.raises(OSError) as error:
            await port.run(INVENTORY)
        assert error.value.errno == errno.EINVAL
        assert_reaped(int(marker.read_text()))
        await port.close()

    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


@LINUX
def test_cancel_and_repeated_close_race_reaps_one_owned_process(tmp_path, monkeypatch):
    marker = tmp_path / "pid"
    executable(tmp_path, monkeypatch,
        "import os, time\nfrom pathlib import Path\n"
        f"Path({str(marker)!r}).write_text(str(os.getpid()))\ntime.sleep(30)\n")

    async def scenario():
        port = LocalHardwareIO()
        task = asyncio.create_task(port.run(INVENTORY))
        pid = await wait_marker(marker)
        start = time.monotonic()
        task.cancel()
        closes = [asyncio.create_task(port.close()) for _ in range(4)]
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(*closes)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert time.monotonic() - start < 0.25
        assert_reaped(pid)
        with pytest.raises(RuntimeError):
            await port.run(INVENTORY)

    asyncio.run(scenario())


@LINUX
def test_exited_parent_with_inherited_pipes_does_not_prevent_timeout_cleanup(tmp_path, monkeypatch):
    marker, descendant = tmp_path / "pid", tmp_path / "descendant"
    executable(tmp_path, monkeypatch,
        "import os, time\nfrom pathlib import Path\n"
        f"Path({str(marker)!r}).write_text(str(os.getpid()))\n"
        "child = os.fork()\nif child:\n"
        f"    Path({str(descendant)!r}).write_text(str(child))\n    os._exit(0)\n"
        "time.sleep(30)\n")

    async def scenario():
        port = LocalHardwareIO(timeout=0.2)
        task = asyncio.create_task(port.run(INVENTORY))
        pid = await wait_marker(marker)
        child = await wait_marker(descendant)
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            await task
        assert time.monotonic() - start < 0.25
        assert_reaped(pid)
        # An orphaned descendant belongs to init's reaper, but must be dead;
        # the directly-created process above must already have been reaped.
        status = Path(f"/proc/{child}/status")
        if status.exists():
            assert "State:\tZ" in status.read_text()
        await port.close()

    asyncio.run(scenario())


@LINUX
def test_cancelled_close_waiter_does_not_abandon_process_cleanup(tmp_path, monkeypatch):
    """Cancelling one waiter must leave cleanup owned by the local IO port."""
    marker = tmp_path / "pid"
    executable(tmp_path, monkeypatch,
        "import os, time\nfrom pathlib import Path\n"
        f"Path({str(marker)!r}).write_text(str(os.getpid()))\ntime.sleep(30)\n")

    async def scenario():
        port = LocalHardwareIO()
        operation = asyncio.create_task(port.run(INVENTORY))
        pid = await wait_marker(marker)
        start = time.monotonic()
        closing = asyncio.create_task(port.close())
        await asyncio.sleep(0)
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        await port.close()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert time.monotonic() - start < 0.25
        assert_reaped(pid)
        with pytest.raises(RuntimeError):
            await port.run(INVENTORY)

    asyncio.run(scenario())


@LINUX
@pytest.mark.parametrize("finish", ["timeout", "cancel", "close", "parallel", "runtime"])
def test_timeout_cleanup_is_bounded_when_descendant_keeps_pipes_in_new_session(tmp_path, monkeypatch, finish):
    """A detached pipe holder cannot extend the local IO cleanup deadline.

    The probe owns a separate process and adopts its orphaned descendants. It
    records the deadline violation, then explicitly kills and reaps the helper
    before returning, so an assertion failure leaves no live process.
    """
    import json
    import ctypes
    import signal
    import subprocess
    import sys
    import textwrap
    import uuid

    marker = tmp_path / "detached-pid"
    parents, descendants = tmp_path / "parents", tmp_path / "descendants"
    parents.mkdir()
    descendants.mkdir()
    executable(tmp_path, monkeypatch,
        "import os, time\nfrom pathlib import Path\n"
        "def publish(path, value):\n"
        "    pending = path.with_name('.' + path.name + '.' + str(os.getpid()) + '.pending')\n"
        "    pending.write_text(str(value))\n    pending.replace(path)\n"
        "parent = os.getpid()\n"
        f"publish(Path({str(parents)!r}, str(parent)), parent)\n"
        "child = os.fork()\nif child == 0:\n    os.setsid()\n"
        f"    publish(Path({str(descendants)!r}, str(parent)), os.getpid())\n"
        f"    publish(Path({str(marker)!r}), os.getpid())\n"
        "    time.sleep(30)\n    os._exit(0)\ntime.sleep(30)\n")
    probe = textwrap.dedent("""
        import asyncio, ctypes, json, os, signal, sys, time
        from pathlib import Path
        from joi_observer.collectors.hardware import LocalHardwareIO

        # PR_SET_CHILD_SUBREAPER: the probe can reap the orphaned pipe holder.
        assert ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) == 0

        def reap_remaining_children():
            # This isolated probe has no children outside this test. Revisit
            # after each kill because subreaper adoption can expose descendants.
            deadline = time.monotonic() + 1
            while True:
                children = Path('/proc/self/task', str(os.getpid()), 'children')
                for child in children.read_text().split():
                    try:
                        os.kill(int(child), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                try:
                    while os.waitpid(-1, os.WNOHANG)[0]:
                        pass
                except ChildProcessError:
                    return
                if time.monotonic() >= deadline:
                    raise AssertionError('Probe could not reap all of its children')
                time.sleep(0.005)

        async def scenario():
            marker = Path(sys.argv[1])
            finish = sys.argv[2]
            parents = marker.parent / 'parents'
            descendants = marker.parent / 'descendants'
            # Allow a cold Python helper to start before exercising cleanup.
            # The cleanup requirement remains 250ms after this 1s IO timeout.
            count = 3 if finish in ('parallel', 'runtime') else 1
            ports = [LocalHardwareIO(timeout=1 if finish == 'timeout' else 10) for _ in range(count)]
            port = ports[0]
            argv = ('nvidia-smi', '--query-gpu=index,uuid', '--format=csv,noheader,nounits')
            quit_requested = asyncio.Event()
            terminal = None
            if finish == 'runtime':
                from joi_observer.cli import ApplicationRuntime, RuntimeComponents
                from joi_observer.config import AppConfig, LogConfig
                from joi_observer.data.models import CollectionResult, Metric, ObjectKey, ObjectSpec
                from joi_observer.data.state import MonitorState
                from joi_observer.error_log import ErrorLog
                from joi_observer.monitor import Monitor
                from joi_observer.tui.app import ObserverApp
                from joi_observer.tui.layout import HostInfo, TerminalSize
                from datetime import datetime, timezone

                class Source:
                    def __init__(self, index, io):
                        self.io = io
                        self.spec = ObjectSpec(ObjectKey('host', 'probe-' + str(index)), (Metric('value', None),))
                    async def collect(self):
                        await self.io.run(argv)
                        return CollectionResult(self.spec.key, (Metric('value', 0),))
                    async def close(self):
                        await self.io.close()

                class Terminal:
                    restored = False
                    def enter(self):
                        pass
                    def restore(self):
                        self.restored = True
                    def size(self):
                        return TerminalSize(120, 36)
                    def render(self, frame):
                        pass
                    async def read_key(self, timeout):
                        try:
                            await asyncio.wait_for(quit_requested.wait(), timeout)
                            return 'q'
                        except TimeoutError:
                            return None

                sources = tuple(Source(index, io) for index, io in enumerate(ports))
                state = MonitorState(tuple(source.spec for source in sources))
                config = AppConfig(mount_points=(), logging=LogConfig(directory=marker.parent / 'logs'))
                log = ErrorLog(config.logging)
                monitor = Monitor(sources, state, log, timeout=10)
                terminal = Terminal()
                app = ObserverApp(config, state, terminal, host=HostInfo('offline', 'Linux'),
                                  wall_clock=lambda: datetime.now(timezone.utc))
                runtime = ApplicationRuntime(config, components=RuntimeComponents(monitor, app, log))
                assert runtime.prepare_log()
                operation = asyncio.create_task(runtime.run())
                operations = [operation]
            else:
                operations = [asyncio.create_task(io.run(argv)) for io in ports]
                operation = operations[0]
            pid = None
            report = {}
            try:
                # Only decimal final names are ready records. The temporary
                # files are invisible to readiness checks until atomic replace.
                def published(directory):
                    return [path for path in directory.iterdir() if path.name.isdecimal()]

                async with asyncio.timeout(3):
                    while not marker.exists() or len(published(descendants)) < count:
                        await asyncio.sleep(0.005)
                pid = int(marker.read_text())
                direct_pids = [int(path.name) for path in published(parents)]
                detached_pids = [int(path.read_text()) for path in published(descendants)]
                started = time.monotonic()
                if finish == 'timeout':
                    await asyncio.sleep(1.5)
                elif finish == 'cancel':
                    operation.cancel()
                    await asyncio.wait({operation}, timeout=0.25)
                elif finish == 'runtime':
                    quit_requested.set()
                    await asyncio.wait({operation}, timeout=1)
                else:
                    closing = [asyncio.create_task(io.close()) for io in ports]
                    await asyncio.wait(closing, timeout=0.25)
                report['completed_within_budget'] = operation.done()
                report['all_operations_done'] = all(task.done() for task in operations)
                report['elapsed'] = time.monotonic() - started
                report['direct_reaped'] = all(not Path('/proc', str(child)).exists() for child in direct_pids)
                report['external_alive'] = all(Path('/proc', str(child)).exists()
                    and 'State:\\tZ' not in Path('/proc', str(child), 'status').read_text()
                    for child in detached_pids)
                report['terminal_restored'] = terminal is None or terminal.restored
                if finish == 'runtime' and operation.done():
                    operation.result()
            finally:
                try:
                    if pid is not None:
                        try:
                            os.kill(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    for task in operations:
                        if not task.done():
                            task.cancel()
                    await asyncio.wait_for(asyncio.gather(*operations, return_exceptions=True), 1)
                    await asyncio.wait_for(asyncio.gather(*(io.close() for io in ports)), 1)
                finally:
                    reap_remaining_children()
                    if pid is not None:
                        report['helper_reaped'] = not Path('/proc', str(pid)).exists()
            print(json.dumps(report))

        asyncio.run(scenario())
    """)
    # A second owner outside the probe handles timeout or a broken probe finally.
    # The unique marker is inherited by every helper, even before its PID file
    # exists. pidfds prevent signalling a replacement process after PID reuse.
    owner = f"{tmp_path.resolve()}/{uuid.uuid4().hex}"
    ownership = f"JOI_IO_PROBE_OWNER={owner}".encode()
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path),
                   "JOI_IO_PROBE_OWNER": owner}
    libc, prior = ctypes.CDLL(None), ctypes.c_int()
    assert libc.prctl(37, ctypes.byref(prior), 0, 0, 0) == 0
    assert libc.prctl(36, 1, 0, 0, 0) == 0
    process = None
    tracked = {}

    def process_table():
        table = {}
        for entry in Path("/proc").iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                table[int(entry.name)] = (int(fields[1]), fields[19])
            except (OSError, IndexError, ValueError):
                continue
        return table

    def cleanup_owned_processes():
        deadline = time.monotonic() + 2
        while True:
            table = process_table()
            owned = {pid for pid, start in tracked.items()
                     if pid in table and table[pid][1] == start}
            if process is not None and process.poll() is None:
                owned.add(process.pid)
            for pid in table:
                try:
                    if ownership in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
                        owned.add(pid)
                except OSError:
                    continue
            # Include zombie descendants whose environ is already empty, before
            # killing their parent. The parent relationship proves ownership.
            while True:
                descendants = {pid for pid, (parent, _) in table.items() if parent in owned}
                if descendants <= owned:
                    break
                owned.update(descendants)
            for pid in owned:
                if pid not in table:
                    continue
                tracked[pid] = table[pid][1]
                try:
                    descriptor = os.pidfd_open(pid)
                except ProcessLookupError:
                    continue
                try:
                    current = process_table().get(pid)
                    if current == table[pid]:
                        signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                finally:
                    os.close(descriptor)
            if process is not None:
                process.poll()
            for pid in tuple(tracked):
                if process is not None and pid == process.pid:
                    continue
                try:
                    os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    pass
            current = process_table()
            remaining = {pid for pid, start in tracked.items()
                         if pid in current and current[pid][1] == start}
            if not remaining:
                return
            assert time.monotonic() < deadline, f"Probe cleanup left owned PIDs: {remaining}"
            time.sleep(0.005)

    try:
        process = subprocess.Popen([sys.executable, "-c", probe, str(marker), finish],
                                   env=environment, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        output, error = process.communicate(timeout=5)
    finally:
        try:
            cleanup_owned_processes()
        finally:
            if process is not None:
                process.stdout.close()
                process.stderr.close()
            assert libc.prctl(36, prior.value, 0, 0, 0) == 0
    assert process.returncode == 0, error
    report = json.loads(output)
    assert report["helper_reaped"]
    assert report["completed_within_budget"], (
        "1s operation timeout plus 250ms cleanup budget exceeded: an inherited "
        "pipe held outside the original process group prevents timeout completion"
    )
    assert report["all_operations_done"]
    assert report["direct_reaped"], "The directly owned subprocess must already be reaped"
    assert report["external_alive"], "Do not signal descendants outside the owned session"
    assert report["terminal_restored"]
    if finish != "timeout":
        assert report["elapsed"] < (1 if finish == "runtime" else 0.25)
