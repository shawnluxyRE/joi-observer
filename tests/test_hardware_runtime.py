"""REQ-002 生产组合根接线：仅替换原始本机 IO 和终端，不替换业务链路。"""

from __future__ import annotations

import asyncio
import socket

from joi_observer import cli
from joi_observer.collectors import hardware
from joi_observer.config import AppConfig, LogConfig
from joi_observer.tui.layout import TerminalSize


GPU_UUIDS = tuple(f"GPU-00000000-0000-0000-0000-{index + 1:012d}" for index in range(5))
MOUNTINFO = (
    "10 1 8:1 / / rw - ext4 /dev/root rw\n"
    "11 10 8:2 / /data rw - ext4 /dev/data rw\n"
    "12 10 8:3 / /archive rw - ext4 /dev/archive rw\n"
    "13 10 8:4 / /ignored rw - ext4 /dev/ignored rw\n"
)


class RecordingTerminal:
    """记录真实 compose_frame 的输出，通过真实应用读键路径退出。"""

    def __init__(self):
        self.frames = []
        self.keys = asyncio.Queue()
        self.entered = False
        self.restored = False

    def enter(self):
        self.entered = True

    def restore(self):
        self.restored = True

    def size(self):
        # 五卡恰需37行；若把inventory当成第六卡，会错误触发43行放大提示。
        return TerminalSize(120, 37)

    def render(self, frame):
        self.frames.append(frame)

    async def read_key(self, timeout):
        try:
            return await asyncio.wait_for(self.keys.get(), timeout)
        except TimeoutError:
            return None


def region_text(frame, name):
    region = next(region for region in frame.regions if region.name == name)
    return " ".join(cell.text for cell in frame.cells
                    if region.row <= cell.row < region.row + region.height
                    and region.column <= cell.column < region.column + region.width)


def hardware_is_visible(frame):
    if frame.too_small:
        return False
    gpu, host, storage = (region_text(frame, name) for name in ("gpu", "host", "storage"))
    return (all(f"Offline GPU {index}" in gpu for index in range(5))
            and "50%" in host and "4.0 GiB" in host and "16.0 GiB" in host
            and "25.0 GiB" in storage and "100.0 GiB" in storage
            and "50.0 GiB" in storage and "200.0 GiB" in storage
            and "75.0 GiB" in storage and "300.0 GiB" in storage)


