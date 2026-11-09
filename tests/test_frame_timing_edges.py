"""Large finite clock values and ready-input fairness through public interfaces."""

import asyncio
from datetime import datetime, timedelta, timezone
import math

import pytest

from joi_observer.config import AppConfig, ModelConfig, ModelType
from joi_observer.data.models import StateSnapshot
from joi_observer.tui.app import ObserverApp
from joi_observer.tui.layout import HostInfo, TerminalSize
from joi_observer.tui.timing import FrameSchedule


@pytest.mark.parametrize("start", (1e20, 1e300, 1e308, 10**5000),
                         ids=("large-float", "huge-float", "near-float-limit", "huge-integer"))
def test_large_finite_origin_advances_without_rounding_back_to_itself(start):
    schedule = FrameSchedule(start)
    assert schedule.due(start)
    schedule.advance(start)
    assert not schedule.due(start)
    assert schedule.timeout(start) == pytest.approx(1 / 60)
    schedule.advance(start)
    assert schedule.timeout(start) == pytest.approx(1 / 60)


@pytest.mark.parametrize("now", (1e308, 10**5000), ids=("huge-float-gap", "huge-integer-gap"))
def test_huge_stall_skips_expired_ticks_without_overflow_or_accumulating_work(now):
    schedule = FrameSchedule(0)
    schedule.advance(now)
    assert not schedule.due(now)
    assert schedule.timeout(now) == pytest.approx(1 / 60)
    schedule.advance(now)
    assert schedule.timeout(now) == pytest.approx(1 / 60)
    assert schedule.timeout(0) == 0.05


def test_huge_integer_origin_retains_phase_and_rejects_backward_advance_atomically():
    start = 10**5000
    schedule = FrameSchedule(start)
    schedule.advance(start)
    assert schedule.due(start + 1)
    schedule.advance(start + 1)
    assert not schedule.due(start + 1)
    assert schedule.timeout(start + 1) == pytest.approx(1 / 60)
    with pytest.raises(ValueError):
        schedule.advance(start)
    assert schedule.timeout(start + 1) == pytest.approx(1 / 60)
    assert schedule.timeout(start) == 0.05


def test_always_ready_input_still_yields_to_other_tasks(monkeypatch):
    async def scenario():
        clock = [0.0]
        sibling_ticks = []

        class Reader:
            def snapshot(self):
                return StateSnapshot(())

        class ReadyTerminal:
            def __init__(self):
                self.reads = 0
                self.draw_times = []
                self.lifecycle = []

            def enter(self):
                self.lifecycle.append("enter")

            def restore(self):
                self.lifecycle.append("restore")

            def size(self):
                return TerminalSize(120, 36)

            def render(self, frame):
                self.draw_times.append(clock[0])

            async def read_key(self, timeout):
                assert 0 < timeout <= 0.05
                self.reads += 1
                assert self.reads < 100, "Ready input starved the sibling task"
                clock[0] += 0.001
                # Deliberately no await here: an injected ready port is legal.
                return "q" if len(sibling_ticks) == 8 else "t"

        async def sibling():
            for _ in range(8):
                await asyncio.sleep(0)
                sibling_ticks.append(clock[0])

        terminal = ReadyTerminal()
        app = ObserverApp(AppConfig(mount_points=()), Reader(), terminal,
                          host=HostInfo("offline", "Ubuntu"),
                          wall_clock=lambda: datetime(2026, 11, 4, tzinfo=timezone.utc))
        with monkeypatch.context() as patch:
            patch.setattr(asyncio.get_running_loop(), "time", lambda: clock[0])
            other = asyncio.create_task(sibling())
            await app.run()
            await other
        assert len(sibling_ticks) == 8
        assert terminal.draw_times == [0.0]
        assert terminal.lifecycle == ["enter", "restore"]

    asyncio.run(scenario())


