"""Offline regression for the combined hardware and Docker production runtime."""

import asyncio
import json
import socket
import subprocess

from joi_observer import cli
from joi_observer.collectors import docker, hardware
from joi_observer.config import AppConfig, ContainerConfig, LogConfig
from joi_observer.data.models import ObjectKey
from joi_observer.tui.layout import TerminalSize


GPU_UUIDS = tuple(f"GPU-00000000-0000-0000-0000-{index + 1:012d}" for index in range(2))


class RecordingTerminal:
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
        return TerminalSize(120, 48)

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


def metrics(item):
    return {metric.name: metric.value for metric in item.metrics}


def test_combined_runtime_samples_both_sources_discovers_new_gpu_and_closes_ports(
        tmp_path, monkeypatch, capsys):
    async def scenario():
        phase = {"expanded": False}
        hardware_ports = []
        docker_ports = []
        calls = []
        forbidden_calls = []

        def forbidden(*args, **kwargs):
            forbidden_calls.append(args)
            raise AssertionError("Combined runtime test must use offline IO ports.")

        # Install after asyncio has created its local wakeup mechanism on Windows.
        for owner, name in (
            (asyncio, "create_subprocess_exec"), (asyncio, "create_subprocess_shell"),
            (asyncio, "open_connection"), (subprocess, "Popen"),
            (socket, "create_connection"), (socket, "getaddrinfo"),
            (socket.socket, "connect"), (socket.socket, "connect_ex"),
        ):
            monkeypatch.setattr(owner, name, forbidden)

        class RawHardwareIO:
            def __init__(self, *, timeout):
                self.timeout = timeout
                self.cpu_reads = 0
                self.closed = False
                hardware_ports.append(self)

            async def read_text(self, path):
                calls.append(("read", path))
                if path == "/proc/stat":
                    self.cpu_reads += 1
                    ticks = 100 + self.cpu_reads * 50
                    return f"cpu {ticks} 0 0 {ticks} 0 0 0 0 0 0\n"
                if path == "/proc/meminfo":
                    return "MemTotal: 16777216 kB\nMemAvailable: 12582912 kB\n"
                assert path == "/proc/self/mountinfo"
                return "10 1 8:1 / / rw - ext4 /dev/root rw\n"

            async def statvfs(self, path):
                calls.append(("statvfs", path))
                assert path == "/"
                return hardware.FileSystemStat(4096, 100 * 2**18, 75 * 2**18)

            async def run(self, argv):
                calls.append(("gpu", argv))
                assert argv[0] == "nvidia-smi"
                if "--query-gpu=index,uuid" in argv:
                    count = 2 if phase["expanded"] else 1
                    return hardware.CommandOutput(0, "".join(
                        f"{index}, {uuid}\n" for index, uuid in enumerate(GPU_UUIDS[:count])))
                uuid = next(arg.removeprefix("--id=") for arg in argv if arg.startswith("--id="))
                index = GPU_UUIDS.index(uuid)
                return hardware.CommandOutput(
                    0, f"{index}, {uuid}, Offline GPU {index}, 25, 8192, 16384, 60, 100\n")

            async def close(self):
                self.closed = True

        class RawDockerCommand:
            def __init__(self):
                self.calls = []
                self.closed = False
                docker_ports.append(self)

            async def run(self, argv, *, timeout):
                self.calls.append((argv, timeout))
                calls.append(("docker", argv))
                assert argv[:5] == (
                    "docker", "--host", "unix:///var/run/docker.sock", "container", "inspect")
                assert argv[-1] == "offline-container"
                return docker.CommandOutput(0, json.dumps({
                    "Id": "a" * 64,
                    "Name": "/offline-container",
                    "State": {"Status": "exited" if phase["expanded"] else "running"},
                }).encode("utf-8"))

            async def close(self):
                self.closed = True

        terminal = RecordingTerminal()
        monkeypatch.setattr(hardware, "LocalHardwareIO", RawHardwareIO)
        monkeypatch.setattr(cli, "CursesTerminal", lambda: terminal)
        config = AppConfig(
            sample_interval=0.1, collection_timeout=0.5, mount_points=("/",),
            containers=(ContainerConfig("combined", "offline-container"),),
            logging=LogConfig(directory=tmp_path / "logs"),
        )
        runtime = cli.ApplicationRuntime(config, docker_command_factory=RawDockerCommand)
        task = None

        async def wait_frame(predicate):
            deadline = asyncio.get_running_loop().time() + 2
            while asyncio.get_running_loop().time() < deadline:
                for frame in reversed(terminal.frames):
                    if not frame.too_small and predicate(frame):
                        return frame
                if task.done():
                    await task
                    raise AssertionError("Runtime stopped before the combined frame was drawn.")
                await asyncio.sleep(0.005)
            raise AssertionError("Combined hardware/Docker frame was not drawn.")

        try:
            assert runtime.prepare_log()
            assert calls == []
            assert len(docker_ports) == 1
            assert len(hardware_ports) == 4  # CPU, RAM, mount and GPU inventory.
            components = runtime.components
            assert not hasattr(components.app.reader, "accept")
            task = asyncio.create_task(runtime.run())
            initial_frame = await wait_frame(lambda frame:
                "Offline GPU 0" in region_text(frame, "gpu")
                and "50%" in region_text(frame, "host")
                and "4.0 GiB" in region_text(frame, "host")
                and "25.0 GiB" in region_text(frame, "storage")
                and "offline-container" in region_text(frame, "docker")
                and "Running" in region_text(frame, "docker"))
            initial = components.app.reader.snapshot()
            assert initial == components.monitor._state.snapshot()
            initial_objects = {item.key: item for item in initial.objects}
            assert metrics(initial_objects[ObjectKey("host", "cpu")])["cpu_percent"] == 50
            assert metrics(initial_objects[ObjectKey("host", "ram")])["ram_used_bytes"] == 4 * 2**30
            assert metrics(initial_objects[ObjectKey("storage", "mount-0")])["used_bytes"] == 25 * 2**30
            assert initial_objects[ObjectKey("docker", "combined")].metrics[0].value == "Running"
            assert [item.key.object_id for item in initial.objects if item.key.collector == "gpu"] == [GPU_UUIDS[0]]
            assert all(item.sampled_at is not None and not item.stale for item in initial.objects)

            # The next raw inventory adds a card while Docker continues sampling.
            phase["expanded"] = True
            expanded_frame = await wait_frame(lambda frame:
                "Offline GPU 0" in region_text(frame, "gpu")
                and "Offline GPU 1" in region_text(frame, "gpu")
                and "Exited" in region_text(frame, "docker"))
            expanded = components.app.reader.snapshot()
            expanded_objects = {item.key: item for item in expanded.objects}
            assert expanded == components.monitor._state.snapshot()
            assert runtime.components is components
            assert expanded.revision > initial.revision
            assert [item.key.object_id for item in expanded.objects if item.key.collector == "gpu"] == list(GPU_UUIDS)
            assert metrics(expanded_objects[ObjectKey("gpu_inventory", "local")])["device_count"] == 2
            old_gpu = initial_objects[ObjectKey("gpu", GPU_UUIDS[0])]
            assert expanded_objects[old_gpu.key].history[:len(old_gpu.history)] == old_gpu.history
            assert expanded_objects[ObjectKey("docker", "combined")].metrics[0].value == "Exited"
            assert len(expanded_objects[ObjectKey("docker", "combined")].history) >= 2
            assert all(item.sampled_at is not None and not item.stale for item in expanded.objects)
            assert "Offline GPU 1" not in region_text(initial_frame, "gpu")
            assert "50%" in region_text(expanded_frame, "host")
            assert "25.0 GiB" in region_text(expanded_frame, "storage")
            assert len(hardware_ports) == 6  # Each discovered UUID owns one new port.
            terminal.keys.put_nowait("q")
            await asyncio.wait_for(task, 1.2)
            # Assert normal shutdown before the emergency cleanup in finally.
            assert terminal.entered and terminal.restored
            assert all(port.closed for port in hardware_ports + docker_ports)
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await runtime.close()

        assert forbidden_calls == []
        assert all(port.timeout == config.collection_timeout for port in hardware_ports)
        assert len(docker_ports) == 1 and len(docker_ports[0].calls) >= 2
        assert all(timeout == config.collection_timeout for _, timeout in docker_ports[0].calls)
        assert (config.logging.directory / "error.log").read_bytes() == b""

    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")
