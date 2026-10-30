"""REQ-003 离线链路：真实 Docker 解析/采集、Monitor、State、Frame 与日志。

只替换命令进程、时钟和终端边界；不注入 CollectionResult 或采集业务结果。
所有外部进程/连接入口在本模块测试期间关闭，不能误用本机 Docker。
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import json
import socket
import subprocess

import pytest

from joi_observer.cli import ApplicationRuntime, RuntimeComponents
from joi_observer.collectors import hardware
from joi_observer.collectors.docker import CommandOutput, DockerCollector
from joi_observer.config import AppConfig, ContainerConfig, LogConfig
from joi_observer.data.state import MonitorState
from joi_observer.error_log import ErrorLog
from joi_observer.monitor import Monitor
from joi_observer.tui.app import ObserverApp
from joi_observer.tui.layout import HostInfo, TerminalSize, compose_frame


NOW = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def forbid_real_processes_and_connections(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Docker integration tests must use offline command ports.")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.fixture(autouse=True)
def offline_hardware_io(monkeypatch):
    """Merged production assembly also samples hardware; replace only raw IO.

    Keep real hardware parsing and scheduling active so strict error-log
    assertions still detect any unexpected failure across the shared runtime.
    """

    class RawHardwareIO:
        def __init__(self, *, timeout=3.0):
            self.cpu_reads = 0

        async def read_text(self, path):
            await asyncio.sleep(0)
            if path == "/proc/stat":
                self.cpu_reads += 1
                ticks = 100 * self.cpu_reads
                return f"cpu {ticks} 0 0 {ticks} 0 0 0 0\n"
            if path == "/proc/meminfo":
                return "MemTotal: 16777216 kB\nMemAvailable: 12582912 kB\n"
            if path == "/proc/self/mountinfo":
                return ("10 1 8:1 / / rw - ext4 /dev/root rw\n"
                        "11 10 8:2 / /data rw - ext4 /dev/data rw\n")
            raise AssertionError(f"Unexpected hardware file request: {path}")

        async def statvfs(self, path):
            await asyncio.sleep(0)
            assert path in ("/", "/data")
            return hardware.FileSystemStat(4096, 100 * 2**18, 75 * 2**18)

        async def run(self, argv):
            await asyncio.sleep(0)
            assert argv == ("nvidia-smi", "--query-gpu=index,uuid",
                            "--format=csv,noheader,nounits")
            return hardware.CommandOutput(0, "")

        async def close(self):
            pass

    monkeypatch.setattr(hardware, "LocalHardwareIO", RawHardwareIO)


class RawCommand:
    """外部命令替身，仅返回原始字节；状态匹配/解析仍由被测代码完成。"""

    def __init__(self, *, status="running", blocked=False):
        self.status = status
        self.error = None
        self.calls = []
        self.closed = False
        self.cancelled = False
        self.gate = asyncio.Event()
        if not blocked:
            self.gate.set()

    async def run(self, argv, *, timeout):
        self.calls.append((argv, timeout))
        try:
            await self.gate.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if isinstance(self.error, BaseException):
            raise self.error
        if isinstance(self.error, CommandOutput):
            return self.error
        if self.error is not None:
            return CommandOutput(1, stderr=self.error)
        payload = {
            "Id": "a" * 64,
            "Name": "/" + argv[-1],
            "State": {"Status": self.status},
        }
        return CommandOutput(0, json.dumps(payload).encode("utf-8"))

    async def close(self):
        self.closed = True


def configuration(tmp_path, count=10):
    return AppConfig(
        containers=tuple(ContainerConfig(f"docker-{i}", f"container-{i:02d}") for i in range(count)),
        logging=LogConfig(directory=tmp_path / "logs"),
    )


async def sample(monitor, clock, at):
    clock[0] = at
    for _ in range(10):
        await monitor.poll()
        await asyncio.sleep(0)


def frame_text(frame):
    return " ".join(cell.text for cell in frame.cells)


def visible_names(frame, config):
    configured = {item.name for item in config.containers}
    return [cell.text for cell in frame.cells if cell.text in configured]


def row_status(frame, name):
    row = next(cell.row for cell in frame.cells if cell.text == name)
    return [cell.text for cell in frame.cells if cell.row == row and cell.text != name]


def test_all_raw_docker_sources_sample_while_hidden_and_recover_without_layout_change(tmp_path, capsys):
    """AC-301～304：十个真采集器、原始失败、隐藏项恢复和 4→6→3 容量。"""
    async def scenario():
        config = configuration(tmp_path)
        commands = [RawCommand(status="exited" if i == 1 else "running") for i in range(10)]
        collectors = tuple(DockerCollector(item, command=command)
                           for item, command in zip(config.containers, commands))
        log = ErrorLog(config.logging)
        assert log.prepare()
        clock = [0.0]
        state = MonitorState(tuple(item.spec for item in collectors), clock=lambda: clock[0])
        monitor = Monitor(collectors, state, log, clock=lambda: clock[0], wall_clock=lambda: NOW)

        def frame_at(rows):
            return compose_frame(state.snapshot(), config, TerminalSize(120, rows),
                                 HostInfo("offline-host", "Ubuntu"), NOW)

        try:
            initial = frame_at(44)
            assert "—" in frame_text(initial) and "STALE" not in frame_text(initial)
            await sample(monitor, clock, 0)
            assert [len(command.calls) for command in commands] == [1] * 10
            ready = frame_at(44)
            assert visible_names(ready, config) == [item.name for item in config.containers[:4]]
            assert "Exited" in row_status(ready, config.containers[1].name)
            assert all(not item.stale for item in state.snapshot().objects)
            assert await log.flush()
            log_path = config.logging.directory / "error.log"
            assert log_path.read_text(encoding="utf-8") == ""

            commands[5].error = b"permission denied: SECRET_CREDENTIAL"
            await sample(monitor, clock, 1)
            assert [len(command.calls) for command in commands] == [2] * 10
            failed = state.snapshot()
            assert failed.objects[5].stale
            assert failed.objects[5].metrics[0].value == "Running"
            assert failed.objects[5].history[-1].metrics is None
            assert "STALE" not in frame_text(frame_at(44))
            expanded = frame_at(48)
            assert visible_names(expanded, config) == [item.name for item in config.containers[:6]]
            assert "STALE" in row_status(expanded, config.containers[5].name)
            assert visible_names(frame_at(42), config) == [item.name for item in config.containers[:3]]
            assert [len(command.calls) for command in commands] == [2] * 10
            assert await log.flush()
            entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            assert [(entry["collector"], entry["object_id"], entry["kind"], entry["code"])
                    for entry in entries] == [("docker", "docker-5", "permission", "access.denied")]

            commands[5].error = None
            commands[5].status = "restarting"
            await sample(monitor, clock, 2)
            recovered = frame_at(48)
            assert [len(command.calls) for command in commands] == [3] * 10
            assert "Restarting" in row_status(recovered, config.containers[5].name)
            assert "STALE" not in frame_text(recovered)
            assert recovered.regions == expanded.regions
            assert state.snapshot().objects[5].history[-1].metrics[0].value == "Restarting"
            assert len(config.containers) == len(state.snapshot().objects) == 10
            assert await log.flush()
            assert len(log_path.read_text(encoding="utf-8").splitlines()) == 1
            combined = log_path.read_text(encoding="utf-8") + repr(state.snapshot()) + frame_text(recovered)
            assert "SECRET_CREDENTIAL" not in combined and "permission denied" not in frame_text(expanded)
            for frame, rows in ((ready, 44), (expanded, 48), (recovered, 48), (frame_at(42), 42)):
                assert not frame.too_small
                assert all(word not in frame_text(frame).lower()
                           for word in ("enlarge", "hidden", "more", "overflow", "page ", "...", "…"))
                service = next(region for region in frame.regions if region.name == "service")
                assert service.row == rows - rows // 2
        finally:
            await monitor.stop()
            await log.close()
        assert all(command.closed for command in commands)

    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("failure,kind,code", [
    (CommandOutput(1, stderr=b"No such container: SECRET_CREDENTIAL"),
     "not_found", "object.not_found"),
    (CommandOutput(1, stderr=b"Cannot connect to Docker: SECRET_CREDENTIAL"),
     "unavailable", "source.unavailable"),
    (CommandOutput(0, stdout=b"SECRET_CREDENTIAL is not JSON"),
     "parse", "response.invalid"),
    (TimeoutError("SECRET_CREDENTIAL"), "timeout", "collection.timeout"),
])
def test_docker_failure_categories_keep_values_layout_and_recover(
        tmp_path, capsys, failure, kind, code):
    """AC-302/303：命令错误经真实业务链路分类，不泄漏原文且下轮可恢复。"""
    async def scenario():
        config = configuration(tmp_path, count=1)
        command = RawCommand()
        collector = DockerCollector(config.containers[0], command=command)
        clock = [0.0]
        state = MonitorState((collector.spec,), clock=lambda: clock[0])
        log = ErrorLog(config.logging)
        assert log.prepare()
        monitor = Monitor((collector,), state, log, clock=lambda: clock[0], wall_clock=lambda: NOW)

        def frame():
            return compose_frame(state.snapshot(), config, TerminalSize(120, 44),
                                 HostInfo("offline-host", "Ubuntu"), NOW)

        try:
            await sample(monitor, clock, 0)
            ready = frame()
            assert "Running" in row_status(ready, config.containers[0].name)
            command.error = failure
            await sample(monitor, clock, 1)
            failed = state.snapshot().objects[0]
            stale = frame()
            assert failed.stale and failed.metrics[0].value == "Running"
            assert failed.history[-1].metrics is None
            assert stale.regions == ready.regions
            assert "STALE" in row_status(stale, config.containers[0].name)
            assert await log.flush()
            log_path = config.logging.directory / "error.log"
            entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            assert [(entry["collector"], entry["object_id"], entry["kind"], entry["code"])
                    for entry in entries] == [("docker", "docker-0", kind, code)]
            assert "SECRET_CREDENTIAL" not in (
                log_path.read_text(encoding="utf-8") + repr(state.snapshot()) + frame_text(stale))

            command.error = None
            command.status = "restarting"
            await sample(monitor, clock, 2)
            recovered = state.snapshot().objects[0]
            recovery_frame = frame()
            assert not recovered.stale and recovered.metrics[0].value == "Restarting"
            assert recovered.history[-1].metrics[0].value == "Restarting"
            assert "Restarting" in row_status(recovery_frame, config.containers[0].name)
            assert "STALE" not in frame_text(recovery_frame)
            assert recovery_frame.regions == ready.regions
            assert len(command.calls) == 3
            assert await log.flush()
            assert len(log_path.read_text(encoding="utf-8").splitlines()) == 1
        finally:
            await monitor.stop()
            await log.close()
        assert command.closed

    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


def test_slow_docker_command_does_not_block_sibling_and_cancel_is_not_failure(tmp_path, capsys):
    """真实采集器必须传播取消；慢容器不阻塞另一容器或制造关闭错误。"""
    async def scenario():
        config = configuration(tmp_path, count=2)
        slow, fast = RawCommand(blocked=True), RawCommand(status="exited")
        collectors = tuple(DockerCollector(item, command=command)
                           for item, command in zip(config.containers, (slow, fast)))
        clock = [0.0]
        state = MonitorState(tuple(item.spec for item in collectors), clock=lambda: clock[0])
        log = ErrorLog(config.logging)
        assert log.prepare()
        monitor = Monitor(collectors, state, log, timeout=3, clock=lambda: clock[0])
        try:
            await asyncio.wait_for(sample(monitor, clock, 0), 0.5)
            await asyncio.wait_for(sample(monitor, clock, 1), 0.5)
            assert (len(slow.calls), len(fast.calls)) == (1, 2)
            snapshot = state.snapshot()
            assert snapshot.objects[0].sampled_at is None
            assert not snapshot.objects[0].stale
            assert snapshot.objects[1].metrics[0].value == "Exited"
        finally:
            await asyncio.wait_for(monitor.stop(), 1.1)
            await log.close()
        assert slow.cancelled and slow.closed and fast.closed
        assert (config.logging.directory / "error.log").read_text(encoding="utf-8") == ""

    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


class MemoryTerminal:
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
        return TerminalSize(120, 44)

    def render(self, frame):
        self.frames.append(frame)

    async def read_key(self, timeout):
        try:
            return await asyncio.wait_for(self.keys.get(), timeout)
        except TimeoutError:
            return None


def test_production_runtime_connects_every_configured_docker_collector(tmp_path, monkeypatch, capsys):
    """生产装配必须真正采集十项；注册十个未知模板不能满足本测试。"""
    async def scenario():
        config = replace(configuration(tmp_path), collection_timeout=0.7)
        terminal = MemoryTerminal()
        commands = []

        def command_factory():
            command = RawCommand()
            commands.append(command)
            return command

        monkeypatch.setattr("joi_observer.cli.CursesTerminal", lambda: terminal)
        runtime = ApplicationRuntime(config, docker_command_factory=command_factory)
        assert commands == []
        assert runtime.prepare_log()
        assert len(commands) == 10
        assert all(not command.calls for command in commands)
        task = asyncio.create_task(runtime.run())
        try:
            deadline = asyncio.get_running_loop().time() + 0.8
            while True:
                objects = [item for item in runtime.components.app.reader.snapshot().objects
                           if item.key.collector == "docker"]
                if len(objects) == 10 and all(item.sampled_at is not None for item in objects):
                    break
                assert not task.done(), "Production runtime exited before collecting Docker state."
                if asyncio.get_running_loop().time() >= deadline:
                    pytest.fail("Production runtime did not sample all ten configured Docker containers.")
                await asyncio.sleep(0.005)
            assert len(commands) == 10
            assert all(command.calls for command in commands)
            assert all(timeout == config.collection_timeout
                       for command in commands for _, timeout in command.calls)
            assert {call[0][-1] for command in commands for call in command.calls} == {
                item.name for item in config.containers
            }
            assert [item.key.object_id for item in objects] == [item.id for item in config.containers]
            assert all(not item.stale and item.metrics[0].value == "Running" for item in objects)
            assert terminal.entered and terminal.frames
            assert visible_names(terminal.frames[0], config) == [item.name for item in config.containers[:4]]
        finally:
            terminal.keys.put_nowait("q")
            try:
                await asyncio.wait_for(task, 1.2)
            finally:
                await runtime.close()
        assert terminal.restored and all(command.closed for command in commands)
        assert (config.logging.directory / "error.log").read_text(encoding="utf-8") == ""

    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


def test_prepare_without_run_owns_and_closes_all_commands_without_sampling(tmp_path, monkeypatch):
    """准备后启动被中止时，已组装端口仍关闭；重复 prepare/close 不重建资源。"""
    async def scenario():
        config = configuration(tmp_path, count=2)
        terminal = MemoryTerminal()
        commands = []

        class CountingCommand(RawCommand):
            def __init__(self):
                super().__init__()
                self.close_calls = 0

            async def close(self):
                self.close_calls += 1
                await super().close()

        def command_factory():
            command = CountingCommand()
            commands.append(command)
            return command

        monkeypatch.setattr("joi_observer.cli.CursesTerminal", lambda: terminal)
        runtime = ApplicationRuntime(config, docker_command_factory=command_factory)
        assert commands == []
        assert not config.logging.directory.exists()
        assert runtime.prepare_log()
        components = runtime.components
        assert runtime.prepare_log()
        assert runtime.components is components
        assert len(commands) == 2 and all(not command.calls for command in commands)
        assert not terminal.entered
        await runtime.close()
        await runtime.close()
        assert all(command.close_calls == 1 and not command.calls for command in commands)
        assert not terminal.entered
        assert (config.logging.directory / "error.log").read_text(encoding="utf-8") == ""

    asyncio.run(scenario())


def test_empty_production_configuration_never_creates_docker_port(tmp_path, monkeypatch):
    async def scenario():
        config = configuration(tmp_path, count=0)
        terminal = MemoryTerminal()
        terminal.keys.put_nowait("q")

        def forbidden_factory():
            pytest.fail("Empty Docker configuration must not construct a command port.")

        monkeypatch.setattr("joi_observer.cli.CursesTerminal", lambda: terminal)
        runtime = ApplicationRuntime(config, docker_command_factory=forbidden_factory)
        assert runtime.prepare_log()
        try:
            await runtime.run()
            assert all(item.key.collector != "docker"
                       for item in runtime.components.app.reader.snapshot().objects)
            assert "No containers configured" in frame_text(terminal.frames[0])
        finally:
            await runtime.close()
        assert terminal.restored

    asyncio.run(scenario())


def test_injected_components_keep_sole_sampling_and_cleanup_ownership(tmp_path):
    """注入已有组合后不创建第二套 Docker 来源、State 或日志。"""
    async def scenario():
        config = configuration(tmp_path, count=1)
        command = RawCommand(status="paused")
        collector = DockerCollector(config.containers[0], command=command)
        state = MonitorState((collector.spec,))
        log = ErrorLog(config.logging)
        monitor = Monitor((collector,), state, log)
        terminal = MemoryTerminal()
        app = ObserverApp(config, state, terminal, host=HostInfo("offline-host", "Ubuntu"),
                          wall_clock=lambda: NOW)
        components = RuntimeComponents(monitor, app, log)

        def forbidden_factory():
            pytest.fail("Injected components must retain sole ownership of their sources.")

        runtime = ApplicationRuntime(config, components=components,
                                     docker_command_factory=forbidden_factory)
        assert runtime.prepare_log()
        assert runtime.components is components and not command.calls
        task = asyncio.create_task(runtime.run())
        try:
            deadline = asyncio.get_running_loop().time() + 0.8
            while state.snapshot().objects[0].sampled_at is None:
                assert not task.done()
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.005)
            assert runtime.components is components
            assert app.reader.snapshot() == state.snapshot()
            assert state.snapshot().objects[0].metrics[0].value == "Paused"
            assert len(command.calls) == 1
        finally:
            terminal.keys.put_nowait("q")
            try:
                await asyncio.wait_for(task, 1.2)
            finally:
                await runtime.close()
        assert command.closed and terminal.restored
        assert (config.logging.directory / "error.log").read_text(encoding="utf-8") == ""

    asyncio.run(scenario())


def test_production_timeout_recovers_and_quit_cancels_next_pending_docker_sample(
        tmp_path, monkeypatch, capsys):
    """真实定时超时、恢复和 q 退出贯穿生产组装，不以预设 TimeoutError 代替。"""
    async def scenario():
        config = replace(configuration(tmp_path, count=2),
                         sample_interval=0.1, collection_timeout=0.1)
        terminal = MemoryTerminal()

        class ObservedCommand(RawCommand):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.closed_after_restore = None

            async def close(self):
                self.closed_after_restore = terminal.restored
                await super().close()

        slow = ObservedCommand(blocked=True)
        fast = ObservedCommand(status="exited")
        commands = iter((slow, fast))
        monkeypatch.setattr("joi_observer.cli.CursesTerminal", lambda: terminal)
        runtime = ApplicationRuntime(config, docker_command_factory=lambda: next(commands))
        assert runtime.prepare_log()
        task = asyncio.create_task(runtime.run())

        def docker_objects():
            return [item for item in runtime.components.app.reader.snapshot().objects
                    if item.key.collector == "docker"]

        async def until(predicate):
            deadline = asyncio.get_running_loop().time() + 0.8
            while not predicate():
                assert not task.done(), "Docker timeout must not stop the production runtime."
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.005)

        try:
            await until(lambda: docker_objects()[0].stale)
            first, sibling = docker_objects()
            assert slow.cancelled
            assert first.metrics[0].value is None and first.history[-1].metrics is None
            assert sibling.metrics[0].value == "Exited" and not sibling.stale
            await until(lambda: any("STALE" in row_status(frame, config.containers[0].name)
                                    for frame in terminal.frames))
            stale_frame = terminal.frames[-1]
            assert await runtime.components.error_log.flush()
            log_path = config.logging.directory / "error.log"
            entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            assert [(entry["object_id"], entry["kind"], entry["code"]) for entry in entries] == [
                ("docker-0", "timeout", "collection.timeout")]

            slow.status = "restarting"
            slow.gate.set()
            await until(lambda: not docker_objects()[0].stale)
            await until(lambda: "Restarting" in row_status(terminal.frames[-1], config.containers[0].name))
            recovered = docker_objects()[0]
            assert recovered.metrics[0].value == "Restarting"
            assert recovered.history[-1].metrics[0].value == "Restarting"
            assert terminal.frames[-1].regions == stale_frame.regions
            assert "STALE" not in row_status(terminal.frames[-1], config.containers[0].name)
            assert len(fast.calls) >= 2

            # Leave a new real collection await pending when q is delivered.
            slow.gate.clear()
            slow.cancelled = False
            previous_calls = len(slow.calls)
            await until(lambda: len(slow.calls) > previous_calls)
            last_sample = docker_objects()[0].sampled_at
            terminal.keys.put_nowait("q")
            await asyncio.wait_for(task, 1.1)
            assert slow.cancelled and not slow.gate.is_set()
            assert terminal.restored
            assert all(command.closed and command.closed_after_restore for command in (slow, fast))
            assert docker_objects()[0].sampled_at == last_sample
            assert not docker_objects()[0].stale
            assert len(log_path.read_text(encoding="utf-8").splitlines()) == 1
        finally:
            if not task.done():
                terminal.keys.put_nowait("q")
                await asyncio.wait_for(task, 1.1)
            await runtime.close()

    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")