def test_near_deadline_draws_do_not_starve_a_pending_quit(monkeypatch):
    """AC-609: crossing a deadline during bookkeeping must not starve input.

    Model a terminal whose flush finishes just before each 60 Hz boundary.
    A uniform microsecond of elapsed bookkeeping time between monotonic-clock
    observations crosses that boundary. The clock does not depend on which
    caller reads it, and the real schedule, app, and composition stay in use.
    """
    async def scenario():
        clock = [0.0]

        def monotonic_time():
            now = clock[0]
            clock[0] += 0.000001
            return now

        class FrameLimitReached(Exception):
            """Bound this test even if the ready q is never polled."""

        class Reader:
            def snapshot(self):
                return StateSnapshot(())

        class NearDeadlineTerminal:
            def __init__(self):
                self.draws = 0
                self.reads = 0
                self.lifecycle = []

            def enter(self):
                self.lifecycle.append("enter")

            def restore(self):
                self.lifecycle.append("restore")

            def size(self):
                return TerminalSize(120, 40)

            def render(self, frame):
                self.draws += 1
                if self.draws >= 30:
                    raise FrameLimitReached
                next_boundary = (math.floor(clock[0] * 60) + 1) / 60
                clock[0] = next_boundary - 0.0000005

            async def read_key(self, timeout):
                assert 0 < timeout <= 0.05
                self.reads += 1
                return "q"  # Already buffered before the first frame.

        terminal = NearDeadlineTerminal()
        app = ObserverApp(AppConfig(mount_points=()), Reader(), terminal,
                          host=HostInfo("offline", "Ubuntu"),
                          wall_clock=lambda: datetime(2026, 11, 4, tzinfo=timezone.utc))
        with monkeypatch.context() as patch:
            patch.setattr(asyncio.get_running_loop(), "time", monotonic_time)
            try:
                await app.run()
            except FrameLimitReached:
                pass
        assert terminal.lifecycle == ["enter", "restore"]
        assert terminal.reads == 1, (
            f"Ready q was never read across {terminal.draws} near-deadline frames"
        )
        assert terminal.draws < 30

    asyncio.run(scenario())


def _run_near_deadline_input(monkeypatch, keys):
    """Uniform clock bookkeeping and a slow external terminal, with real app state."""
    async def scenario():
        clock, last_observed = [0.0], [0.0]
        sibling_ticks = []
        stopped = False

        def monotonic_time():
            last_observed[0] = clock[0]
            clock[0] += 0.000001
            return last_observed[0]

        class Reader:
            reads = 0

            def snapshot(self):
                self.reads += 1
                return StateSnapshot(())

        class Terminal:
            def __init__(self):
                self.keys = list(keys)
                self.frames, self.draw_times, self.reads, self.lifecycle = [], [], [], []

            def enter(self):
                self.lifecycle.append("enter")

            def restore(self):
                self.lifecycle.append("restore")

            def size(self):
                return TerminalSize(120, 40)

            def render(self, frame):
                assert len(self.frames) < 30, "Slow draws starved the scheduled input"
                self.frames.append(frame)
                self.draw_times.append(clock[0])
                clock[0] = (math.floor(clock[0] * 60) + 1) / 60 - 0.0000005

            async def read_key(self, timeout):
                assert 0 < timeout <= 0.05
                assert self.keys, "App read after the queued quit"
                self.reads.append((last_observed[0], timeout))
                key = self.keys.pop(0)
                if key is None:
                    clock[0] += timeout
                # Ready keys intentionally return without an await. The app
                # still owes both other tasks and the next normal frame time.
                return key

        async def sibling():
            while not stopped:
                sibling_ticks.append(clock[0])
                await asyncio.sleep(0)

        terminal, reader = Terminal(), Reader()
        config = AppConfig(mount_points=(), models=(
            ModelConfig("first", ModelType.CHAT, "First", "http://offline.invalid:8000"),
            ModelConfig("second", ModelType.CHAT, "Second", "http://offline.invalid:8001"),
        ))
        epoch = datetime(2026, 11, 4, tzinfo=timezone.utc)
        app = ObserverApp(config, reader, terminal, host=HostInfo("offline", "Ubuntu"),
                          wall_clock=lambda: epoch + timedelta(seconds=clock[0] * 1000))
        with monkeypatch.context() as patch:
            patch.setattr(asyncio.get_running_loop(), "time", monotonic_time)
            other = asyncio.create_task(sibling())
            try:
                await app.run()
            finally:
                stopped = True
                await other
        assert terminal.lifecycle == ["enter", "restore"]
        assert not terminal.keys
        assert reader.reads == len(terminal.frames)
        assert sibling_ticks
        # Every input budget ends at the next slot of the original 60 Hz grid,
        # not at a fresh period relative to a slow render's completion time.
        for observed_at, timeout in terminal.reads:
            next_tick = (math.floor(observed_at * 60) + 1) / 60
            assert observed_at + timeout == pytest.approx(next_tick, rel=0, abs=1e-12)
        assert all(later - earlier >= 1 / 60 - 0.0001
                   for earlier, later in zip(terminal.draw_times, terminal.draw_times[1:]))
        return terminal

    return asyncio.run(scenario())


