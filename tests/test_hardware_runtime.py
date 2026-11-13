"""REQ-002 生产组合根接线：仅替换原始本机 IO 和终端，不替换业务链路。"""

from __future__ import annotations

import asyncio
import json
import re
import socket
import subprocess

from joi_observer import cli
from joi_observer.collectors import docker, hardware
from joi_observer.config import AppConfig, ContainerConfig, LogConfig
from joi_observer.tui.layout import TerminalSize
from test_hardware_view import pixels


GPU_UUIDS = tuple(f"GPU-00000000-0000-0000-0000-{index + 1:012d}" for index in range(5))
MOUNTINFO = (
    "10 1 8:1 / / rw - ext4 /dev/root rw\n"
    "11 10 8:2 / /data rw - ext4 /dev/data rw\n"
    "12 10 8:3 / /archive rw - ext4 /dev/archive rw\n"
    "13 10 8:4 / /ignored rw - ext4 /dev/ignored rw\n"
)


class RecordingTerminal:
    """记录真实 compose_frame 的输出，通过真实应用读键路径退出。"""

    def __init__(self, rows=37):
        self.rows = rows
        self.frames = []
        self.keys = asyncio.Queue()
        self.entered = False
        self.restored = False

    def enter(self):
        self.entered = True

    def restore(self):
        self.restored = True

    def size(self):
        return TerminalSize(120, self.rows)

    def render(self, frame):
        self.frames.append(frame)

    async def read_key(self, timeout):
        try:
            return await asyncio.wait_for(self.keys.get(), timeout)
        except TimeoutError:
            return None


def region_text(frame, name):
    """Read rendered cells spatially; adjacent color spans add no text spaces."""
    region = next(region for region in frame.regions if region.name == name)
    grid = pixels(frame.cells)
    text = "\n".join("".join(grid.get((row, column), (" ", "text"))[0]
                            for column in range(region.column, region.column + region.width))
                     for row in range(region.row, region.row + region.height))
    return " ".join(text.split())


def has_capacity_numbers(text, *numbers):
    """Readiness depends on sampled values, not the old repeated-unit layout."""
    return "GiB" in text and all(re.search(rf"(?<![\d.]){re.escape(number)}(?![\d.])", text)
                                for number in numbers)


def hardware_is_visible(frame):
    if frame.too_small:
        return False
    gpu, host, storage = (region_text(frame, name) for name in ("gpu", "host", "storage"))
    return (all(f"Offline GPU {index}" in gpu for index in range(5))
            and "50.0%" in host and has_capacity_numbers(host, "4", "16")
            and has_capacity_numbers(storage, "25", "100", "50", "200", "75", "300"))


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

        # 在事件循环创建后安装采集边界，保持测试初始化与被测采样隔离。
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

        # 五卡恰需39行；误将inventory计为第六卡会触发45行放大提示。
        terminal = RecordingTerminal(rows=39)
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
        assert frame.minimum_size == TerminalSize(120, 39) and not frame.too_small
        gpu_text = region_text(frame, "gpu")
        assert all(f"[{index}]" in gpu_text for index in range(5))
        assert "8.0 / 16.0 GiB" in gpu_text and "60°C" in gpu_text
        assert "4 / 16 GiB" in region_text(frame, "host")
        assert all(value in region_text(frame, "storage") for value in (
            "25 / 100 GiB · 25.0%", "50 / 200 GiB · 25.0%", "75 / 300 GiB · 25.0%"))
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
                and has_capacity_numbers(region_text(frame, "host"), "4", "16")
                and has_capacity_numbers(region_text(frame, "storage"), "25", "100"))
            assert "No NVIDIA GPUs" not in region_text(failed, "gpu")
            assert "STALE" not in region_text(failed, "storage")
            host = next(region for region in failed.regions if region.name == "host")
            cpu_text = " ".join(cell.text for cell in failed.cells if cell.row == host.row + 1
                                and host.column <= cell.column < host.column + host.width)
            assert "—" in cpu_text and "0.0%" not in cpu_text
            phase["healthy"] = True
            recovered = await wait_frame(lambda frame:
                "No NVIDIA GPUs" in region_text(frame, "gpu")
                and "STALE" not in region_text(frame, "host")
                and has_capacity_numbers(region_text(frame, "host"), "8", "16"))
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
        assert "4 / 16 GiB" in region_text(failed, "host")
        assert "8 / 16 GiB" in region_text(recovered, "host")

    asyncio.run(scenario())


