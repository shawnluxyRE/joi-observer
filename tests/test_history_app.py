"""The default app must carry session scales into real, read-only frames."""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from joi_observer.config import AppConfig, ModelConfig, ModelType
from joi_observer.data.models import HistoryPoint, Metric, ObjectKey, ObjectSnapshot, StateSnapshot
from joi_observer.tui.app import ObserverApp
from joi_observer.tui.layout import HostInfo, TerminalSize


NOW = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
HOST = HostInfo("offline", "Ubuntu")


def inputs():
    config = AppConfig(mount_points=(), models=(
        ModelConfig("chat", ModelType.CHAT, "Chat", "http://offline.invalid:8000"),
        ModelConfig("embed", ModelType.EMBEDDING, "Embedding", "http://offline.invalid:8001"),
    ))
    # The 121 peak's second leaves the fixed 60-slot sweep at time 101. The
    # remaining peak is 23, which asks for the 50-unit scale, not 23 itself.
    snapshot = StateSnapshot((
        ObjectSnapshot(ObjectKey("vllm", "chat"), (Metric("decode_rate", 23, "tok/s"),),
                       sampled_at=100, history=(
                           HistoryPoint(41, (Metric("decode_rate", 121, "tok/s"),)),
                           HistoryPoint(100, (Metric("decode_rate", 23, "tok/s"),)),
                       )),
        ObjectSnapshot(ObjectKey("vllm", "embed"), (Metric("rate", 7, "seq/s"),),
                       sampled_at=100, history=(HistoryPoint(100, (Metric("rate", 7, "seq/s"),)),)),
    ), revision=1)
    return config, snapshot


class Reader:
    def __init__(self, snapshot):
        self.value = snapshot
        self.reads = 0

    def snapshot(self):
        self.reads += 1
        return self.value


class Terminal:
    def __init__(self, clock, schedule, *, small_at=()):
        self.clock, self.schedule = clock, list(schedule)
        self.small_at = small_at
        self.index = 0
        self.frames = []
        self.events = []

    def enter(self):
        self.events.append("enter")

    def restore(self):
        self.events.append("restore")

    def size(self):
        if self.clock[0] in self.small_at:
            return TerminalSize(80, 24)
        return TerminalSize(120 + 2 * (self.index % 2), 40)

    def render(self, frame):
        self.frames.append((self.clock[0], frame))

    async def read_key(self, timeout):
        assert 0 < timeout <= 0.05
        assert self.index < len(self.schedule), "Application did not exit on q"
        when, key = self.schedule[self.index]
        self.index += 1
        # An external scheduling stall may exceed the requested key timeout.
        # Production must recover using latest data, without replaying frames.
        self.clock[0] = when
        await asyncio.sleep(0)
        return key


def labels(frame):
    return [cell.text for cell in frame.cells if cell.text.startswith("Scale ≤ ")]


@pytest.mark.parametrize("small", (False, True), ids=("normal", "small-window"))
def test_default_app_updates_unselected_scales_across_theme_resize_and_same_snapshot(monkeypatch, small):
    async def scenario():
        config, snapshot = inputs()
        before = deepcopy((config, snapshot))
        reader, clock = Reader(snapshot), [100.0]
        terminal = Terminal(clock, ((101, "down"), (103, "t"), (105.9, "up"),
                                    (106, None), (107, "q")), small_at=(103,) if small else ())
        app = ObserverApp(config, reader, terminal, host=HOST, wall_clock=lambda: NOW)
        with monkeypatch.context() as patch:
            patch.setattr(asyncio.get_running_loop(), "time", lambda: clock[0])
            patch.setattr("joi_observer.tui.layout.time.monotonic", lambda: clock[0])
            await app.run()
        assert terminal.events == ["enter", "restore"]
        assert reader.reads == len(terminal.frames)
        assert (config, snapshot) == before
        observed = dict(terminal.frames)
        assert labels(observed[100]) == ["Scale ≤ 200 tok/s"]
        assert labels(observed[101]) == ["Scale ≤ 10 seq/s"]
        assert observed[103].too_small is small
        assert labels(observed[105.9]) == ["Scale ≤ 200 tok/s"]
        assert labels(observed[106]) == ["Scale ≤ 50 tok/s"]
        assert any(cell.text == "Theme: Moonlight [t]" for cell in observed[106].cells)

    asyncio.run(scenario())


def test_same_app_preserves_scale_delay_across_runs_but_new_app_starts_independently(monkeypatch):
    async def scenario():
        config, snapshot = inputs()
        clock, reader = [100.0], Reader(snapshot)
        terminal = Terminal(clock, ((101, None), (101.1, "q"), (103.1, "q")))
        app = ObserverApp(config, reader, terminal, host=HOST, wall_clock=lambda: NOW)
        with monkeypatch.context() as patch:
            patch.setattr(asyncio.get_running_loop(), "time", lambda: clock[0])
            patch.setattr("joi_observer.tui.layout.time.monotonic", lambda: clock[0])
            await app.run()
            clock[0] = 103.0
            await app.run()
            clock[0] = 103.0
            fresh_terminal = Terminal(clock, ((103.1, "q"),))
            fresh_app = ObserverApp(config, reader, fresh_terminal, host=HOST, wall_clock=lambda: NOW)
            await fresh_app.run()
        assert terminal.events == ["enter", "restore", "enter", "restore"]
        assert labels(terminal.frames[-1][1]) == ["Scale ≤ 200 tok/s"]
        assert labels(fresh_terminal.frames[0][1]) == ["Scale ≤ 50 tok/s"]
        assert fresh_terminal.events == ["enter", "restore"]

    asyncio.run(scenario())