def test_near_deadline_draws_keep_navigation_and_theme_for_the_next_normal_frame(monkeypatch):
    terminal = _run_near_deadline_input(monkeypatch, ("down", "t", None, "q"))
    assert len(terminal.reads) == 4
    assert len(terminal.frames) == 2  # Ready keys must not create extra frames.
    initial, updated = terminal.frames
    assert initial.theme == "hologram" and updated.theme == "moonlight"
    assert any(cell.text == "First" and cell.role == "primary" for cell in initial.cells)
    assert any(cell.text == "Second" and cell.role == "primary" for cell in updated.cells)


def test_continuous_near_deadline_draws_without_input_keep_phase_and_task_fairness(monkeypatch):
    terminal = _run_near_deadline_input(monkeypatch, (None,) * 5 + ("q",))
    assert len(terminal.reads) == 6
    assert len(terminal.frames) == 6
    assert all(frame.theme == "hologram" for frame in terminal.frames)
    assert terminal.draw_times[-1] < 1


@pytest.mark.parametrize("phase_us", (1.5, 2.5, 3.5))
def test_periodic_input_before_deadlines_cannot_starve_normal_frames(monkeypatch, phase_us):
    """A legal input phase must not repeatedly discard an undrawn frame slot.

    Events arrive every 1/60 second, independently of the app, just before its
    original frame boundaries. Each clock observation incurs the same small
    bookkeeping cost. The terminal draws immediately and waits for a real
    queued event or the full requested timeout; it never returns None early.
    """
    async def scenario():
        clock = [0.0]

        def monotonic_time():
            now = clock[0]
            clock[0] += 0.000001
            return now

        class Reader:
            def snapshot(self):
                return StateSnapshot(())

        class PeriodicInputTerminal:
            def __init__(self):
                self.events = [(tick / 60 - phase_us / 1_000_000,
                                "t" if tick < 61 else "q")
                               for tick in range(1, 62)]
                self.frames, self.draw_times, self.lifecycle = [], [], []
                self.reads = 0

            def enter(self):
                self.lifecycle.append("enter")

            def restore(self):
                self.lifecycle.append("restore")

            def size(self):
                return TerminalSize(120, 40)

            def render(self, frame):
                assert len(self.frames) < 100, "Rendering starved the queued quit"
                self.frames.append(frame)
                self.draw_times.append(clock[0])

            async def read_key(self, timeout):
                assert 0 < timeout <= 0.05
                self.reads += 1
                assert self.reads < 200, "Input loop failed to make bounded progress"
                assert self.events, "App read after the queued quit"
                deadline = clock[0] + timeout
                if self.events[0][0] <= deadline:
                    when, key = self.events.pop(0)
                    clock[0] = max(clock[0], when)
                else:
                    clock[0] = deadline
                    key = None
                await asyncio.sleep(0)
                return key

        terminal = PeriodicInputTerminal()
        app = ObserverApp(AppConfig(mount_points=()), Reader(), terminal,
                          host=HostInfo("offline", "Ubuntu"),
                          wall_clock=lambda: datetime(2026, 11, 4, tzinfo=timezone.utc))
        with monkeypatch.context() as patch:
            patch.setattr(asyncio.get_running_loop(), "time", monotonic_time)
            await app.run()
        assert terminal.lifecycle == ["enter", "restore"]
        assert not terminal.events
        assert clock[0] > 1
        assert len(terminal.frames) > 1, (
            f"Only the initial frame was drawn during {terminal.reads} input polls"
        )
        assert {frame.theme for frame in terminal.frames} == {"hologram", "moonlight"}
        assert all(later - earlier >= 1 / 60 - 0.0001
                   for earlier, later in zip(terminal.draw_times, terminal.draw_times[1:]))

    asyncio.run(scenario())


