"""Session navigation through the real app and frame composer, using offline IO.

Assertions describe the finished behavior. A default-theme mismatch remains an
ordinary design-stage failure, never skipped or xfailed.
"""

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from joi_observer.cli import ApplicationRuntime
from joi_observer.collectors.vllm import VllmCollector
from joi_observer.config import AppConfig, LogConfig, ModelConfig, ModelType
from joi_observer.data.models import Metric, ObjectKey, ObjectSpec, StateSnapshot
from joi_observer.data.state import MonitorState
from joi_observer.error_log import ErrorLog
from joi_observer.monitor import Monitor
from joi_observer.tui.app import ObserverApp
from joi_observer.tui.layout import HostInfo, TerminalSize, ViewSelection, compose_frame
from joi_observer.tui.navigation import SessionViewActions
from test_vllm_integration import RawHttp, configs, settle
from test_vllm_view import object_snapshot


HOST = HostInfo("offline-host", "Ubuntu")
NOW = datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc)


def models():
    return tuple(ModelConfig(kind.value, kind, kind.value, f"http://offline.invalid:{8000 + i}")
                 for i, kind in enumerate(ModelType))


def configuration(items=None):
    return AppConfig(models=models() if items is None else items, mount_points=())


def snapshot(config, *, stale=(), revision=1):
    return StateSnapshot(tuple(object_snapshot(item.id, item.type, stale=item.id in stale)
                               for item in config.models), revision)


class ReadOnlyInput:
    """The UI receives no write, registration, sampling or source access method."""

    def __init__(self, samples):
        self.samples = tuple(samples)
        self.index = 0

    def snapshot(self):
        return self.samples[min(self.index, len(self.samples) - 1)]


class ScriptedTerminal:
    """One externally supplied key and optional size/sample change per frame.

    Alternating terminal widths exercises the existing immediate resize redraw,
    avoiding sleeps or a patched application clock in the navigation assertions.
    """

    def __init__(self, keys=("q",), *, reader=None, sizes=None):
        self.keys = tuple(keys)
        self.reader = reader
        self.sizes = tuple(sizes) if sizes else tuple(
            TerminalSize(120 + 2 * (index % 2), 40) for index in range(len(self.keys)))
        self.index = 0
        self.frames = []
        self.events = []

    def enter(self):
        self.events.append("enter")

    def restore(self):
        self.events.append("restore")

    def size(self):
        return self.sizes[min(self.index, len(self.sizes) - 1)]

    def render(self, frame):
        self.frames.append(frame)

    async def read_key(self, timeout):
        assert 0 < timeout <= 0.05
        await asyncio.sleep(0)
        assert self.index < len(self.keys), "The app did not exit on q"
        key = self.keys[self.index]
        self.index += 1
        if self.reader is not None:
            self.reader.index = self.index
        return key


def run_app(config, keys, *, samples=None, sizes=None, actions=None):
    samples = (snapshot(config),) if samples is None else samples
    reader = ReadOnlyInput(samples)
    terminal = ScriptedTerminal(keys, reader=reader, sizes=sizes)
    app = ObserverApp(config, reader, terminal, host=HOST, wall_clock=lambda: NOW, actions=actions)
    before = deepcopy((config, samples))
    asyncio.run(app.run())
    assert (config, samples) == before
    assert terminal.events == ["enter", "restore"]
    return terminal.frames


def region(frame, name):
    return next(item for item in frame.regions if item.name == name)


def detail_cells(frame):
    service = region(frame, "service")
    return tuple(cell for cell in frame.cells
                 if service.row < cell.row < service.row + service.height - 1
                 and cell.column >= service.column + 30)


def selected_name(frame):
    service = region(frame, "service")
    names = [cell.text for cell in detail_cells(frame)
             if cell.row == service.row + 2 and cell.column == service.column + 30]
    assert len(names) == 1, "Detail name must occupy the fixed column after the 24-column rail"
    return names[0]