def test_production_runtime_collects_local_hardware_and_closes_every_io_on_q(tmp_path, monkeypatch, capsys):
    async def scenario():
        calls = []
        instances = []
        network_attempts = []

        def reject_network(*args, **kwargs):
            network_attempts.append(args)
            raise AssertionError("Offline runtime must not attempt a network connection.")

        async def reject_async_network(*args, **kwargs):
            reject_network(*args, **kwargs)

        # 在事件循环创建后安装边界，避免误拦截Windows事件循环自身的本地唤醒机制。
        monkeypatch.setattr(socket, "create_connection", reject_network)
        monkeypatch.setattr(socket, "getaddrinfo", reject_network)
        monkeypatch.setattr(socket.socket, "connect", reject_network)
        monkeypatch.setattr(socket.socket, "connect_ex", reject_network)
        monkeypatch.setattr(asyncio, "open_connection", reject_async_network)

        class RawLocalIO:
            """只提供proc、mountinfo、statvfs计数和nvidia-smi CSV原始输入。"""

            def __init__(self, *, timeout=3.0):
                self.timeout = timeout
                self.cpu_reads = 0
                self.closed = False
                instances.append(self)

            async def read_text(self, path):
                calls.append(("read", path))
                await asyncio.sleep(0)
                if path == "/proc/stat":
                    self.cpu_reads += 1
                    value = 100 + 50 * self.cpu_reads
                    return f"cpu {value} 0 0 {value} 0 0 0 0 0 0\n"
                if path == "/proc/meminfo":
                    return "MemTotal: 16777216 kB\nMemAvailable: 12582912 kB\nMemFree: 1048576 kB\n"
                if path == "/proc/self/mountinfo":
                    return MOUNTINFO
                raise AssertionError(f"Unexpected raw file request: {path}")

            async def statvfs(self, path):
                calls.append(("statvfs", path))
                await asyncio.sleep(0)
                total_gib = {"/": 100, "/data": 200, "/archive": 300}[path]
                return hardware.FileSystemStat(4096, total_gib * 2**18, total_gib * 3 * 2**16)

            async def run(self, argv):
                calls.append(("run", argv))
                await asyncio.sleep(0)
                assert argv[0] == "nvidia-smi"
                assert "--format=csv,noheader,nounits" in argv
                if "--query-gpu=index,uuid" in argv:
                    assert len(argv) == 3
                    return hardware.CommandOutput(0, "".join(
                        f"{index}, {uuid}\n" for index, uuid in enumerate(GPU_UUIDS)))
                assert "--query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw" in argv
                uuid = next(argument.removeprefix("--id=") for argument in argv if argument.startswith("--id="))
                index = GPU_UUIDS.index(uuid)
                return hardware.CommandOutput(0, f"{index}, {uuid}, Offline GPU {index}, {25 + index}, 8192, 16384, {60 + index}, {100 + index}.0\n")

            async def close(self):
                self.closed = True

        terminal = RecordingTerminal()
        monkeypatch.setattr(cli, "CursesTerminal", lambda: terminal)
        monkeypatch.setattr(hardware, "LocalHardwareIO", RawLocalIO)
        config = AppConfig(sample_interval=0.1, collection_timeout=0.2,
                           mount_points=("/", "/data", "/archive", "/ignored"),
                           logging=LogConfig(directory=tmp_path / "logs"))
        runtime = cli.ApplicationRuntime(config)
        task = None
        try:
            assert runtime.prepare_log()
            assert calls == []  # 装配和日志准备不得执行采集。
            task = asyncio.create_task(runtime.run())
            deadline = asyncio.get_running_loop().time() + 0.75
            while not task.done() and not any(hardware_is_visible(frame) for frame in terminal.frames):
                if asyncio.get_running_loop().time() >= deadline:
                    break
                await asyncio.sleep(0.01)
            terminal.keys.put_nowait("q")
            await asyncio.wait_for(task, timeout=0.25)
        finally:
            if task is not None and not task.done():
                terminal.keys.put_nowait("q")
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await runtime.close()

        assert terminal.entered and terminal.restored
        assert terminal.frames and any(hardware_is_visible(frame) for frame in terminal.frames), (
            "Production runtime did not present collected GPU, CPU, RAM and Storage values."
        )
        frame = next(frame for frame in reversed(terminal.frames) if hardware_is_visible(frame))
        assert frame.minimum_size == TerminalSize(120, 37) and not frame.too_small
        gpu_text = region_text(frame, "gpu")
        assert all(f"GPU {index}" in gpu_text for index in range(5))
        assert "8.0 GiB" in gpu_text and "16.0 GiB" in gpu_text and "60°C" in gpu_text
        assert "gpu_inventory" not in gpu_text and "STALE" not in " ".join(cell.text for cell in frame.cells)
        assert {path for operation, path in calls if operation == "statvfs"} == {"/", "/data", "/archive"}
        assert "/ignored" not in region_text(frame, "storage")
        assert instances and all(instance.closed for instance in instances)
        assert all(instance.timeout == config.collection_timeout for instance in instances)
        assert network_attempts == []
        assert (tmp_path / "logs" / "error.log").read_bytes() == b""

    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


