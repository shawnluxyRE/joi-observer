"""REQ-001容量、只读呈现及终端生命周期；不接触真实终端或服务器。"""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import unicodedata

import pytest

from joi_observer.config import AppConfig, ContainerConfig, ModelConfig, ModelType
from joi_observer.cli import ApplicationRuntime, RuntimeComponents
from joi_observer.data.models import Metric, ObjectKey, ObjectSnapshot, ObjectSpec, StateSnapshot
from joi_observer.data.state import MonitorState
from joi_observer.monitor import Monitor
from joi_observer.tui.app import ObserverApp
from joi_observer.tui.layout import HostInfo, TerminalSize, ViewSelection, compose_frame, format_metric, required_size


NOW = datetime(2026, 10, 28, 12, 34, 56, tzinfo=timezone.utc)
HOST = HostInfo("offline-test-host", "Ubuntu 24.04")


def config_with_containers(count=5):
    return AppConfig(containers=tuple(ContainerConfig(f"c{i}", f"container-{i}") for i in range(count)))


def snapshot(*, stale=False, sampled_at=None):
    return StateSnapshot(objects=(ObjectSnapshot(key=ObjectKey("host", "local"), metrics=(Metric("usage", None, "%"),), stale=stale, sampled_at=sampled_at),), revision=0)


def text(frame):
    return " ".join(cell.text for cell in frame.cells)


@pytest.mark.parametrize("gpu,mount,docker,expected_rows", [(5, 2, 5, 37), (6, 2, 5, 43), (10, 2, 5, 67), (5, 10, 10, 37), (0, 0, 0, 36), (0, 3, 100, 36)])
def test_capacity_uses_character_counts(gpu, mount, docker, expected_rows):
    assert required_size(gpu_count=gpu, mount_count=mount, container_count=docker) == TerminalSize(120, expected_rows)


@pytest.mark.parametrize("args", [(-1, 2, 5), (5, -1, 5), (5, 2, -1), (True, 2, 5), (5, 2, 1.5)])
def test_invalid_capacity_is_rejected(args):
    with pytest.raises(ValueError):
        required_size(gpu_count=args[0], mount_count=args[1], container_count=args[2])


@pytest.mark.parametrize("metric,expected", [(Metric("usage", None, "%"), "—"), (Metric("usage", 0, "%"), "0%"), (Metric("queue", None, "s", applicable=False), "N/A"), (Metric("state", "Exited"), "Exited")])
def test_value_states_do_not_confuse_unknown_with_zero(metric, expected):
    assert format_metric(metric) == expected


def test_initial_frame_has_title_host_time_and_unknown_values():
    frame = compose_frame(snapshot(), config_with_containers(), TerminalSize(120, 38), HOST, NOW, gpu_slots=("0", "1", "2", "3", "4"))
    combined = "".join(cell.text for cell in frame.cells)
    assert "Joi::Observer" in combined
    assert HOST.hostname in combined and HOST.system in combined
    assert "2026-10-28 12:34:56" in combined
    assert "—" in combined and "STALE" not in combined
    assert not frame.too_small
    assert "WebUI" in combined
    assert "Details" not in combined and "Pause" not in combined


def test_failure_reuses_status_slot_without_timestamp_or_layout_change():
    options = (config_with_containers(), TerminalSize(120, 38), HOST, NOW)
    initial = compose_frame(snapshot(), *options, gpu_slots=("0", "1", "2", "3", "4"))
    failed = compose_frame(snapshot(stale=True, sampled_at=987654321.25), *options, gpu_slots=("0", "1", "2", "3", "4"))
    recovered = compose_frame(snapshot(stale=False), *options, gpu_slots=("0", "1", "2", "3", "4"))
    assert initial.regions == failed.regions == recovered.regions
    assert "STALE" in text(failed) and "STALE" not in text(recovered)
    assert "987654321" not in text(failed)
    assert "last success" not in text(failed).lower()


@pytest.mark.parametrize("size", [TerminalSize(119, 37), TerminalSize(120, 36), TerminalSize(80, 24)])
def test_small_window_gets_single_enlarge_view(size):
    frame = compose_frame(snapshot(), config_with_containers(), size, HOST, NOW, gpu_slots=("0", "1", "2", "3", "4"))
    assert frame.too_small
    assert frame.minimum_size == TerminalSize(120, 37)
    assert "Enlarge terminal to at least 120x37" in text(frame)
    assert "q Quit" in text(frame)
    assert frame.regions == ()