def detail_metric(frame, label):
    """Read a metric's separate label and numeric value from the public frame."""
    service = region(frame, "service")
    headings = [cell for cell in detail_cells(frame)
                if cell.row == service.row + 9 and cell.text == label]
    assert len(headings) == 1, f"Missing four-column metric label: {label}"
    values = [cell.text for cell in detail_cells(frame)
              if cell.row == service.row + 10 and cell.column == headings[0].column]
    assert len(values) == 1, f"Missing numeric value below metric label: {label}"
    return values[0]


def test_default_app_arrows_traverse_all_types_and_stop_at_both_ends():
    frames = run_app(configuration(), ("up", "down", "down", "down", "up", "up", "up", "q"))
    assert [selected_name(frame) for frame in frames] == [
        "chat", "chat", "embedding", "reranker", "reranker", "embedding", "chat", "chat",
    ]
    for frame, expected in zip(frames, ("chat", "chat", "embedding", "reranker",
                                        "reranker", "embedding", "chat", "chat")):
        text = " ".join(cell.text for cell in detail_cells(frame))
        if expected == "chat":
            assert detail_metric(frame, "DECODE / tok/s") == "100"
            assert detail_metric(frame, "TTFT / s") == "3"
            assert "DECODE HISTORY / tok/s" in text
        else:
            assert detail_metric(frame, "RATE / seq/s") == "3"
            assert detail_metric(frame, "Avg latency / s") == "3"
            assert "RATE HISTORY / seq/s" in text
            assert "TTFT" not in text and "DECODE" not in text


@pytest.mark.parametrize("count", (0, 1))
def test_empty_or_single_model_keeps_global_theme_and_quit_keys(count):
    config = configuration(models()[:count])
    frames = run_app(config, ("up", "down", "left", "right", "t", "up", "down", "t", "q"))
    assert len(frames) == 9
    for frame in frames:
        if count:
            assert selected_name(frame) == "chat"
        else:
            assert any(cell.text == "No models configured" for cell in frame.cells)
    for frame, theme in zip(frames, ["Hologram"] * 5 + ["Moonlight"] * 3 + ["Hologram"]):
        assert any(cell.text == f"Theme: {theme} [t]" for cell in frame.cells)


def test_selected_unavailable_model_survives_snapshot_refresh_and_recovery():
    config = configuration()
    healthy = snapshot(config)
    unavailable = snapshot(config, stale=("embedding",), revision=2)
    recovered = snapshot(config, revision=3)
    frames = run_app(config, ("down", None, None, None, "q"),
                     samples=(healthy, healthy, unavailable, unavailable, recovered))
    assert [selected_name(frame) for frame in frames] == [
        "chat", "embedding", "embedding", "embedding", "embedding",
    ]
    assert any(cell.text == "STALE" for cell in detail_cells(frames[2]))
    assert not any(cell.text == "STALE" for cell in detail_cells(frames[-1]))
    # A sample's availability never becomes a navigation input or selection filter.
    assert [region(frame, "service").row for frame in frames] == [20] * 5