def test_joint_runtime_samples_hardware_and_docker_isolates_failures_and_closes_on_q(
        tmp_path, monkeypatch, capsys):
    """Both real collector chains share one runtime; only raw IO and terminal are replaced."""
    async def scenario():
        terminal = RecordingTerminal()
        hardware_ports, docker_ports, forbidden_calls = [], [], []
        phase = {"cpu_failure": False, "docker_failure": False, "shutdown_pending": False}
        cpu_pending, docker_pending = asyncio.Event(), asyncio.Event()

        def forbidden(*args, **kwargs):
            forbidden_calls.append(args)
            raise AssertionError("Joint runtime test must not start real processes or connections")

        # Install IO guards inside the active test event loop.
        for name in ("create_subprocess_exec", "create_subprocess_shell", "open_connection"):
            monkeypatch.setattr(asyncio, name, forbidden)
        monkeypatch.setattr(subprocess, "Popen", forbidden)
        for name in ("create_connection", "getaddrinfo"):
            monkeypatch.setattr(socket, name, forbidden)
        for name in ("connect", "connect_ex"):
            monkeypatch.setattr(socket.socket, name, forbidden)

        class RawHardwareIO:
            def __init__(self, *, timeout=3.0):
                self.timeout = timeout
                self.calls = []
                self.cpu_reads = 0
                self.cancelled = False
                self.close_calls = 0
                self.closed_after_restore = False
                hardware_ports.append(self)

            async def read_text(self, path):
                self.calls.append(("read", path))
                if path == "/proc/stat":
                    self.cpu_reads += 1
                    if phase["shutdown_pending"]:
                        cpu_pending.set()
                        try:
                            await asyncio.Future()
                        except asyncio.CancelledError:
                            self.cancelled = True
                            raise
                    if phase["cpu_failure"]:
                        raise PermissionError("PRIVATE_HARDWARE_FAILURE")
                    ticks = 100 + 50 * self.cpu_reads
                    return f"cpu {ticks} 0 0 {ticks} 0 0 0 0\n"
                if path == "/proc/meminfo":
                    return "MemTotal: 16777216 kB\nMemAvailable: 12582912 kB\n"
                if path == "/proc/self/mountinfo":
                    return MOUNTINFO
                raise AssertionError(path)

            async def statvfs(self, path):
                self.calls.append(("statvfs", path))
                assert path == "/"
                return hardware.FileSystemStat(4096, 100 * 2**18, 75 * 2**18)

            async def run(self, argv):
                self.calls.append(("run", argv))
                inventory = ("nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader,nounits")
                if argv == inventory:
                    return hardware.CommandOutput(0, f"0, {GPU_UUIDS[0]}\n")
                assert argv == (
                    "nvidia-smi",
                    "--query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                    "--format=csv,noheader,nounits", f"--id={GPU_UUIDS[0]}",
                )
                return hardware.CommandOutput(0, f"0, {GPU_UUIDS[0]}, Joint GPU, 25, 8192, 16384, 60, 100\n")

            async def close(self):
                self.close_calls += 1
                self.closed_after_restore = terminal.restored

        class RawDockerCommand:
            def __init__(self):
                self.calls = []
                self.cancelled = False
                self.close_calls = 0
                self.closed_after_restore = False
                docker_ports.append(self)

            async def run(self, argv, *, timeout):
                self.calls.append((argv, timeout))
                assert argv[:-1] == (
                    "docker", "--host", docker.LOCAL_DOCKER_HOST, "container", "inspect",
                    "--format", docker.DOCKER_INSPECT_TEMPLATE, "--",
                )
                target = argv[-1]
                assert target in ("joint-container", "hidden-container")
                if target == "joint-container":
                    if phase["shutdown_pending"]:
                        docker_pending.set()
                        try:
                            await asyncio.Future()
                        except asyncio.CancelledError:
                            self.cancelled = True
                            raise
                    if phase["docker_failure"]:
                        return docker.CommandOutput(1, stderr=b"No such container: PRIVATE_DOCKER_FAILURE")
                payload = {"Id": "a" * 64, "Name": "/" + target, "State": {"Status": "running"}}
                return docker.CommandOutput(0, json.dumps(payload).encode("utf-8"))

            async def close(self):
                self.close_calls += 1
                self.closed_after_restore = terminal.restored

        monkeypatch.setattr(cli, "CursesTerminal", lambda: terminal)
        monkeypatch.setattr(hardware, "LocalHardwareIO", RawHardwareIO)
        config = AppConfig(
            sample_interval=0.1, collection_timeout=3.0, mount_points=("/",),
            # Reusing 'cpu' proves collector namespaces isolate state and errors.
            containers=(ContainerConfig("cpu", "joint-container"), ContainerConfig("other", "hidden-container")),
            logging=LogConfig(directory=tmp_path / "logs"),
        )
        runtime = cli.ApplicationRuntime(config, docker_command_factory=RawDockerCommand)
        task = None

        def objects():
            return {(item.key.collector, item.key.object_id): item
                    for item in runtime.components.app.reader.snapshot().objects}

        async def until(predicate):
            deadline = asyncio.get_running_loop().time() + 2
            while not predicate():
                if task.done():
                    await task
                    raise AssertionError("Joint runtime stopped before the expected state")
                assert asyncio.get_running_loop().time() < deadline, "Joint runtime did not reach the expected state"
                await asyncio.sleep(0.005)

        expected = {("host", "cpu"), ("host", "ram"), ("storage", "mount-0"),
                    ("gpu_inventory", "local"), ("gpu", GPU_UUIDS[0]), ("docker", "cpu"), ("docker", "other")}
        try:
            assert runtime.prepare_log()
            components = runtime.components
            assert len(hardware_ports) == 4 and len(docker_ports) == 2
            assert all(not port.calls for port in hardware_ports + docker_ports)
            task = asyncio.create_task(runtime.run())
            await until(lambda: set(objects()) == expected
                        and all(len(item.history) >= 2 for item in objects().values()))
            await until(lambda: terminal.frames and "Joint GPU" in region_text(terminal.frames[-1], "gpu")
                        and "50.0%" in region_text(terminal.frames[-1], "host")
                        and has_capacity_numbers(region_text(terminal.frames[-1], "storage"), "25", "100")
                        and "Running" in region_text(terminal.frames[-1], "docker"))
            initial = terminal.frames[-1]
            assert "cpu" in region_text(initial, "docker")
            assert "other" not in region_text(initial, "docker")
            assert all(not item.stale for item in objects().values())
            assert len(hardware_ports) == 5  # Four static/discovery ports plus the discovered GPU.
            assert all(len(port.calls) >= 2 for port in hardware_ports + docker_ports)

            docker_samples = {key: item.sampled_at for key, item in objects().items() if key[0] == "docker"}
            phase["cpu_failure"] = True
            await until(lambda: objects()[("host", "cpu")].stale
                        and all(objects()[key].sampled_at > at for key, at in docker_samples.items()))
            await until(lambda: "STALE" in region_text(terminal.frames[-1], "host"))
            hardware_failed = terminal.frames[-1]
            assert {key for key, item in objects().items() if item.stale} == {("host", "cpu")}
            assert "STALE" not in region_text(hardware_failed, "docker")
            assert "Running" in region_text(hardware_failed, "docker")

            phase["cpu_failure"], phase["docker_failure"] = False, True
            await until(lambda: objects()[("docker", "cpu")].stale
                        and not objects()[("host", "cpu")].stale
                        and objects()[("host", "cpu")].metrics[0].value == 50)
            await until(lambda: "STALE" in region_text(terminal.frames[-1], "docker")
                        and "STALE" not in region_text(terminal.frames[-1], "host"))
            docker_failed = terminal.frames[-1]
            assert {key for key, item in objects().items() if item.stale} == {("docker", "cpu")}
            assert objects()[("docker", "cpu")].metrics[0].value == "Running"
            assert objects()[("docker", "cpu")].history[-1].metrics is None
            assert initial.regions == hardware_failed.regions == docker_failed.regions
            assert set(objects()) == expected and runtime.components is components

            phase["docker_failure"] = False
            await until(lambda: not objects()[("docker", "cpu")].stale)
            phase["shutdown_pending"] = True
            await until(lambda: cpu_pending.is_set() and docker_pending.is_set())
            before_quit = {key: objects()[key].sampled_at for key in (("host", "cpu"), ("docker", "cpu"))}
            terminal.keys.put_nowait("q")
            await asyncio.wait_for(task, 1.1)
            assert all(objects()[key].sampled_at == at and not objects()[key].stale
                       for key, at in before_quit.items())
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await runtime.close()

        assert terminal.entered and terminal.restored
        assert sum(port.cancelled for port in hardware_ports) == 1
        assert sum(port.cancelled for port in docker_ports) == 1
        assert all(port.close_calls == 1 and port.closed_after_restore for port in hardware_ports + docker_ports)
        assert all(port.timeout == config.collection_timeout for port in hardware_ports)
        assert all(timeout == config.collection_timeout for port in docker_ports for _, timeout in port.calls)
        records = [json.loads(line) for line in (config.logging.directory / "error.log").read_text().splitlines()]
        assert [(entry["collector"], entry["object_id"], entry["kind"]) for entry in records] == [
            ("host", "cpu", "permission"), ("docker", "cpu", "not_found")]
        assert all("PRIVATE" not in cell.text for frame in terminal.frames for cell in frame.cells)
        assert all("PRIVATE" not in json.dumps(entry) for entry in records)
        assert forbidden_calls == []
        assert "25 / 100 GiB · 25.0%" in region_text(initial, "storage")

    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")