def test_docker_height_uses_remaining_space_independent_of_configured_count():
    frames = [compose_frame(snapshot(), config_with_containers(count), TerminalSize(120, 44), HOST, NOW)
              for count in (0, 1, 5, 6, 10)]
    assert all(not frame.too_small for frame in frames)
    assert all(frame.regions == frames[0].regions for frame in frames)
    assert all(next(r for r in frame.regions if r.name == "docker").height == 7 for frame in frames)


@pytest.mark.parametrize("height,upper,lower", [(36, 18, 18), (37, 19, 18), (38, 19, 19), (44, 22, 22), (45, 23, 22), (48, 24, 24)])
def test_full_page_halves_include_header_switch_footer_and_gaps(height, upper, lower):
    frame = compose_frame(snapshot(), config_with_containers(1), TerminalSize(120, height), HOST, NOW)
    assert not frame.too_small
    regions = {region.name: region for region in frame.regions}
    assert set(regions) == {"header", "gpu", "host", "storage", "docker", "service", "service_switch", "footer"}
    assert (regions["header"].row, regions["header"].height) == (0, 2)
    assert (regions["gpu"].row, regions["gpu"].height) == (2, upper - 2)
    assert (regions["host"].row, regions["host"].height) == (2, 5)
    assert (regions["storage"].row, regions["storage"].height) == (8, 6)
    assert (regions["docker"].row, regions["docker"].height) == (15, upper - 15)
    assert (regions["service"].row, regions["service"].height) == (upper, lower - 2)
    assert (regions["service_switch"].row, regions["service_switch"].height) == (height - 2, 1)
    assert (regions["footer"].row, regions["footer"].height) == (height - 1, 1)
    assert regions["service"].height + regions["service_switch"].height + regions["footer"].height == lower
    assert any("WebUI" in cell.text and cell.row == height - 2 for cell in frame.cells)
    assert all(region.row + region.height <= upper for name, region in regions.items()
               if name in {"header", "gpu", "host", "storage", "docker"})


@pytest.mark.parametrize("mounts", [(), ("/",), ("/", "/data"), ("/", "/data", "/cache")])
def test_storage_has_three_content_rows_at_every_window_height(mounts):
    config = AppConfig(mount_points=mounts)
    for height in (36, 44, 48):
        frame = compose_frame(snapshot(), config, TerminalSize(120, height), HOST, NOW)
        storage = next(region for region in frame.regions if region.name == "storage")
        assert (storage.row, storage.height) == (8, 6)
        for index, mount in enumerate(mounts):
            cells = [cell for cell in frame.cells if cell.text.startswith(mount + "  ")]
            assert len(cells) == 1 and cells[0].row == 10 + index
        if not mounts:
            assert any("No mount points configured" in cell.text and 10 <= cell.row <= 12 for cell in frame.cells)


def test_storage_ignores_fourth_mount_without_replacing_failed_first_item():
    mounts = ("/", "/data", "/cache", "/ignored")
    config = AppConfig(mount_points=mounts)
    data = StateSnapshot(tuple(ObjectSnapshot(ObjectKey("storage", mount),
                                             (Metric("used", index, "GiB"),), stale=index == 0)
                               for index, mount in enumerate(mounts)))
    frame = compose_frame(data, config, TerminalSize(120, 44), HOST, NOW)
    labels = [cell for cell in frame.cells if any(cell.text.startswith(mount + "  ") for mount in mounts)]
    assert [cell.text.split("  ", 1)[0] for cell in labels] == ["/", "/data", "/cache"]
    assert [cell.row for cell in labels] == [10, 11, 12]
    assert any(cell.text == "STALE" and cell.row == 10 for cell in frame.cells)
    assert "/ignored" not in text(frame)


def docker_snapshot(count=10, *, stale_index=None):
    return StateSnapshot(tuple(ObjectSnapshot(ObjectKey("docker", f"c{index}"),
                                             (Metric("state", "Exited" if index == 4 else "Running"),),
                                             stale=index == stale_index)
                               for index in range(count)))


def visible_container_names(frame):
    return [cell.text for cell in frame.cells if cell.text.startswith("container-")]


def test_docker_resize_shows_prefix_four_then_six_then_three_from_same_latest_snapshot():
    config, data = config_with_containers(10), docker_snapshot(stale_index=5)
    before = deepcopy((config, data))
    frames = [compose_frame(data, config, TerminalSize(120, height), HOST, NOW) for height in (44, 48, 42)]
    for frame, capacity in zip(frames, (4, 6, 3)):
        assert not frame.too_small
        assert visible_container_names(frame) == [f"container-{index}" for index in range(capacity)]
        regions = {region.name: region for region in frame.regions}
        docker, service = regions["docker"], regions["service"]
        assert all(docker.row + 2 <= cell.row < docker.row + docker.height - 1
                   for cell in frame.cells if cell.text.startswith("container-"))
        assert docker.row + docker.height == service.row
        displayed = text(frame).lower()
        assert all(word not in displayed for word in ("enlarge", "hidden", "more", "overflow", "page ", "...", "…"))
    assert "Exited" not in text(frames[0]) and "Exited" in text(frames[1])
    assert "STALE" not in text(frames[0]) and "STALE" in text(frames[1])
    assert (config, data) == before and len(config.containers) == len(data.objects) == 10