def test_fixed_size_key_burst_updates_next_normal_frame_without_extra_redraws(monkeypatch):
    """Fast input is accumulated without bypassing the ordinary 60Hz budget."""
    async def scenario():
        config = configuration()
        reader = ReadOnlyInput((snapshot(config),))
        clock = [0.0]
        schedule = (
            (0.001, "down"), (0.002, "down"), (0.003, "up"), (0.004, "t"),
            (0.005, "left"), (0.006, "right"), (0.007, "enter"), (0.008, "p"),
            (0.009, "tab"), (1 / 60, None), (2 / 60, None), (0.035, "q"),
        )

        class BurstTerminal(ScriptedTerminal):
            def __init__(self):
                super().__init__(sizes=(TerminalSize(120, 40),))
                self.draw_times = []

            def render(self, frame):
                self.draw_times.append(clock[0])
                super().render(frame)

            async def read_key(self, timeout):
                assert 0 < timeout <= 0.05
                next_deadline = (len(self.frames)) / 60
                assert timeout <= next_deadline - clock[0] + 1e-12
                # Initial rendering precedes input. Every key in this burst
                # must be consumed even though no redraw is due yet.
                if self.index < 10:
                    assert len(self.frames) == 1
                assert self.index < len(schedule), "The app did not exit on q"
                clock[0], key = schedule[self.index]
                self.index += 1
                await asyncio.sleep(0)
                return key

        terminal = BurstTerminal()
        app = ObserverApp(config, reader, terminal, host=HOST,
                          wall_clock=lambda: NOW + timedelta(seconds=clock[0] * 100))
        # Only the external clock changes; default actions, application loop
        # and frame composition remain real. Restore it before loop teardown.
        with monkeypatch.context() as patch:
            patch.setattr(asyncio.get_running_loop(), "time", lambda: clock[0])
            await app.run()

        assert terminal.draw_times == pytest.approx([0.0, 1 / 60, 2 / 60])
        assert [selected_name(frame) for frame in terminal.frames] == [
            "chat", "embedding", "embedding",
        ]
        for frame in terminal.frames[1:]:
            assert any(cell.text == "Theme: Moonlight [t]" for cell in frame.cells)
            assert frame.regions == terminal.frames[0].regions
        assert terminal.index == len(schedule)
        assert terminal.events == ["enter", "restore"]

    asyncio.run(scenario())


def test_small_window_processes_navigation_and_theme_then_restores_selection():
    sizes = (TerminalSize(120, 40), TerminalSize(80, 24), TerminalSize(81, 24),
             TerminalSize(82, 24), TerminalSize(120, 40))
    frames = run_app(configuration(), ("down", "down", "t", None, "q"), sizes=sizes)
    assert all(frame.too_small for frame in frames[1:4])
    assert not frames[-1].too_small
    assert selected_name(frames[-1]) == "reranker"
    assert any(cell.text == "Theme: Moonlight [t]" for cell in frames[-1].cells)


def test_long_list_selection_stays_visible_when_terminal_shrinks_and_grows():
    items = tuple(ModelConfig(f"m{i:02}", ModelType.CHAT, f"M{i:02}", "http://offline.invalid")
                  for i in range(12))
    keys = ("down",) * 11 + (None, None, "q")
    sizes = tuple(TerminalSize(120 + 2 * (i % 2), 40) for i in range(12)) + (
        TerminalSize(120, 36), TerminalSize(120, 48),
    )
    frames = run_app(configuration(items), keys, sizes=sizes)
    assert selected_name(frames[-1]) == "M11"
    for frame in frames:
        service = region(frame, "service")
        selected = selected_name(frame)
        assert any(cell.text.removeprefix("› ") == selected and cell.role == "primary"
                   and cell.column < service.column + 26
                   and service.row < cell.row < service.row + service.height - 1
                   for cell in frame.cells)
        assert region(frame, "footer").row + 1 - service.row == (
            region(frame, "footer").row + 1) // 2


def test_disabled_keys_do_not_leave_selected_model_or_change_the_upper_panels():
    config = configuration()
    keys = ("down", "left", "right", "enter", "p", "tab", "mouse", "q")
    frames = run_app(config, keys)
    assert [selected_name(frame) for frame in frames[1:]] == ["embedding"] * 7
    for frame in frames:
        assert any("WebUI (disabled)" in cell.text for cell in frame.cells)
        assert len([item for item in frame.regions if item.name == "service"]) == 1
    original_upper = tuple(cell for cell in frames[0].cells if cell.row < 20)
    for frame in frames[2::2]:  # The same physical size must retain the same upper content.
        assert tuple(cell for cell in frame.cells if cell.row < 20) == original_upper


