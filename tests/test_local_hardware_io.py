"""Real local Linux process tests; no remote machine, driver or network required."""

import asyncio
import errno
import json
import os
from pathlib import Path
import sys
import time

import pytest

from joi_observer.collectors import _local_io
from joi_observer.collectors.hardware import LocalHardwareIO


LINUX = pytest.mark.skipif(sys.platform != "linux", reason="Real Linux process/proc verification in local WSL")
INVENTORY = ("nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader,nounits")


def executable(tmp_path, monkeypatch, body):
    target = tmp_path / "nvidia-smi"
    target.write_text(f"#!{sys.executable}\n" + body, encoding="utf-8")
    target.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path))
    return target


def assert_reaped(pid):
    assert not Path(f"/proc/{pid}").exists(), f"Child {pid} is still alive or a zombie"


async def wait_marker(marker):
    async with asyncio.timeout(2):
        while not marker.exists():
            await asyncio.sleep(0.005)
    return int(marker.read_text())


def test_local_io_rejects_non_readonly_inputs_without_starting_process(monkeypatch):
    async def reject(*args, **kwargs):
        raise AssertionError("A rejected operation must not start a process")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", reject)

    async def scenario():
        io = LocalHardwareIO()
        for operation in (lambda: io.read_text("/etc/passwd"), lambda: io.statvfs("relative"),
                          lambda: io.run(("sh", "-c", "true")),
                          lambda: io.run((*INVENTORY, "--reset-gpu"))):
            with pytest.raises(ValueError):
                await operation()
        await io.close()
        await io.close()
        with pytest.raises(RuntimeError):
            await io.read_text("/proc/stat")

    asyncio.run(scenario())


@LINUX
def test_real_proc_and_statvfs_worker_and_errno(tmp_path, capsys):
    async def scenario():
        io = LocalHardwareIO()
        assert (await io.read_text("/proc/stat")).startswith("cpu ")
        assert "MemTotal:" in await io.read_text("/proc/meminfo")
        assert " - " in await io.read_text("/proc/self/mountinfo")
        value = await io.statvfs("/")
        assert value.fragment_size > 0 and value.blocks > 0
        assert 0 <= value.free_blocks <= value.blocks
        with pytest.raises(FileNotFoundError):
            await io.statvfs(str(tmp_path / "missing"))
        await io.close()

    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


@LINUX
def test_real_host_collectors_accept_kernel_proc_and_namespace_mounts():
    from joi_observer.collectors.hardware import CpuCollector, MemoryCollector, StorageCollector

    async def scenario():
        sources = (CpuCollector(LocalHardwareIO()), MemoryCollector(LocalHardwareIO()),
                   StorageCollector(0, "/", LocalHardwareIO()))
        try:
            results = await asyncio.gather(*(source.collect() for source in sources))
            assert all(result.failure is None for result in results), results
            ram = {metric.name: metric.value for metric in results[1].metrics}
            disk = {metric.name: metric.value for metric in results[2].metrics}
            assert 0 <= ram["ram_used_bytes"] <= ram["ram_total_bytes"]
            assert 0 <= disk["used_bytes"] <= disk["total_bytes"]
            await asyncio.sleep(0.02)
            second_cpu = await sources[0].collect()
            assert second_cpu.failure is None
            assert 0 <= second_cpu.metrics[0].value <= 100
        finally:
            await asyncio.gather(*(source.close() for source in sources))

    asyncio.run(scenario())


@LINUX
def test_real_nvidia_argv_output_and_returncode(tmp_path, monkeypatch, capsys):
    executable(tmp_path, monkeypatch, "import sys, json\nprint(json.dumps(sys.argv[1:]))\nprint('captured', file=sys.stderr)\nsys.exit(7)\n")

    async def scenario():
        io = LocalHardwareIO()
        result = await io.run(INVENTORY)
        assert result.returncode == 7
        assert json.loads(result.stdout) == list(INVENTORY[1:])
        assert result.stderr == "captured\n"
        await io.close()

    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


