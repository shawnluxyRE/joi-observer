"""Additional public shell/lifecycle boundaries; all external sources stay offline."""

import asyncio
from datetime import datetime, timezone
import time
import unicodedata

import pytest

from joi_observer.cli import ApplicationRuntime, RuntimeComponents
from joi_observer.config import AppConfig, ContainerConfig, load_config
from joi_observer.data.models import CollectionResult, Metric, ObjectKey, ObjectSnapshot, ObjectSpec, StateSnapshot
from joi_observer.data.state import MonitorState
from joi_observer.monitor import Monitor
from joi_observer.tui.app import ObserverApp
from joi_observer.tui.layout import HostInfo, TerminalSize, compose_frame, format_metric


NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
HOST = HostInfo("offline", "Ubuntu")


class Terminal:
    def __init__(self):
        self.frames = []
        self.entered = asyncio.Event()
        self.restored = False

    def enter(self):
        self.entered.set()

    def restore(self):
        self.restored = True

    def size(self):
        return TerminalSize(120, 40)

    def render(self, frame):
        self.frames.append(frame)

    async def read_key(self, timeout):
        await asyncio.sleep(timeout)
        return None


def make_app(terminal, reader=None):
    return ObserverApp(AppConfig(), reader or MonitorState(), terminal, host=HOST, wall_clock=lambda: NOW)


def test_cancel_restores_terminal_and_concurrent_run_is_rejected():
    async def scenario():
        terminal = Terminal()
        app = make_app(terminal)
        task = asyncio.create_task(app.run())
        await terminal.entered.wait()
        with pytest.raises(RuntimeError, match="already running"):
            await app.run()
        assert not terminal.restored
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert terminal.restored

    asyncio.run(scenario())


def test_failed_restore_does_not_replace_original_draw_error():
    class BrokenTerminal(Terminal):
        def render(self, frame):
            raise ValueError("original draw failure")

        def restore(self):
            super().restore()
            raise RuntimeError("secondary restore failure")

    terminal = BrokenTerminal()
    with pytest.raises(ValueError, match="original draw failure"):
        asyncio.run(make_app(terminal).run())
    assert terminal.restored


def test_unicode_names_are_bounded_by_display_width_and_controls_removed():
    config = AppConfig(containers=(ContainerConfig("test", "界" * 128),))
    frame = compose_frame(StateSnapshot(()), config, TerminalSize(120, 40),
                          HostInfo("name\x1b\n\u202e", "界" * 128), NOW)
    for cell in frame.cells:
        assert 0 <= cell.row < 40 and 0 <= cell.column < 120
        assert all(not unicodedata.category(char).startswith("C") for char in cell.text)
        width = sum(0 if unicodedata.combining(char) else
                    2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in cell.text)
        assert cell.column + width <= 120
    assert format_metric(Metric("state", "Ready\n\x1b[31m")) == "Ready  [31m"
    with pytest.raises(ValueError, match="timezone"):
        compose_frame(StateSnapshot(()), config, TerminalSize(120, 40), HOST, NOW.replace(tzinfo=None))


def test_gpu_slots_survive_disappearance_without_capacity_shrinking():
    class Reader:
        def __init__(self):
            self.reads = 0

        def snapshot(self):
            self.reads += 1
            objects = tuple(ObjectSnapshot(ObjectKey("gpu", str(index))) for index in range(6))
            return StateSnapshot(objects if self.reads == 1 else ())

    class TwoFrameTerminal(Terminal):
        def size(self):
            return TerminalSize(120, 44)

        async def read_key(self, timeout):
            await asyncio.sleep(timeout)
            return "q" if len(self.frames) >= 2 else None

    terminal = TwoFrameTerminal()
    asyncio.run(make_app(terminal, Reader()).run())
    assert len(terminal.frames) >= 2
    assert terminal.frames[0].minimum_size == terminal.frames[1].minimum_size == TerminalSize(120, 43)
    assert not terminal.frames[0].too_small and terminal.frames[0].regions
    assert terminal.frames[0].regions == terminal.frames[1].regions


