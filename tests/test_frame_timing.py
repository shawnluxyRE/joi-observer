"""Fixed 60 Hz presentation deadlines with controlled offline clocks.

Only time and terminal IO are substituted. App composition, navigation, and
the public scheduling interface remain real; no real sleeps or collectors run.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from joi_observer.config import AppConfig, ModelConfig, ModelType
from joi_observer.data.models import StateSnapshot
from joi_observer.tui.app import ObserverApp
from joi_observer.tui.layout import HostInfo, TerminalSize
from joi_observer.tui.timing import FRAME_INTERVAL, FRAME_RATE, FrameSchedule


@pytest.mark.parametrize("start", (0, 12.5))
def test_first_frame_is_due_immediately_and_queries_are_read_only(start):
    assert FRAME_RATE == 60 and FRAME_INTERVAL == 1 / 60
    schedule = FrameSchedule(start)
    for _ in range(3):
        assert schedule.due(start)
        assert schedule.timeout(start) == 0
    assert schedule.advance(start) is None
    assert not schedule.due(start)
    assert schedule.timeout(start) == pytest.approx(1 / 60)


def test_exact_deadlines_are_due_and_each_completion_uses_the_next_original_tick():
    schedule = FrameSchedule(0)
    for tick in range(61):
        now = tick / 60
        assert schedule.due(now)
        assert schedule.timeout(now) == 0
        schedule.advance(now)
        assert not schedule.due(now)
        assert schedule.timeout(now) == pytest.approx(1 / 60)
        assert not schedule.due((tick + 1) / 60 - 0.000001)


def test_slow_completion_skips_elapsed_slots_without_catchup_or_drift():
    schedule = FrameSchedule(0)
    schedule.advance(0.112)
    assert not schedule.due(0.115)
    assert schedule.timeout(0.112) == pytest.approx(7 / 60 - 0.112)
    assert schedule.due(7 / 60)
    schedule.advance(0.112)
    schedule.advance(0.115)
    assert schedule.timeout(0.115) == pytest.approx(7 / 60 - 0.115)
    schedule.advance(7 / 60)
    assert schedule.timeout(7 / 60) == pytest.approx(1 / 60)


def test_many_small_draw_costs_do_not_accumulate_in_deadlines():
    start = 4.25
    schedule = FrameSchedule(start)
    for tick in range(100):
        complete = start + tick / 60 + 0.004
        schedule.advance(complete)
        next_tick = start + (tick + 1) / 60
        assert schedule.timeout(complete) == pytest.approx(next_tick - complete)
        assert schedule.due(next_tick)


def test_query_time_order_is_unrestricted_and_timeout_is_capped():
    schedule = FrameSchedule(10)
    schedule.advance(10.91)
    assert schedule.timeout(10) == 0.05
    assert schedule.due(11)
    assert not schedule.due(10.915)
    assert schedule.timeout(10.915) == pytest.approx(10 + 55 / 60 - 10.915)
    assert schedule.timeout(11) == 0
    assert schedule.timeout(10) == 0.05


@pytest.mark.parametrize("invalid", (-1, float("inf"), float("-inf"), float("nan"), True, None, "0"))
def test_invalid_start_is_rejected(invalid):
    with pytest.raises(ValueError):
        FrameSchedule(invalid)


@pytest.mark.parametrize("method", ("due", "timeout", "advance"))
@pytest.mark.parametrize("invalid", (9.99, float("inf"), float("-inf"), float("nan"), True, None, "10"))
def test_invalid_time_is_rejected_without_changing_schedule(method, invalid):
    schedule = FrameSchedule(10)
    schedule.advance(10)
    before = schedule.timeout(10)
    with pytest.raises(ValueError):
        getattr(schedule, method)(invalid)
    assert schedule.timeout(10) == before
    assert not schedule.due(10)
    schedule.advance(10)
    assert schedule.timeout(10) == before


def test_backward_advance_is_rejected_atomically_but_queries_can_go_back():
    schedule = FrameSchedule(10)
    schedule.advance(10.12)
    before = schedule.timeout(10.12)
    assert schedule.timeout(10) == 0.05
    with pytest.raises(ValueError):
        schedule.advance(10.11)
    assert schedule.timeout(10.12) == before
    schedule.advance(10.12)
    assert schedule.timeout(10.12) == before


class ClockTerminal:
    """External key/resize events advance a fake monotonic clock up to timeout."""

    def __init__(self, clock, events, *, draw_costs=()):
        self.clock = clock
        self.events = list(events)
        self.draw_costs = tuple(draw_costs)
        self.draw_times, self.frames, self.reads, self.lifecycle = [], [], [], []
        self.current_size = TerminalSize(120, 40)

    def enter(self):
        self.lifecycle.append("enter")

    def restore(self):
        self.lifecycle.append("restore")

    def size(self):
        return self.current_size

    def render(self, frame):
        self.draw_times.append(self.clock[0])
        self.frames.append(frame)
        index = len(self.frames) - 1
        if index < len(self.draw_costs):
            self.clock[0] += self.draw_costs[index]

    async def read_key(self, timeout):
        assert 0 < timeout <= 0.05
        assert len(self.reads) < 200, "App failed to progress or exit under controlled time"
        self.reads.append((self.clock[0], timeout))
        until = self.clock[0] + timeout
        if self.events and self.events[0][0] <= until + 1e-12:
            when, value = self.events.pop(0)
            self.clock[0] = max(self.clock[0], when)
            if isinstance(value, TerminalSize):
                self.current_size = value
                result = None
            else:
                result = value
        else:
            self.clock[0] = until
            result = None
        await asyncio.sleep(0)
        return result


def run_timed_app(monkeypatch, events, *, draw_costs=()):
    async def scenario():
        clock = [0.0]
        terminal = ClockTerminal(clock, events, draw_costs=draw_costs)

        class Reader:
            def snapshot(self):
                return StateSnapshot((), revision=len(terminal.frames))

        config = AppConfig(mount_points=(), models=(
            ModelConfig("first", ModelType.CHAT, "First", "http://offline.invalid:8000"),
            ModelConfig("second", ModelType.CHAT, "Second", "http://offline.invalid:8001"),
        ))
        # Each scheduled frame has distinct wall-clock text, so a legitimate
        # identical-frame write optimization cannot hide deadline observations.
        epoch = datetime(2026, 11, 4, tzinfo=timezone.utc)
        app = ObserverApp(config, Reader(), terminal, host=HostInfo("offline", "Ubuntu"),
                          wall_clock=lambda: epoch + timedelta(seconds=clock[0] * 1000))
        with monkeypatch.context() as patch:
            patch.setattr(asyncio.get_running_loop(), "time", lambda: clock[0])
            await app.run()
        assert terminal.lifecycle == ["enter", "restore"]
        assert not terminal.events
        return terminal

    return asyncio.run(scenario())


def test_app_renders_on_60_hz_deadlines_and_never_reads_past_next_deadline(monkeypatch):
    terminal = run_timed_app(monkeypatch, ((0.205, "q"),))
    assert terminal.draw_times == pytest.approx([tick / 60 for tick in range(13)])
    assert len(terminal.reads) == 13
    assert [timeout for _, timeout in terminal.reads] == pytest.approx([1 / 60] * 13)


def test_input_burst_changes_next_frame_without_adding_frames(monkeypatch):
    terminal = run_timed_app(monkeypatch, (
        (0.001, "down"), (0.002, "up"), (0.003, "down"), (0.004, "t"),
        (0.005, "left"), (0.006, "right"), (0.007, "enter"), (0.008, "p"),
        (0.0375, "q"),
    ))
    assert terminal.draw_times == pytest.approx([0, 1 / 60, 2 / 60])
    assert any(cell.text == "First" and cell.role == "primary" for cell in terminal.frames[0].cells)
    assert all(any(cell.text == "Second" and cell.role == "primary" for cell in frame.cells)
               for frame in terminal.frames[1:])
    for when, timeout in terminal.reads:
        assert when + timeout <= next(tick / 60 for tick in range(1, 5) if tick / 60 > when + 1e-12) + 1e-12


def test_slow_app_draw_skips_missed_frames_and_keeps_original_phase(monkeypatch):
    terminal = run_timed_app(monkeypatch, ((0.18, "q"),), draw_costs=(0.087, 0.005))
    assert terminal.draw_times == pytest.approx([0, 0.1, 7 / 60, 8 / 60, 9 / 60, 10 / 60])
    assert terminal.reads[0] == pytest.approx((0.087, 0.013))
    assert terminal.reads[1] == pytest.approx((0.105, 7 / 60 - 0.105))


def test_resize_draws_immediately_and_preserves_next_original_deadline(monkeypatch):
    terminal = run_timed_app(monkeypatch, (
        (0.01, TerminalSize(122, 40)), (0.02, TerminalSize(124, 40)), (0.075, "q"),
    ))
    assert terminal.draw_times == pytest.approx([0, 0.01, 1 / 60, 0.02, 2 / 60, 3 / 60, 4 / 60])
    assert [frame.regions[0].width for frame in terminal.frames] == [120, 122, 122, 124, 124, 124, 124]
    assert len(set(terminal.draw_times)) == len(terminal.draw_times)