@pytest.mark.parametrize("falsey", (False, True), ids=("truthy", "falsey"))
def test_injected_actions_are_preserved_and_only_supported_keys_are_dispatched(falsey):
    class InjectedActions:
        def __init__(self):
            self.received = []
            self.selection_reads = 0

        def __bool__(self):
            return not falsey

        def selection(self):
            self.selection_reads += 1
            return ViewSelection("reranker", "hologram")

        def on_key(self, key):
            self.received.append(key)

    actions = InjectedActions()
    frames = run_app(configuration(), ("down", "t", "left", "right", "enter", "p", "tab", "q"),
                     actions=actions)
    assert actions.received == ["down", "t", "left", "right"]
    assert actions.selection_reads == len(frames)
    assert all(selected_name(frame) == "reranker" for frame in frames)
    assert all(any(cell.text == "Theme: Hologram [t]" for cell in frame.cells) for frame in frames)


def test_new_app_session_does_not_reuse_previous_model_or_theme():
    config = configuration()
    previous = run_app(config, ("down", "t", "q"))
    assert selected_name(previous[-1]) == "embedding"
    assert any(cell.text == "Theme: Moonlight [t]" for cell in previous[-1].cells)
    fresh = run_app(config, ("q",))
    assert selected_name(fresh[0]) == "chat"
    assert any(cell.text == "Theme: Hologram [t]" for cell in fresh[0].cells)


def test_same_app_preserves_model_and_theme_across_sequential_runs():
    config = configuration()
    reader = ReadOnlyInput((snapshot(config),))
    terminal = ScriptedTerminal(("down", "t", "q", "q"))
    app = ObserverApp(config, reader, terminal, host=HOST, wall_clock=lambda: NOW)

    async def scenario():
        await app.run()
        previous_count = len(terminal.frames)
        assert selected_name(terminal.frames[-1]) == "embedding"
        assert any(cell.text == "Theme: Moonlight [t]" for cell in terminal.frames[-1].cells)
        await app.run()
        assert len(terminal.frames) == previous_count + 1
        assert selected_name(terminal.frames[-1]) == "embedding"
        assert any(cell.text == "Theme: Moonlight [t]" for cell in terminal.frames[-1].cells)
        assert terminal.events == ["enter", "restore", "enter", "restore"]

    asyncio.run(scenario())


def test_footer_lists_only_live_keys_and_service_entry_marks_vllm_current():
    frame = compose_frame(StateSnapshot(()), configuration(), TerminalSize(120, 41), HOST, NOW)
    footer, switch, service = (region(frame, name) for name in ("footer", "service_switch", "service"))
    footer_cells = tuple(cell for cell in frame.cells if cell.row == footer.row)
    assert [(cell.text, cell.role) for cell in footer_cells] == [
        ("↑↓ Select model    t Theme    q Quit", "primary"),
    ]
    switch_cells = tuple(cell for cell in frame.cells if cell.row == switch.row)
    assert any(cell.text == "vLLM" and cell.role == "primary" for cell in switch_cells)
    assert any("WebUI (disabled)" in cell.text and cell.role == "muted" for cell in switch_cells)
    assert service.height + switch.height + footer.height == 41 // 2


def test_production_composition_navigates_without_starting_or_rebuilding_sources(tmp_path, monkeypatch):
    """Run the real production app after prepare; Monitor alone owns source polling."""
    class IdleDiscovery:
        spec = ObjectSpec(ObjectKey("gpu_inventory", "local"), (Metric("device_count", None),))

        async def discover(self):
            pytest.fail("UI navigation must not discover hardware")

        async def close(self):
            pass

    monkeypatch.setattr("joi_observer.cli.build_hardware_sources",
                        lambda cfg: SimpleNamespace(collectors=(), discovery=IdleDiscovery()))
    terminal = ScriptedTerminal(("down", "t", "left", "right", "enter", "p", "q"))
    monkeypatch.setattr("joi_observer.cli.CursesTerminal", lambda: terminal)
    config = replace(configuration(), logging=LogConfig(directory=tmp_path / "logs"))
    ports = []

    def http_factory():
        port = RawHttp(config.models[len(ports)])
        ports.append(port)
        return port

    async def scenario():
        runtime = ApplicationRuntime(config, vllm_http_factory=http_factory)
        try:
            assert runtime.prepare_log()
            reader = runtime.components.app.reader
            before = reader.snapshot()
            await runtime.components.app.run()
            assert reader.snapshot() == before
            assert len(ports) == len(config.models)
            assert all(not port.calls for port in ports)
            assert selected_name(terminal.frames[-1]) == "embedding"
            assert any(cell.text == "Theme: Moonlight [t]" for cell in terminal.frames[-1].cells)
        finally:
            await runtime.close()
        assert all(port.closed for port in ports)

    asyncio.run(scenario())