@pytest.mark.parametrize("phase_us", (-1.5, 0, 1.5, 2.5, 3.5, 5.5))
@pytest.mark.parametrize("draw_mode", ("fast", "mixed"))
def test_periodic_input_and_resize_keep_both_drawing_and_input_progress(monkeypatch, phase_us, draw_mode):
    """Exercise both deadline-crossing directions across small/normal layouts."""
    async def scenario():
        clock, last_observed = [0.0], [0.0]
        original = TerminalSize(120, 40)
        expanded, small = TerminalSize(124, 44), TerminalSize(80, 24)

        def monotonic_time():
            last_observed[0] = clock[0]
            clock[0] += 0.000001
            return last_observed[0]

        class Reader:
            reads = 0
            value = StateSnapshot(())

            def snapshot(self):
                self.reads += 1
                return self.value

        class Terminal:
            def __init__(self):
                self.current_size = original
                self.expected_theme, self.expected_model = "hologram", 0
                self.frames, self.draw_times, self.reads, self.lifecycle = [], [], [], []
                self.deliveries = []
                replacements = {16: expanded, 32: small, 48: original, 80: "q"}
                self.events = [(tick / 60 - phase_us / 1_000_000,
                                replacements.get(tick, ("t", "down", "t", "up")[(tick - 1) % 4]))
                               for tick in range(1, 81)]

            def enter(self):
                self.lifecycle.append("enter")

            def restore(self):
                self.lifecycle.append("restore")

            def size(self):
                return self.current_size

            def render(self, frame):
                assert len(self.frames) < 150, "Drawing starved the pending input"
                assert frame.theme == self.expected_theme
                assert frame.too_small is (self.current_size == small)
                if not frame.too_small:
                    assert frame.regions[0].width == self.current_size.columns
                    name = ("First", "Second")[self.expected_model]
                    assert any(cell.text == name and cell.role == "primary" for cell in frame.cells)
                self.frames.append((self.current_size, frame))
                self.draw_times.append(clock[0])
                if draw_mode == "mixed" and len(self.frames) % 3 == 1:
                    clock[0] = (math.floor(clock[0] * 60) + 1) / 60 - 0.0000005

            async def read_key(self, timeout):
                assert 0 < timeout <= 0.05
                assert len(self.reads) < 250, "Input polling starved normal drawing"
                assert self.events, "App polled after quit"
                self.reads.append((last_observed[0], timeout))
                deadline = clock[0] + timeout
                if self.events[0][0] <= deadline:
                    arrival, event = self.events.pop(0)
                    clock[0] = max(clock[0], arrival)
                    self.deliveries.append((arrival, clock[0]))
                    if isinstance(event, TerminalSize):
                        self.current_size, key = event, None
                    else:
                        key = event
                        if key == "t":
                            self.expected_theme = "moonlight" if self.expected_theme == "hologram" else "hologram"
                        elif key in ("up", "down"):
                            self.expected_model = min(1, max(0, self.expected_model + (1 if key == "down" else -1)))
                else:
                    clock[0], key = deadline, None
                await asyncio.sleep(0)
                return key

        reader, terminal = Reader(), Terminal()
        config = AppConfig(mount_points=(), models=(
            ModelConfig("first", ModelType.CHAT, "First", "http://offline.invalid:8000"),
            ModelConfig("second", ModelType.CHAT, "Second", "http://offline.invalid:8001"),
        ))
        epoch = datetime(2026, 11, 4, tzinfo=timezone.utc)
        app = ObserverApp(config, reader, terminal, host=HostInfo("offline", "Ubuntu"),
                          wall_clock=lambda: epoch + timedelta(seconds=clock[0] * 1000))
        with monkeypatch.context() as patch:
            patch.setattr(asyncio.get_running_loop(), "time", monotonic_time)
            await app.run()
        assert terminal.lifecycle == ["enter", "restore"]
        assert not terminal.events and len(terminal.deliveries) == 80
        assert reader.reads == len(terminal.frames)
        # Every layout stage receives multiple current frames. Neither a
        # steady input phase nor a resize may hide a prolonged drawing stall.
        for start, end in ((0, 16 / 60), (16 / 60, 32 / 60), (32 / 60, 48 / 60), (48 / 60, 80 / 60)):
            assert sum(start + 0.0001 < instant < end - 0.0001 for instant in terminal.draw_times) >= 3
        assert max(later - earlier for earlier, later in zip(terminal.draw_times, terminal.draw_times[1:])) < 3 / 60 + 0.001
        # Resize frames can occur shortly before the next normal tick. Remove
        # only those externally identifiable size-change draws from the rate
        # check; the normal frames on either side must still retain their gap.
        normal_draw_times = [instant for index, instant in enumerate(terminal.draw_times)
                             if index == 0 or terminal.frames[index][0] == terminal.frames[index - 1][0]]
        assert all(later - earlier >= 1 / 60 - 0.0001
                   for earlier, later in zip(normal_draw_times, normal_draw_times[1:]))
        assert max(delivered - arrived for arrived, delivered in terminal.deliveries) < 2 / 60 + 0.0001
        for observed_at, timeout in terminal.reads:
            next_tick = (math.floor(observed_at * 60) + 1) / 60
            assert observed_at + timeout == pytest.approx(next_tick, rel=0, abs=1e-12)
        assert {size for size, _ in terminal.frames} == {original, expanded, small}
        assert terminal.frames[-1][0] == original

    asyncio.run(scenario())