def test_production_runtime_isolates_hardware_failures_and_recovers_empty_inventory(tmp_path, monkeypatch):
    """Exercise failure/recovery through the real scheduler, log and UI composition."""
    async def scenario():
        phase = {"healthy": False}
        instances = []

        class RawLocalIO:
            def __init__(self, *, timeout=3.0):
                self.closed = False
                self.cpu_reads = 0
                instances.append(self)

            async def read_text(self, path):
                if path == "/proc/stat":
                    if not phase["healthy"]:
                        raise PermissionError("PRIVATE_CPU_FAILURE")
                    self.cpu_reads += 1
                    # Busy stays fixed while idle advances: a valid idle interval.
                    return f"cpu 100 0 0 {100 + self.cpu_reads * 100} 0 0 0 0\n"
                if path == "/proc/meminfo":
                    available = 8388608 if phase["healthy"] else 12582912
                    return f"MemTotal: 16777216 kB\nMemAvailable: {available} kB\n"
                if path == "/proc/self/mountinfo":
                    return MOUNTINFO
                raise AssertionError(path)

            async def statvfs(self, path):
                assert path == "/"
                return hardware.FileSystemStat(4096, 100 * 2**18, 75 * 2**18)

            async def run(self, argv):
                assert argv == ("nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader,nounits")
                return (hardware.CommandOutput(0, "") if phase["healthy"] else
                        hardware.CommandOutput(9, "PRIVATE_DRIVER_FAILURE", "PRIVATE_STDERR"))

            async def close(self):
                self.closed = True

        terminal = RecordingTerminal()
        monkeypatch.setattr(cli, "CursesTerminal", lambda: terminal)
        monkeypatch.setattr(hardware, "LocalHardwareIO", RawLocalIO)
        runtime = cli.ApplicationRuntime(AppConfig(
            sample_interval=0.1, collection_timeout=0.2, mount_points=("/",),
            logging=LogConfig(directory=tmp_path / "logs")))
        assert runtime.prepare_log()
        task = asyncio.create_task(runtime.run())

        async def wait_frame(predicate):
            deadline = asyncio.get_running_loop().time() + 2
            while asyncio.get_running_loop().time() < deadline:
                match = next((frame for frame in reversed(terminal.frames) if predicate(frame)), None)
                if match is not None:
                    return match
                if task.done():
                    await task
                    raise AssertionError("Runtime stopped before the expected frame")
                await asyncio.sleep(0.005)
            raise AssertionError("Expected hardware failure/recovery frame was not drawn")

        try:
            failed = await wait_frame(lambda frame:
                "STALE" in region_text(frame, "gpu")
                and "STALE" in region_text(frame, "host")
                and "4.0 GiB" in region_text(frame, "host")
                and "25.0 GiB" in region_text(frame, "storage"))
            assert "No NVIDIA GPUs" not in region_text(failed, "gpu")
            assert "STALE" not in region_text(failed, "storage")
            host = next(region for region in failed.regions if region.name == "host")
            cpu_text = " ".join(cell.text for cell in failed.cells if cell.row == host.row + 1
                                and host.column <= cell.column < host.column + host.width)
            assert "—" in cpu_text and "0%" not in cpu_text
            phase["healthy"] = True
            recovered = await wait_frame(lambda frame:
                "No NVIDIA GPUs" in region_text(frame, "gpu")
                and "STALE" not in region_text(frame, "host")
                and "8.0 GiB" in region_text(frame, "host"))
            assert "STALE" not in region_text(recovered, "gpu")
            assert failed.regions == recovered.regions
            assert failed.minimum_size == recovered.minimum_size == TerminalSize(120, 36)
            assert all("PRIVATE" not in cell.text for frame in terminal.frames for cell in frame.cells)
            terminal.keys.put_nowait("q")
            await asyncio.wait_for(task, 1)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await runtime.close()

        records = (tmp_path / "logs" / "error.log").read_text(encoding="utf-8").splitlines()
        assert len(records) == 2  # One failure per source; healthy empty inventory is not an error.
        assert all("PRIVATE" not in record for record in records)
        assert instances and all(instance.closed for instance in instances)
        assert terminal.restored

    asyncio.run(scenario())