@pytest.mark.parametrize("count", [0, 10])
def test_zero_docker_content_capacity_does_not_draw_entries_empty_state_or_prompt(count):
    frame = compose_frame(snapshot(), config_with_containers(count), TerminalSize(120, 36), HOST, NOW)
    assert not frame.too_small
    docker = next(region for region in frame.regions if region.name == "docker")
    assert docker.height == 3
    assert visible_container_names(frame) == []
    assert "No containers configured" not in text(frame)
    assert "Enlarge" not in text(frame)


def test_empty_docker_uses_available_content_row_without_shrinking_panel():
    frame = compose_frame(snapshot(), config_with_containers(0), TerminalSize(120, 44), HOST, NOW)
    docker = next(region for region in frame.regions if region.name == "docker")
    assert docker.height == 7
    empty = [cell for cell in frame.cells if "No containers configured" in cell.text]
    assert len(empty) == 1 and empty[0].row == 17


def test_docker_failures_keep_prefix_order_and_other_regions_unchanged():
    config = config_with_containers(10)
    frames = [compose_frame(docker_snapshot(stale_index=index), config, TerminalSize(120, 44), HOST, NOW)
              for index in (None, 0, None)]
    assert all(frame.regions == frames[0].regions for frame in frames)
    assert all(visible_container_names(frame) == [f"container-{index}" for index in range(4)] for frame in frames)
    assert "STALE" not in text(frames[0]) and "STALE" in text(frames[1]) and "STALE" not in text(frames[2])
    assert all("container-4" not in text(frame) for frame in frames)


@pytest.mark.parametrize("columns,height", [(120, 36), (121, 37), (140, 44), (120, 45), (120, 48)])
def test_dense_unicode_content_remains_inside_its_named_region(columns, height):
    name = "界" * 128
    models = tuple(ModelConfig(f"m{index}", ModelType.CHAT, name, "http://127.0.0.1:8000")
                   for index in range(40))
    config = AppConfig(mount_points=("/", "/data", "/cache", "/ignored"), models=models,
                       containers=tuple(ContainerConfig(f"c{index}", name) for index in range(40)))
    data = StateSnapshot((ObjectSnapshot(ObjectKey("vllm", "m39"),
                                          tuple(Metric(f"metric-{index}", name) for index in range(30)), stale=True),))
    frame = compose_frame(data, config, TerminalSize(columns, height), HOST, NOW,
                          view=ViewSelection(model_id="m39"))
    assert not frame.too_small
    for cell in frame.cells:
        display_width = sum(0 if unicodedata.combining(char) else
                            2 if unicodedata.east_asian_width(char) in "WF" else 1
                            for char in cell.text)
        owners = [region for region in frame.regions
                  if region.row <= cell.row < region.row + region.height
                  and region.column <= cell.column
                  and cell.column + display_width <= region.column + region.width]
        assert len(owners) == 1, (cell, owners)
        if cell.text.startswith("metric-"):
            service = owners[0]
            assert service.name == "service"
            assert service.row < cell.row < service.row + service.height - 1
    assert all("/ignored" not in cell.text for cell in frame.cells)


def test_model_list_grows_with_half_page_while_selection_and_switch_stay_visible():
    models = tuple(ModelConfig(f"m{index}", ModelType.CHAT, f"Model {index:02}", "http://127.0.0.1:8000")
                   for index in range(40))
    config = AppConfig(models=models)
    model_names = {model.name for model in models}
    visible = []
    for height in (36, 48):
        frame = compose_frame(StateSnapshot(()), config, TerminalSize(120, height), HOST, NOW,
                              view=ViewSelection(model_id="m39"))
        service = next(region for region in frame.regions if region.name == "service")
        labels = [cell for cell in frame.cells if cell.text in model_names]
        visible.append([cell.text for cell in labels])
        assert labels[-1].text == "Model 39" and labels[-1].role == "primary"
        assert all(service.row < cell.row < service.row + service.height - 1 for cell in labels)
        assert [cell.row for cell in frame.cells if "WebUI" in cell.text] == [height - 2]
        assert [cell.row for cell in frame.cells if "q Quit" in cell.text] == [height - 1]
    assert len(visible[1]) > len(visible[0])
    assert set(visible[0]).issubset(visible[1])