class Log:
    def __init__(self, terminal, *, close_delay=0):
        self.terminal = terminal
        self.close_delay = close_delay
        self.closed = False
        self.timeout = None

    def record(self, *args, **kwargs):
        return True

    def recovered(self, *args):
        pass

    async def close(self, *, timeout=1.0):
        assert self.terminal.restored
        self.timeout = timeout
        await asyncio.sleep(self.close_delay)
        self.closed = True
        return True


def test_monitor_internal_error_restores_ui_then_closes_log():
    class InvalidSource:
        spec = ObjectSpec(ObjectKey("host", "local"), (Metric("CPU", None),))

        def __init__(self):
            self.closed = False

        async def collect(self):
            # The collector's declared contract is violated, which is a runtime
            # programming error rather than a user-visible collection failure.
            return CollectionResult(self.spec.key, (Metric("undeclared", 1),))

        async def close(self):
            self.closed = True

    async def scenario():
        source = InvalidSource()
        state = MonitorState((source.spec,))
        terminal = Terminal()
        log = Log(terminal)
        app = make_app(terminal, state)
        monitor = Monitor((source,), state, log)
        runtime = ApplicationRuntime(AppConfig(), components=RuntimeComponents(monitor, app, log))
        with pytest.raises(ValueError):
            await runtime.run()
        await runtime.close()
        assert terminal.restored and source.closed and log.closed

    asyncio.run(scenario())


def test_monitor_and_log_share_one_shutdown_budget():
    class SlowClosingSource:
        spec = ObjectSpec(ObjectKey("host", "local"), (Metric("CPU", None),))

        def __init__(self):
            self.started = asyncio.Event()
            self.closed = False

        async def collect(self):
            self.started.set()
            await asyncio.Future()

        async def close(self):
            await asyncio.sleep(0.7)
            self.closed = True

    class QuittingTerminal(Terminal):
        async def read_key(self, timeout):
            await source.started.wait()
            return "q"

    async def scenario():
        state = MonitorState((source.spec,))
        terminal = QuittingTerminal()
        log = Log(terminal, close_delay=0.7)
        monitor = Monitor((source,), state, log, timeout=30)
        runtime = ApplicationRuntime(AppConfig(), components=RuntimeComponents(monitor, make_app(terminal, state), log))
        started = time.monotonic()
        await runtime.run()
        await runtime.close()
        elapsed = time.monotonic() - started
        assert elapsed < 1.15  # two serial 0.7-second closes would violate this
        assert source.closed and log.closed and terminal.restored
        assert 0 < log.timeout <= 1.0

    source = SlowClosingSource()
    asyncio.run(scenario())


def test_production_unknown_slots_accept_long_mount_and_display_names(tmp_path, monkeypatch):
    class QuittingTerminal(Terminal):
        async def read_key(self, timeout):
            return "q"

    mount = "/" + "x" * 200
    name = "界" * 128
    path = tmp_path / "config.yaml"
    path.write_text(
        f"mount_points: ['{mount}']\n"
        f"containers: [{{id: container, name: '{name}'}}]\n"
        f"models: [{{id: model, type: chat, name: '{name}', base_url: 'http://127.0.0.1:8000'}}]\n"
        f"logging: {{directory: '{tmp_path.as_posix()}'}}\n", encoding="utf-8")
    config = load_config(path)
    terminal = QuittingTerminal()
    monkeypatch.setattr("joi_observer.cli.CursesTerminal", lambda: terminal)
    runtime = ApplicationRuntime(config)
    assert runtime.prepare_log()

    async def scenario():
        await runtime.run()
        await runtime.close()

    asyncio.run(scenario())
    assert terminal.restored and terminal.frames
    assert not terminal.frames[0].too_small
    assert "STALE" not in " ".join(cell.text for cell in terminal.frames[0].cells)
    assert (tmp_path / "error.log").read_text(encoding="utf-8") == ""