@LINUX
@pytest.mark.parametrize("stream", [1, 2])
def test_real_command_output_is_bounded_and_child_reaped(tmp_path, monkeypatch, stream):
    marker = tmp_path / "pid"
    executable(tmp_path, monkeypatch, f"import os, time\nfrom pathlib import Path\nPath({str(marker)!r}).write_text(str(os.getpid()))\nos.write({stream}, b'x' * (1024*1024+1))\ntime.sleep(30)\n")

    async def scenario():
        io = LocalHardwareIO(timeout=2)
        with pytest.raises(OSError) as failure:
            await io.run(INVENTORY)
        assert failure.value.errno == errno.EFBIG
        assert_reaped(int(marker.read_text()))
        await io.close()

    asyncio.run(scenario())


@LINUX
@pytest.mark.parametrize("finish", ["timeout", "cancel", "close"])
@pytest.mark.parametrize("operation", ["command", "file", "statvfs"])
def test_slow_real_process_cleanup_is_bounded(tmp_path, monkeypatch, finish, operation):
    marker = tmp_path / "pid"
    body = f"import os, time\nfrom pathlib import Path\nPath({str(marker)!r}).write_text(str(os.getpid()))\ntime.sleep(30)\n"
    if operation == "command":
        executable(tmp_path, monkeypatch, body)
    else:
        worker = tmp_path / "slow_worker.py"
        worker.write_text(body)
        monkeypatch.setattr(_local_io, "_WORKER", worker)

    async def scenario():
        io = LocalHardwareIO(timeout=0.2 if finish == "timeout" else 3)
        call = {"command": lambda: io.run(INVENTORY), "file": lambda: io.read_text("/proc/stat"),
                "statvfs": lambda: io.statvfs("/")}[operation]
        task = asyncio.create_task(call())
        pid = await wait_marker(marker)
        start = time.monotonic()
        if finish == "close":
            await io.close()
        elif finish == "cancel":
            task.cancel()
        with pytest.raises(TimeoutError if finish == "timeout" else asyncio.CancelledError):
            await task
        assert time.monotonic() - start < 0.25
        assert_reaped(pid)
        await io.close()
        await io.close()

    asyncio.run(scenario())


@LINUX
def test_cancellation_during_spawn_does_not_lose_process(tmp_path, monkeypatch):
    marker = tmp_path / "pid"
    executable(tmp_path, monkeypatch, f"import os, time\nfrom pathlib import Path\nPath({str(marker)!r}).write_text(str(os.getpid()))\ntime.sleep(30)\n")
    original = asyncio.create_subprocess_exec

    async def delayed_spawn(*args, **kwargs):
        child = await original(*args, **kwargs)
        await wait_marker(marker)
        await asyncio.sleep(0.04)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_spawn)

    async def scenario():
        io = LocalHardwareIO()
        task = asyncio.create_task(io.run(INVENTORY))
        pid = await wait_marker(marker)
        start = time.monotonic()
        task.cancel()
        await io.close()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert time.monotonic() - start < 0.25
        assert_reaped(pid)

    asyncio.run(scenario())


@LINUX
@pytest.mark.parametrize("worker_body,expected", [
    ("import sys\nsys.stderr.write('13')\nsys.exit(1)", PermissionError),
    ("import os\nos.write(1, b'x' * (1024*1024+1))", OSError),
    ("print('invalid json')", OSError),
])
def test_worker_error_and_protocol_boundaries(tmp_path, monkeypatch, worker_body, expected):
    worker = tmp_path / "worker.py"
    worker.write_text(worker_body)
    monkeypatch.setattr(_local_io, "_WORKER", worker)

    async def scenario():
        io = LocalHardwareIO()
        with pytest.raises(expected):
            await io.statvfs("/")
        await io.close()

    asyncio.run(scenario())