def test_real_monitor_sampling_and_histories_are_independent_of_navigation(tmp_path):
    """Only received HTTP bytes and the sampling clock are external substitutes."""
    async def scenario():
        config = replace(configuration(configs()), logging=LogConfig(directory=tmp_path / "logs"))
        ports = tuple(RawHttp(item) for item in config.models)
        collectors = tuple(VllmCollector(item, port) for item, port in zip(config.models, ports))
        clock = [0.0]
        state = MonitorState(tuple(collector.spec for collector in collectors), clock=lambda: clock[0])
        log = ErrorLog(config.logging)
        assert log.prepare()
        monitor = Monitor(collectors, state, log, clock=lambda: clock[0])
        try:
            await settle(monitor)
            clock[0] = 2.0
            await settle(monitor)
            before = state.snapshot()
            expected_snapshot = before
            expected_calls = tuple(tuple(port.calls) for port in ports)
            assert all(len(item.history) == 2 for item in before.objects)
            actions = SessionViewActions(config.models)
            checkpoints = []

            class SamplingTerminal(ScriptedTerminal):
                async def read_key(self, timeout):
                    nonlocal expected_snapshot, expected_calls
                    # Keys and completed frame draws themselves must not update
                    # state or call any source. Only this external sampling
                    # schedule advances the clock and polls the real Monitor.
                    assert state.snapshot() == expected_snapshot
                    assert tuple(tuple(port.calls) for port in ports) == expected_calls
                    if self.index in (6, 7):
                        # The previous p/Enter has been handled, while the UI
                        # session is still active and q has not yet been sent.
                        assert self.events == ["enter"]
                        clock[0] += 2.0
                        await settle(monitor)
                        refreshed = state.snapshot()
                        assert all(len(item.history) == self.index - 3
                                   and item.sampled_at == clock[0] and not item.stale
                                   for item in refreshed.objects)
                        assert refreshed.revision > expected_snapshot.revision
                        for item, port, previous in zip(config.models, ports, expected_calls):
                            assert port.calls == list(previous) + [
                                item.base_url + suffix for suffix in ("/version", "/v1/models", "/metrics")
                            ]
                        expected_snapshot = refreshed
                        expected_calls = tuple(tuple(port.calls) for port in ports)
                        checkpoints.append("p" if self.index == 6 else "enter")
                    return await super().read_key(timeout)

            terminal = SamplingTerminal(("down", "down", "up", "left", "right", "p", "enter", "t", "q"))
            app = ObserverApp(config, state, terminal, host=HOST, wall_clock=lambda: NOW, actions=actions)
            await app.run()
            assert actions.selection() == ViewSelection("embedding", "moonlight")
            assert selected_name(terminal.frames[-1]) == config.models[1].name
            assert checkpoints == ["p", "enter"]
            assert state.snapshot() == expected_snapshot
            assert tuple(tuple(port.calls) for port in ports) == expected_calls
            assert all(len(item.history) == 4 for item in state.snapshot().objects)
            assert all(len(item.history) == 2 for item in before.objects)
        finally:
            await monitor.stop()
            await log.close()
        assert all(port.closed for port in ports)

    asyncio.run(scenario())