def test_four_gpu_minimum_keeps_all_cards_even_when_no_container_fits():
    frame = compose_frame(StateSnapshot(()), config_with_containers(100), TerminalSize(120, 36), HOST, NOW,
                          gpu_slots=("0", "1", "2", "3"))
    assert not frame.too_small and frame.minimum_size == TerminalSize(120, 36)
    assert [cell.text for cell in frame.cells if cell.text.startswith("GPU ")] == ["GPU 0", "GPU 1", "GPU 2", "GPU 3"]
    assert visible_container_names(frame) == []


@pytest.mark.parametrize("gpu_count,minimum_rows", [(6, 43), (10, 67)])
def test_gpu_capacity_boundary_draws_every_slot_inside_the_upper_half(gpu_count, minimum_rows):
    """Capacity includes actual GPU values/statuses without cropping later cards."""
    slots = tuple(str(index) for index in range(gpu_count))
    data = StateSnapshot(tuple(
        ObjectSnapshot(ObjectKey("gpu", object_id), (Metric("util", index, "%"),), stale=bool(index % 2))
        for index, object_id in enumerate(slots)
    ))
    config = config_with_containers(100)
    too_small = compose_frame(data, config, TerminalSize(120, minimum_rows - 1), HOST, NOW,
                              gpu_slots=slots)
    assert too_small.too_small and too_small.regions == ()
    assert f"Enlarge terminal to at least 120x{minimum_rows}" in text(too_small)

    for height in (minimum_rows, minimum_rows + 1):
        frame = compose_frame(data, config, TerminalSize(120, height), HOST, NOW, gpu_slots=slots)
        assert not frame.too_small
        regions = {region.name: region for region in frame.regions}
        gpu, service = regions["gpu"], regions["service"]
        labels = [cell for cell in frame.cells if cell.text.startswith("GPU ")]
        values = [cell for cell in frame.cells if cell.text.startswith("util: ")]
        statuses = [cell for cell in frame.cells if cell.text == "STALE" and cell.column < gpu.width]
        assert [cell.text for cell in labels] == [f"GPU {object_id}" for object_id in slots]
        assert [cell.text for cell in values] == [f"util: {index}%" for index in range(gpu_count)]
        assert len(statuses) == gpu_count // 2
        assert all(gpu.row < cell.row < gpu.row + gpu.height - 1 <= service.row
                   for cell in labels + values + statuses)
        assert service.row == height - height // 2
        assert regions["storage"].height == 6


class MemoryReader:
    def __init__(self):
        self.reads = 0

    def snapshot(self):
        self.reads += 1
        return snapshot()


class MemoryTerminal:
    """外部终端替身；不替代布局或应用循环。"""

    def __init__(self, keys=("q",), sizes=(TerminalSize(120, 40),), failure=None):
        self.keys = list(keys)
        self.sizes = list(sizes)
        self.failure = failure
        self.calls = []
        self.frames = []

    def enter(self):
        self.calls.append("enter")
        if self.failure == "enter":
            raise RuntimeError("partial enter failure")

    def restore(self):
        self.calls.append("restore")

    def size(self):
        return self.sizes[0]

    def render(self, frame):
        self.calls.append("render")
        if self.failure == "render":
            raise RuntimeError("draw failure")
        self.frames.append(frame)

    async def read_key(self, timeout):
        assert 0 < timeout <= 0.05
        await asyncio.sleep(0)
        if len(self.sizes) > 1:
            self.sizes.pop(0)
        key = self.keys.pop(0) if self.keys else "q"
        if isinstance(key, BaseException):
            raise key
        return key


class MemoryActions:
    def __init__(self):
        self.keys = []

    def selection(self):
        return ViewSelection()

    def on_key(self, key):
        self.keys.append(key)


def app_for(terminal, *, actions=None):
    return ObserverApp(AppConfig(), MemoryReader(), terminal, host=HOST, wall_clock=lambda: NOW, actions=actions)


def test_q_exits_and_restores_after_initial_draw():
    terminal = MemoryTerminal()
    asyncio.run(app_for(terminal).run())
    assert terminal.calls[0] == "enter"
    assert terminal.frames
    assert terminal.calls[-1] == "restore"


@pytest.mark.parametrize("failure", ["enter", "render"])
def test_terminal_restored_on_partial_entry_or_draw_exception(failure):
    terminal = MemoryTerminal(failure=failure)
    with pytest.raises(RuntimeError, match="partial enter failure|draw failure"):
        asyncio.run(app_for(terminal).run())
    assert terminal.calls[-1] == "restore"


