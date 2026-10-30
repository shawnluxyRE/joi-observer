"""REQ-001 公共链路离线集成：只替换采集、终端、时钟和文件故障边界。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import threading

import pytest

from joi_observer.config import AppConfig, ContainerConfig, LogConfig, load_config
from joi_observer.data.models import CollectionResult, Metric, ObjectKey, ObjectSpec
from joi_observer.data.state import MonitorState
from joi_observer.error_log import ErrorKind, ErrorLog, Failure, FileLogIO
from joi_observer.monitor import Monitor
from joi_observer.tui.app import ObserverApp
from joi_observer.tui.layout import HostInfo, TerminalSize, ViewSelection, compose_frame


NOW = datetime(2026, 10, 28, 18, 0, tzinfo=timezone(timedelta(hours=8)))
TIMEOUT = Failure(ErrorKind.TIMEOUT, "collection.timeout", "PRIVATE source detail")
PERMISSION = Failure(ErrorKind.PERMISSION, "access.denied", "PRIVATE permission detail")


class OfflineSource:
    def __init__(self, object_id, *, collector="vllm", failure=None, blocked=False):
        self.spec = ObjectSpec(ObjectKey(collector, object_id), (Metric("RUNNING", None),))
        self.failure = failure
        self.calls = 0
        self.value = None
        self.closed = False
        self.cancelled = False
        self.gate = asyncio.Event()
        if not blocked:
            self.gate.set()

    async def collect(self):
        self.calls += 1
        try:
            await self.gate.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if self.failure is not None:
            return CollectionResult(self.spec.key, failure=self.failure)
        value = self.calls if self.value is None else self.value
        return CollectionResult(self.spec.key, (Metric("RUNNING", value),))

    async def close(self):
        self.closed = True


class QueueTerminal:
    def __init__(self):
        self.keys = asyncio.Queue()
        self.frames = []
        self.entered = False
        self.restored = False

    def enter(self):
        self.entered = True

    def restore(self):
        self.restored = True

    def size(self):
        return TerminalSize(120, 40)

    def render(self, frame):
        self.frames.append(frame)

    async def read_key(self, timeout):
        try:
            return await asyncio.wait_for(self.keys.get(), timeout)
        except TimeoutError:
            return None


class Actions:
    """只观察 REQ-001 的展示操作端口分派，不实现后续导航与主题业务。"""

    def __init__(self):
        self.keys = []

    def selection(self):
        return ViewSelection("chat")

    def on_key(self, key):
        self.keys.append(key)


def config_for(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "mount_points: []\nmodels:\n"
        "  - {id: chat, type: chat, name: Chat, base_url: 'http://offline.invalid:8000'}\n"
        "  - {id: embedding, type: embedding, name: Embedding, base_url: 'http://offline.invalid:8001'}\n"
        "  - {id: reranker, type: reranker, name: Reranker, base_url: 'http://offline.invalid:8002'}\n"
        f"logging:\n  directory: {json.dumps(str(tmp_path / 'logs'))}\n",
        encoding="utf-8",
    )
    return load_config(path)


def text(frame):
    return " ".join(cell.text for cell in frame.cells)


async def until(predicate, *, timeout=0.6):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            pytest.fail("Offline integration did not reach the expected state.")
        await asyncio.sleep(0.002)


async def sample(monitor, clock, tick):
    clock[0] = tick
    for _ in range(5):
        await monitor.poll()
        await asyncio.sleep(0)


def harness(config, sources, log):
    clock = [0.0]
    state = MonitorState(tuple(source.spec for source in sources), clock=lambda: clock[0])
    updates = []
    monitor = Monitor(
        tuple(sources), state, log, interval=config.sample_interval, timeout=30,
        clock=lambda: clock[0], wall_clock=lambda: NOW + timedelta(seconds=clock[0]),
        on_update=lambda: updates.append(state.snapshot().revision),
    )
    terminal, actions = QueueTerminal(), Actions()
    app = ObserverApp(
        config, state, terminal, host=HostInfo("offline-host", "Ubuntu"),
        wall_clock=lambda: NOW + timedelta(seconds=clock[0]), actions=actions,
    )
    return monitor, state, clock, updates, terminal, actions, app


async def cleanup(running, monitor, log):
    if not running.done():
        running.cancel()
    await asyncio.gather(running, return_exceptions=True)
    await monitor.stop()
    await log.close()


def test_all_docker_sources_keep_sampling_and_logging_while_visibility_changes(tmp_path):
    """显示容量只作用于Frame；真实Monitor/State/日志处理全部十个离线对象。"""
    async def scenario():
        containers = tuple(ContainerConfig(f"docker-{i}", f"container-{i:02d}") for i in range(10))
        config = AppConfig(containers=containers, logging=LogConfig(directory=tmp_path / "logs"))
        sources = [OfflineSource(item.id, collector="docker") for item in containers]
        for source in sources:
            source.value = "Running"
        log = ErrorLog(config.logging)
        assert log.prepare()
        clock = [0.0]
        state = MonitorState(tuple(source.spec for source in sources), clock=lambda: clock[0])
        monitor = Monitor(tuple(sources), state, log, clock=lambda: clock[0], wall_clock=lambda: NOW)

        def frame_at(rows):
            return compose_frame(state.snapshot(), config, TerminalSize(120, rows),
                                 HostInfo("offline-host", "Ubuntu"), NOW)

        def names(frame):
            return [cell.text for cell in frame.cells if cell.text in {item.name for item in containers}]

        try:
            await sample(monitor, clock, 0)
            assert [source.calls for source in sources] == [1] * 10
            assert len(state.snapshot().objects) == 10
            initial = frame_at(44)
            assert not initial.too_small
            assert names(initial) == [item.name for item in containers[:4]]
            assert await log.flush()
            assert (config.logging.directory / "error.log").read_text(encoding="utf-8") == ""

            sources[5].failure = TIMEOUT
            await sample(monitor, clock, 1)
            assert [source.calls for source in sources] == [2] * 10
            assert state.snapshot().objects[5].stale
            assert await log.flush()
            entries = [json.loads(line) for line in
                       (config.logging.directory / "error.log").read_text(encoding="utf-8").splitlines()]
            assert [(entry["collector"], entry["object_id"]) for entry in entries] == [("docker", "docker-5")]
            assert "STALE" not in text(frame_at(44))

            expanded = frame_at(48)
            assert names(expanded) == [item.name for item in containers[:6]]
            assert "STALE" in text(expanded)
            assert names(frame_at(42)) == [item.name for item in containers[:3]]
            assert [source.calls for source in sources] == [2] * 10
            assert len(config.containers) == len(state.snapshot().objects) == 10
        finally:
            await monitor.stop()
            await log.close()
    asyncio.run(scenario())


def test_loaded_configuration_keeps_complete_sources_and_history_across_ui_resize(tmp_path, capsys):
    """从真实 YAML 接入全部离线来源；缩放仅改变 Frame 中的容器前缀。"""
    class ResizingTerminal(QueueTerminal):
        rows = 44

        def size(self):
            return TerminalSize(120, self.rows)

    async def scenario():
        path = tmp_path / "config.yaml"
        source_text = (
            "mount_points: ['/disk-first', '/disk-second', '/disk-third', "
            "{ignored: invalid-path}, '/disk-first', null]\n"
            "containers:\n"
            + "".join(f"  - {{id: docker-{i}, name: container-{i:02d}}}\n" for i in range(10))
            + f"logging:\n  directory: {json.dumps(str(tmp_path / 'logs'))}\n"
        )
        path.write_text(source_text, encoding="utf-8")
        original_bytes = path.read_bytes()
        config = load_config(path)
        assert config.mount_points == ("/disk-first", "/disk-second", "/disk-third")
        assert [item.id for item in config.containers] == [f"docker-{i}" for i in range(10)]
        assert path.read_bytes() == original_bytes

        # Identity is local to these offline ports, as in the R2 Frame tests;
        # this does not introduce a production hardware/storage adapter.
        mounts = [OfflineSource(mount, collector="storage") for mount in config.mount_points]
        containers = [OfflineSource(item.id, collector="docker") for item in config.containers]
        for source in containers:
            source.value = "Running"
        sources = [*mounts, *containers]
        clock = [0.0]
        state = MonitorState(tuple(source.spec for source in sources), clock=lambda: clock[0])
        log = ErrorLog(config.logging)
        assert log.prepare()
        log_path = config.logging.directory / "error.log"
        monitor = Monitor(tuple(sources), state, log, interval=config.sample_interval,
                          clock=lambda: clock[0], wall_clock=lambda: NOW + timedelta(seconds=clock[0]))
        terminal, actions = ResizingTerminal(), Actions()
        app = ObserverApp(config, state, terminal, host=HostInfo("offline-host", "Ubuntu"),
                          wall_clock=lambda: NOW + timedelta(seconds=clock[0]), actions=actions)
        names = [item.name for item in config.containers]

        def visible_names(frame):
            return [cell.text for cell in frame.cells if cell.text in names]

        def status_is(frame, name, value):
            row = next(cell.row for cell in frame.cells if cell.text == name)
            return any(cell.row == row and cell.text == value for cell in frame.cells)

        def region_text(frame, name):
            region = next(item for item in frame.regions if item.name == name)
            return " ".join(cell.text for cell in frame.cells
                            if region.row <= cell.row < region.row + region.height
                            and region.column <= cell.column < region.column + region.width)

        async def resize(rows, visible):
            before = state.snapshot()
            calls = [source.calls for source in sources]
            file_before = log_path.read_bytes()
            terminal.rows = rows
            terminal.keys.put_nowait(None)
            await until(lambda: terminal.frames and any(
                region.name == "footer" and region.row == rows - 1
                for region in terminal.frames[-1].regions))
            await sample(monitor, clock, clock[0])
            frame = terminal.frames[-1]
            assert not frame.too_small
            assert visible_names(frame) == names[:visible]
            assert state.snapshot() == before
            assert [source.calls for source in sources] == calls
            assert log_path.read_bytes() == file_before
            assert path.read_bytes() == original_bytes
            assert all(word not in region_text(frame, "docker").lower()
                       for word in ("more", "hidden", "enlarge", "...", "…"))
            return frame

        running = asyncio.create_task(app.run())
        try:
            await until(lambda: bool(terminal.frames))
            assert visible_names(terminal.frames[0]) == names[:4]
            assert len(state.snapshot().objects) == 13
            assert tuple(item.key for item in state.snapshot().objects) == tuple(source.spec.key for source in sources)

            await sample(monitor, clock, 0)
            assert [source.calls for source in sources] == [1] * 13
            await until(lambda: status_is(terminal.frames[-1], names[0], "Running"))
            assert await log.flush()
            assert log_path.read_bytes() == b""  # Hidden healthy objects are not failures.
            healthy_snapshot = state.snapshot()

            mounts[0].failure = containers[5].failure = TIMEOUT
            await sample(monitor, clock, 1)
            assert [source.calls for source in sources] == [2] * 13
            assert await log.flush()
            entries = [json.loads(line) for line in log_path.read_bytes().splitlines()]
            assert [(item["collector"], item["object_id"]) for item in entries] == [
                ("storage", "/disk-first"), ("docker", "docker-5"),
            ]
            await until(lambda: "STALE" in region_text(terminal.frames[-1], "storage"))
            assert "STALE" not in region_text(terminal.frames[-1], "docker")
            assert all(mount in region_text(terminal.frames[-1], "storage") for mount in config.mount_points)
            assert "ignored" not in region_text(terminal.frames[-1], "storage")
            assert all(not item.stale for item in healthy_snapshot.objects)

            expanded = await resize(48, 6)
            assert status_is(expanded, names[5], "STALE")
            reduced = await resize(42, 3)
            assert "STALE" not in region_text(reduced, "docker")
            assert len(state.snapshot().objects) == 13

            # Both newly hidden and never-visible objects still get new samples.
            mounts[0].failure = None
            containers[9].value = "Exited"
            await sample(monitor, clock, 2)
            assert [source.calls for source in sources] == [3] * 13
            hidden = {item.key.object_id: item for item in state.snapshot().objects
                      if item.key.collector == "docker"}
            assert hidden["docker-5"].stale
            assert [point.metrics is None for point in hidden["docker-5"].history] == [False, True, True]
            assert hidden["docker-9"].metrics[0].value == "Exited"
            assert len(hidden["docker-9"].history) == 3
            assert await log.flush()
            assert len(log_path.read_bytes().splitlines()) == 2

            containers[5].failure = None
            containers[5].value = "Restarting"
            await sample(monitor, clock, 3)
            assert [source.calls for source in sources] == [4] * 13
            assert state.snapshot().revision == 52
            assert all(len(item.history) == 4 for item in state.snapshot().objects)
            assert await log.flush()
            recovered = await resize(48, 6)
            assert status_is(recovered, names[5], "Restarting")
            assert "STALE" not in text(recovered)
            assert len(log_path.read_bytes().splitlines()) == 2  # Recovery/Exited are silent.

            for key in ("t", "down", "up", "q"):
                terminal.keys.put_nowait(key)
            await asyncio.wait_for(running, 0.5)
            assert actions.keys == ["t", "down", "up"] and terminal.restored
            assert len(config.containers) == 10 and len(config.mount_points) == 3
            assert path.read_bytes() == original_bytes
            assert all("PRIVATE" not in text(frame) for frame in terminal.frames)
        finally:
            await cleanup(running, monitor, log)
        assert all(source.closed for source in sources)

    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


def test_61_failed_samples_keep_updating_ui_while_real_log_records_only_0_and_60(tmp_path, capsys):
    async def scenario():
        config = config_for(tmp_path)
        bad, good = OfflineSource("chat", failure=TIMEOUT), OfflineSource("embedding")
        log = ErrorLog(config.logging)
        assert log.prepare()
        monitor, state, clock, updates, terminal, actions, app = harness(config, [bad, good], log)
        running = asyncio.create_task(app.run())
        try:
            await until(lambda: bool(terminal.frames))
            assert "—" in text(terminal.frames[0]) and "STALE" not in text(terminal.frames[0])
            for tick in range(61):
                await sample(monitor, clock, tick)
                if tick in (0, 30, 60):
                    frame_count = len(terminal.frames)
                    await until(lambda: len(terminal.frames) > frame_count)
                    assert "STALE" in text(terminal.frames[-1])
            assert bad.calls == good.calls == 61
            assert updates == list(range(1, 123))
            failed, healthy = state.snapshot().objects
            assert failed.stale and failed.sampled_at == 60
            assert healthy.metrics[0].value == 61 and not healthy.stale
            assert len(failed.history) == 61
            assert all(point.metrics is None for point in failed.history)
            assert await log.flush()
            path = config.logging.directory / "error.log"
            entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            assert [entry["time"] for entry in entries] == ["2026-10-28 18:00:00", "2026-10-28 18:01:00"]

            bad.failure, bad.value = None, 0
            await sample(monitor, clock, 61)
            frame_count = len(terminal.frames)
            await until(lambda: len(terminal.frames) > frame_count)
            assert "STALE" not in text(terminal.frames[-1])
            assert "RUNNING: 0" in text(terminal.frames[-1])
            bad.failure = TIMEOUT
            await sample(monitor, clock, 62)
            bad.failure = PERMISSION
            await sample(monitor, clock, 63)
            bad.failure = good.failure = TIMEOUT
            await sample(monitor, clock, 64)
            assert await log.flush()
            entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            assert [(entry["object_id"], entry["kind"]) for entry in entries] == [
                ("chat", "timeout"), ("chat", "timeout"), ("chat", "timeout"),
                ("chat", "permission"), ("embedding", "timeout"),
            ]
            for key in ("t", "down", "up", "q"):
                terminal.keys.put_nowait(key)
            await asyncio.wait_for(running, 0.5)
            assert actions.keys == ["t", "down", "up"] and terminal.restored
            assert all(frame.regions == terminal.frames[0].regions for frame in terminal.frames)
            assert "PRIVATE" not in path.read_text(encoding="utf-8")
            assert all("PRIVATE" not in text(frame) for frame in terminal.frames)
            assert bad.calls == good.calls == 65
        finally:
            await cleanup(running, monitor, log)
        assert bad.closed and good.closed
    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


class GatedFileIO(FileLogIO):
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def append(self, config, line):
        self.started.set()
        if not self.release.wait(2):
            raise OSError("PRIVATE simulated slow disk")
        super().append(config, line)


def test_slow_disk_full_queue_and_slow_source_leave_sampling_keys_and_quit_responsive(tmp_path, capsys):
    async def scenario():
        config = config_for(tmp_path)
        failing = [OfflineSource(name, failure=TIMEOUT) for name in ("chat", "embedding", "reranker")]
        fast = OfflineSource("local", collector="host")
        slow = OfflineSource("0", collector="gpu", blocked=True)
        io = GatedFileIO()
        log = ErrorLog(config.logging, io=io, queue_capacity=1)
        assert log.prepare()
        monitor, state, clock, updates, terminal, actions, app = harness(config, [*failing, fast, slow], log)
        running = asyncio.create_task(app.run())
        try:
            await sample(monitor, clock, 0)
            await until(io.started.is_set)
            await sample(monitor, clock, 1)
            assert all(source.calls == 2 for source in [*failing, fast])
            assert slow.calls == 1
            assert len(updates) == 8
            assert [obj.stale for obj in state.snapshot().objects] == [True, True, True, False, False]
            await until(lambda: bool(terminal.frames) and "STALE" in text(terminal.frames[-1]))
            for key in ("t", "down", "up", "q"):
                terminal.keys.put_nowait(key)
            await asyncio.wait_for(running, 0.5)
            assert actions.keys == ["t", "down", "up"] and terminal.restored
            assert not io.release.is_set()  # q restored the terminal while disk was still blocked.
            io.release.set()
            assert await log.flush()
            path = config.logging.directory / "error.log"
            assert len(path.read_text(encoding="utf-8").splitlines()) == 2
            await sample(monitor, clock, 2)
            assert await log.flush()
            entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            assert {entry["object_id"] for entry in entries} == {"chat", "embedding", "reranker"}
            assert len(entries) == 3  # The dropped object's next sample was not throttled.
            assert all(source.calls == 3 for source in [*failing, fast])
            assert all("PRIVATE" not in text(frame) for frame in terminal.frames)
        finally:
            io.release.set()
            await cleanup(running, monitor, log)
        assert slow.cancelled and all(source.closed for source in [*failing, fast, slow])
    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


class FailingFileIO(FileLogIO):
    def __init__(self, *, prepare_fails):
        self.prepare_fails = prepare_fails
        self.append_fails = True

    def prepare(self, directory):
        if self.prepare_fails:
            raise PermissionError("PRIVATE prepare failure")
        super().prepare(directory)

    def append(self, config, line):
        if self.append_fails:
            raise OSError("PRIVATE append failure")
        super().append(config, line)


@pytest.mark.parametrize("prepare_fails", [False, True])
def test_log_io_failure_then_recovery_preserves_sampling_and_silent_ui(tmp_path, capsys, prepare_fails):
    async def scenario():
        config = config_for(tmp_path)
        io = FailingFileIO(prepare_fails=prepare_fails)
        log = ErrorLog(config.logging, io=io)
        assert log.prepare() is not prepare_fails
        bad, good = OfflineSource("chat", failure=TIMEOUT), OfflineSource("embedding")
        monitor, state, clock, updates, terminal, actions, app = harness(config, [bad, good], log)
        running = asyncio.create_task(app.run())
        try:
            for tick in range(2):
                await sample(monitor, clock, tick)
                assert await log.flush()
            assert bad.calls == good.calls == 2
            assert len(updates) == 4
            await until(lambda: bool(terminal.frames) and "STALE" in text(terminal.frames[-1]))
            terminal.keys.put_nowait("down")
            terminal.keys.put_nowait("t")
            await until(lambda: actions.keys == ["down", "t"])
            io.prepare_fails = io.append_fails = False
            await sample(monitor, clock, 2)
            assert await log.flush()
            path = config.logging.directory / "error.log"
            entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            assert len(entries) == 1 and entries[0]["time"] == "2026-10-28 18:00:02"
            bad.failure = None
            await sample(monitor, clock, 3)
            assert not state.snapshot().objects[0].stale
            assert bad.calls == good.calls == 4
            frame_count = len(terminal.frames)
            await until(lambda: len(terminal.frames) > frame_count)
            assert "STALE" not in text(terminal.frames[-1])
            terminal.keys.put_nowait("q")
            await asyncio.wait_for(running, 0.5)
            assert terminal.restored
            assert all("PRIVATE" not in text(frame) for frame in terminal.frames)
        finally:
            await cleanup(running, monitor, log)
    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")