def test_default_app_keeps_model_and_gpu_selection_consistent_during_discovery_and_failure():
    """Real app navigation shares one selection across changing hardware samples."""
    from joi_observer.data.models import ObjectSnapshot

    uuids = tuple(f"GPU-00000000-0000-0000-0000-{index:012d}" for index in range(2))
    items = tuple(replace(model, gpu_ids=aliases) for model, aliases in zip(
        models(), ((uuids[0],), ("1",), (uuids[1],))))
    config = configuration(items)

    def card(index, *, stale=False):
        return ObjectSnapshot(ObjectKey("gpu", uuids[index]), (
            Metric("index", index), Metric("name", f"Card {index}"),
            Metric("utilization_percent", 25 + 25 * index, "%"),
            Metric("memory_used_bytes", 2**30, "B"),
            Metric("memory_total_bytes", 4 * 2**30, "B"),
        ), stale=stale, sampled_at=100)

    healthy = snapshot(config)
    failed = snapshot(config, stale=("embedding",))
    # A newly discovered card appears first in the source snapshot. The app
    # must append its display slot after Card 0, independent of model choice.
    discovered = (card(1), card(0))
    stale_cards = (card(1, stale=True), card(0))
    samples = tuple(StateSnapshot(cards + service.objects, revision) for revision, (cards, service) in enumerate((
        ((card(0),), healthy),
        (discovered, healthy),
        (stale_cards, failed),
        (stale_cards, failed),
        (stale_cards, failed),
        (discovered, healthy),
    ), 1))
    frames = run_app(config, ("down", None, "down", "up", None, "q"), samples=samples)

    assert [selected_name(frame) for frame in frames] == [
        "chat", "embedding", "embedding", "reranker", "embedding", "embedding",
    ]
    expected_roles = (
        ("primary",), ("muted", "primary"), ("muted", "muted"),
        ("muted", "primary"), ("muted", "muted"), ("muted", "primary"),
    )
    for frame, roles in zip(frames, expected_roles):
        gpu_region = region(frame, "gpu")
        cells = [cell for cell in frame.cells if gpu_region.row < cell.row
                 < gpu_region.row + gpu_region.height - 1
                 and gpu_region.column < cell.column < gpu_region.column + gpu_region.width - 1]
        labels = sorted((cell for cell in cells if cell.text in {"GPU 0", "GPU 1"}),
                        key=lambda cell: (cell.row, cell.column))
        assert [(cell.text, cell.row, cell.role) for cell in labels] == [
            (f"GPU {index}", 3 + 3 * index, role) for index, role in enumerate(roles)
        ]
        for index, role in enumerate(roles):
            # Association changes affect the number, filled bar and percentage
            # together, without moving devices or changing sampled values.
            utilization = [cell for cell in cells if cell.row == 4 + 3 * index]
            assert any(cell.text == f"{25 + 25 * index}%" and cell.role == role
                       for cell in utilization)
            assert any(cell.column == gpu_region.column + 2 and cell.role == role
                       for cell in utilization)
    assert any(cell.text == "STALE" for cell in detail_cells(frames[2]))
    assert any(cell.text == "STALE" for cell in detail_cells(frames[4]))
    assert not any(cell.text == "STALE" for cell in detail_cells(frames[-1]))