def test_terminal_restored_on_interrupt():
    terminal = MemoryTerminal(keys=(KeyboardInterrupt(),))
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(app_for(terminal).run())
    assert terminal.calls[-1] == "restore"


def test_small_window_can_still_quit():
    terminal = MemoryTerminal(sizes=(TerminalSize(80, 24),))
    asyncio.run(app_for(terminal).run())
    assert terminal.frames[0].too_small
    assert terminal.calls[-1] == "restore"


def test_resize_returns_to_full_view_without_restarting():
    terminal = MemoryTerminal(keys=(None, "q"), sizes=(TerminalSize(80, 24), TerminalSize(120, 40)))
    asyncio.run(app_for(terminal).run())
    assert terminal.frames[0].too_small
    assert not terminal.frames[-1].too_small
    assert terminal.calls.count("enter") == 1


def test_navigation_is_dispatched_without_collector_dependency():
    terminal = MemoryTerminal(keys=("t", "down", "up", "left", "right", "p", "enter", "q"))
    actions = MemoryActions()
    asyncio.run(app_for(terminal, actions=actions).run())
    assert actions.keys == ["t", "down", "up", "left", "right"]
    assert terminal.calls[-1] == "restore"


class WaitingCollector:
    """离线外部源始终等待，公开取消/关闭标志用于观察运行期清理。"""

    def __init__(self):
        self.spec = ObjectSpec(ObjectKey("host", "local"), (Metric("usage", None, "%"),))
        self.started = asyncio.Event()
        self.cancelled = False
        self.closed = False

    async def collect(self):
        self.started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def close(self):
        self.closed = True


class MemoryLogPort:
    """仅隔离文件IO；联合测试不制造采集错误，无日志业务预期。"""

    def __init__(self, events):
        self.events = events
        self.records = []

    def prepare(self):
        return True

    def record(self, collector, object_id, failure, **kwargs):
        self.records.append((collector, object_id, failure))
        return True

    def recovered(self, collector, object_id):
        pass

    async def close(self, *, timeout=1.0):
        assert 0 < timeout <= 1.0
        self.events.append("log.close")
        return True


class CoordinatedTerminal(MemoryTerminal):
    """只有采集已发起后才返回退出或读键异常，避免用q跳过协作验证。"""

    def __init__(self, collector, events, *, read_error=False):
        super().__init__()
        self.collector = collector
        self.events = events
        self.read_error = read_error

    def restore(self):
        super().restore()
        self.events.append("restore")

    async def read_key(self, timeout):
        try:
            await asyncio.wait_for(self.collector.started.wait(), timeout)
        except TimeoutError:
            return None
        if self.read_error:
            raise RuntimeError("input failed")
        return "q"


def test_real_runtime_ui_quits_while_real_monitor_source_is_waiting():
    async def scenario():
        events = []
        collector = WaitingCollector()
        state = MonitorState((collector.spec,))
        log = MemoryLogPort(events)
        terminal = CoordinatedTerminal(collector, events)
        app = ObserverApp(AppConfig(), state, terminal, host=HOST, wall_clock=lambda: NOW)
        monitor = Monitor((collector,), state, log, timeout=30)
        runtime = ApplicationRuntime(AppConfig(), components=RuntimeComponents(monitor, app, log))
        await asyncio.wait_for(runtime.run(), 1.5)
        await runtime.close()
        assert collector.started.is_set()
        assert collector.cancelled and collector.closed
        assert terminal.frames
        assert events.index("restore") < events.index("log.close")
        assert log.records == []  # 取消本身不是采集失败。

    asyncio.run(scenario())


def test_real_runtime_stops_source_and_restores_after_ui_exception():
    async def scenario():
        events = []
        collector = WaitingCollector()
        state = MonitorState((collector.spec,))
        log = MemoryLogPort(events)
        terminal = CoordinatedTerminal(collector, events, read_error=True)
        app = ObserverApp(AppConfig(), state, terminal, host=HOST, wall_clock=lambda: NOW)
        monitor = Monitor((collector,), state, log, timeout=30)
        runtime = ApplicationRuntime(AppConfig(), components=RuntimeComponents(monitor, app, log))
        with pytest.raises(RuntimeError, match="input failed"):
            await asyncio.wait_for(runtime.run(), 1.5)
        await runtime.close()
        assert collector.cancelled and collector.closed
        assert events.index("restore") < events.index("log.close")
        assert log.records == []

    asyncio.run(scenario())