def test_default_app_uses_id_for_same_type_name_and_endpoint_samples(monkeypatch):
    """Only model IDs distinguish these sources; values and history must follow."""
    from joi_observer.data.models import HistoryPoint

    items = tuple(ModelConfig(identifier, ModelType.CHAT, "Shared", "http://offline.invalid:8000")
                  for identifier in ("second", "first"))
    config = configuration(items)

    def history(values):
        return tuple(HistoryPoint(at, (Metric("decode_rate", value, "tok/s"),))
                     for at, value in zip((40, 100), values))

    # Reverse snapshot order to ensure neither type/name nor object ordering
    # can replace the configured ID as the lookup key.
    sample = StateSnapshot((
        object_snapshot("first", decode_rate=0, stale=True, history=history((22, 0))),
        object_snapshot("second", decode_rate=11, history=history((0, 11))),
    ), 3)
    # Keep application-owned scales and rendering in the same controlled clock
    # domain. Alternating sizes drive these frames without elapsed real time.
    monkeypatch.setattr(asyncio.BaseEventLoop, "time", lambda self: 100.0)
    monkeypatch.setattr("joi_observer.tui.layout.time", SimpleNamespace(monotonic=lambda: 100))
    frames = run_app(config, ("down", "up", "q"), samples=(sample,))

    assert len(frames) == 3
    for frame, expected_rate, stale, selected_offset in zip(
            frames, (11, 0, 11), (False, True, False), (2, 6, 2)):
        service = region(frame, "service")
        detail = detail_cells(frame)
        assert detail_metric(frame, "DECODE / tok/s") == str(expected_rate)
        assert any(cell.text == "STALE" for cell in detail) is stale
        names = sorted((cell for cell in frame.cells if cell.text.removeprefix("› ") == "Shared"
                        and cell.column < service.column + 26),
                       key=lambda cell: cell.row)
        assert len(names) == 2
        assert [cell.row - service.row for cell in names if cell.role == "primary"] == [selected_offset]
        plot = [cell for cell in detail
                if service.row + 13 <= cell.row <= service.row + service.height - 3]
        left = service.column + 30
        right = service.column + service.width - 3
        zeros = {cell.column for cell in plot if cell.text == "·"}
        bars = {cell.column for cell in plot if cell.text in "▁▂▃▄▅▆▇█"}
        assert zeros == {right if stale else left}
        assert bars == {left if stale else right}
    assert frames[0] == frames[-1]


def test_each_frame_reads_selection_once_for_model_details_and_gpu_highlight():
    """A per-frame boundary detects extra reads or cached choices across frames."""
    from joi_observer.data.models import ObjectSnapshot

    uuids = tuple(f"GPU-00000000-0000-0000-0000-{index:012d}" for index in range(2))
    configured = tuple(replace(model, gpu_ids=(uuid,))
                       for model, uuid in zip(models()[:2], uuids))
    config = configuration(configured)
    cards = tuple(ObjectSnapshot(ObjectKey("gpu", uuid), (
        Metric("index", index), Metric("name", f"Card {index}"),
        Metric("utilization_percent", 25, "%"),
    ), sampled_at=100) for index, uuid in enumerate(uuids))
    sample = replace(snapshot(config), objects=cards + snapshot(config).objects)
    before = deepcopy((config, sample))

    class CountedActions:
        def __init__(self):
            self.delegate = SessionViewActions(config.models)
            self.reads = 0

        def selection(self):
            self.reads += 1
            # Reading does not advance model or theme; only on_key may do so.
            return self.delegate.selection()

        def on_key(self, key):
            self.delegate.on_key(key)

    actions = CountedActions()
    expected = ((0, "Hologram"), (1, "Hologram"), (1, "Moonlight"),
                (0, "Moonlight"), (0, "Moonlight"))

    class ObservedTerminal(ScriptedTerminal):
        def render(self, frame):
            # Check before every draw, so a double read in one frame cannot be
            # hidden by reusing the old choice without a read in another frame.
            assert actions.reads == len(self.frames) + 1
            model_index, theme = expected[len(self.frames)]
            assert selected_name(frame) == configured[model_index].name
            assert detail_metric(frame, "DECODE / tok/s" if model_index == 0 else "RATE / seq/s") == (
                "100" if model_index == 0 else "3")
            highlighted = [cell.text for cell in frame.cells
                           if cell.text in {"GPU 0", "GPU 1"} and cell.role == "primary"]
            assert highlighted == [f"GPU {model_index}"]
            assert any(cell.text == f"Theme: {theme} [t]" for cell in frame.cells)
            super().render(frame)

    terminal = ObservedTerminal(("down", "t", "up", None, "q"))
    app = ObserverApp(config, ReadOnlyInput((sample,)), terminal, host=HOST,
                      wall_clock=lambda: NOW, actions=actions)
    asyncio.run(app.run())
    assert len(terminal.frames) == actions.reads == len(expected)
    assert terminal.events == ["enter", "restore"]
    assert (config, sample) == before
