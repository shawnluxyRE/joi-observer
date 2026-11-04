"""Session selection contracts, exercised through public actions and real views.

Snapshots below are immutable presentation inputs, not substituted navigation or
rendering results. Unimplemented action methods remain ordinary failing tests.
"""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from pathlib import Path
import subprocess

import pytest

from joi_observer.config import AppConfig, ModelConfig, ModelType
from joi_observer.data.models import HistoryPoint, Metric, ObjectKey, ObjectSnapshot, StateSnapshot
from joi_observer.tui.layout import HostInfo, TerminalSize, ViewSelection, compose_frame
from joi_observer.tui.navigation import SessionViewActions


NOW = datetime(2026, 11, 3, 16, 0, tzinfo=timezone.utc)
HOST = HostInfo("offline", "Ubuntu")
UUIDS = tuple(f"GPU-00000000-0000-0000-0000-{index:012d}" for index in range(2))


def models():
    """Deliberately use configuration order that differs from IDs and types."""
    return (
        ModelConfig("middle", ModelType.EMBEDDING, "Shared", "http://offline.invalid:8001"),
        ModelConfig("first", ModelType.CHAT, "Shared", "http://offline.invalid:8000"),
        ModelConfig("last", ModelType.RERANKER, "Shared", "http://offline.invalid:8002"),
    )


@pytest.mark.parametrize("count", (0, 1, 3))
def test_default_selection_uses_first_configured_id_and_session_theme(count):
    configured = models()[:count]
    actions = SessionViewActions(configured)
    expected = ViewSelection(configured[0].id if configured else None, "moonlight")
    assert actions.selection() == expected
    assert actions.selection() == expected


def test_arrows_traverse_configuration_order_and_stop_at_both_ends():
    actions = SessionViewActions(models())
    expected = (
        ("up", "middle"), ("up", "middle"),
        ("down", "first"), ("down", "last"), ("down", "last"),
        ("up", "first"), ("up", "middle"), ("up", "middle"),
    )
    for key, identifier in expected:
        actions.on_key(key)
        assert actions.selection() == ViewSelection(identifier, "moonlight")


@pytest.mark.parametrize("second_url", ("http://offline.invalid:8001", "http://offline.invalid:8000"),
                         ids=("same-endpoint", "different-endpoint"))
def test_distinct_ids_with_same_type_and_name_remain_distinct_choices(second_url):
    configured = (
        ModelConfig("second", ModelType.CHAT, "Shared", "http://offline.invalid:8001"),
        ModelConfig("first", ModelType.CHAT, "Shared", second_url),
    )
    actions = SessionViewActions(configured)
    assert actions.selection().model_id == "second"
    actions.on_key("down")
    assert actions.selection().model_id == "first"
    actions.on_key("up")
    assert actions.selection().model_id == "second"


@pytest.mark.parametrize("count", (0, 1))
def test_empty_and_single_model_lists_accept_arrows_and_theme(count):
    configured = models()[:count]
    actions = SessionViewActions(configured)
    expected_id = configured[0].id if configured else None
    for key in ("up", "down", "left", "right") * 3:
        actions.on_key(key)
        assert actions.selection() == ViewSelection(expected_id, "moonlight")
    actions.on_key("t")
    assert actions.selection() == ViewSelection(expected_id, "hologram")
    actions.on_key("t")
    assert actions.selection() == ViewSelection(expected_id, "moonlight")


@pytest.mark.parametrize("key", (
    "left", "right", "enter", "p", "tab", "q", "interrupt", "T", "Q", "unknown", "", "\x1b[B",
))
def test_non_action_keys_do_not_change_selection_or_theme(key):
    actions = SessionViewActions(models())
    actions.on_key("down")
    actions.on_key("t")
    before = actions.selection()
    actions.on_key(key)
    assert actions.selection() == before == ViewSelection("first", "hologram")


def test_returned_selection_is_immutable_and_old_values_survive_later_actions():
    actions = SessionViewActions(models())
    original = actions.selection()
    with pytest.raises(FrozenInstanceError):
        original.model_id = "last"
    actions.on_key("down")
    moved = actions.selection()
    actions.on_key("t")
    assert original == ViewSelection("middle", "moonlight")
    assert moved == ViewSelection("first", "moonlight")
    assert actions.selection() == ViewSelection("first", "hologram")


def test_sessions_do_not_share_selection_theme_or_modify_configuration():
    configured = models()
    before = deepcopy(configured)
    first, second = SessionViewActions(configured), SessionViewActions(configured)
    first.on_key("down")
    first.on_key("t")
    assert first.selection() == ViewSelection("first", "hologram")
    assert second.selection() == ViewSelection("middle", "moonlight")
    assert SessionViewActions(configured).selection() == ViewSelection("middle", "moonlight")
    assert configured == before


def test_construct_read_and_keys_do_not_access_files_or_launch_processes(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("View actions must not access files or external processes")

    with monkeypatch.context() as patch:
        patch.setattr("builtins.open", forbidden)
        patch.setattr(Path, "open", forbidden)
        patch.setattr(subprocess, "Popen", forbidden)
        actions = SessionViewActions(models())
        for key in ("down", "t", "left", "right", "enter", "p", "up"):
            actions.on_key(key)
            actions.selection()
        assert actions.selection() == ViewSelection("middle", "hologram")


def sample_for_navigation():
    configured = (
        ModelConfig("chat", ModelType.CHAT, "Chat model", "http://offline.invalid:8000", (UUIDS[0],)),
        ModelConfig("embedding", ModelType.EMBEDDING, "Embed model", "http://offline.invalid:8001", ("1",)),
        ModelConfig("reranker", ModelType.RERANKER, "Rerank model", "http://offline.invalid:8002"),
    )
    cards = tuple(ObjectSnapshot(ObjectKey("gpu", uuid), (
        Metric("index", index), Metric("name", f"Card {index}"),
        Metric("utilization_percent", 25, "%"), Metric("memory_used_bytes", 2**30, "B"),
        Metric("memory_total_bytes", 4 * 2**30, "B"),
    ), sampled_at=100) for index, uuid in enumerate(UUIDS))
    observations = []
    # Distinct timelines prove selection chooses history as well as the label.
    for model, rates in zip(configured, ((0, 10), (5, 0), (None, 0))):
        chat = model.type == ModelType.CHAT
        primary, unit = ("decode_rate", "tok/s") if chat else ("rate", "seq/s")
        metrics = (
            Metric("running", 1, "seq"), Metric("waiting", 0, "seq"), Metric("total", 1, "seq"),
            Metric(primary, rates[1], unit), Metric("queue_seconds", 0.5, "s"),
        ) + ((Metric("prefill_rate", 20, "tok/s"), Metric("ttft_seconds", 0.25, "s"),
              Metric("kv_cache_percent", 25, "%")) if chat else
             (Metric("latency_seconds", 0.75, "s"),))
        history = tuple(HistoryPoint(at, None if value is None else (Metric(primary, value, unit),))
                        for at, value in zip((40, 100), rates))
        observations.append(ObjectSnapshot(ObjectKey("vllm", model.id), metrics,
                                           sampled_at=100, history=history))
    return AppConfig(models=configured, mount_points=()), StateSnapshot(cards + tuple(observations), 29)


def render(snapshot, config, actions, size=TerminalSize(120, 40), *, gpu_slots=UUIDS):
    return compose_frame(snapshot, config, size, HOST, NOW, gpu_slots=gpu_slots,
                         view=actions.selection(), monotonic_now=100)


def test_navigation_updates_type_units_history_and_gpu_roles_together():
    config, snapshot = sample_for_navigation()
    before = deepcopy((config, snapshot))
    actions = SessionViewActions(config.models)
    frames = []
    for index, model in enumerate(config.models):
        if index:
            actions.on_key("down")
        frame = render(snapshot, config, actions)
        frames.append(frame)
        service = next(region for region in frame.regions if region.name == "service")
        right = [cell for cell in frame.cells if service.row < cell.row < service.row + service.height - 1
                 and cell.column >= service.column + service.width // 3 + 2]
        detail = " ".join(cell.text for cell in right)
        assert model.name in detail and model.base_url in detail
        if model.type == ModelType.CHAT:
            assert all(label in detail for label in ("DECODE: 10tok/s", "TTFT: 0.25s", "DECODE HISTORY / tok/s"))
            assert "Avg latency" not in detail and "RATE HISTORY" not in detail
        else:
            assert all(label in detail for label in ("RATE: 0seq/s", "Avg latency: 0.75s", "RATE HISTORY / seq/s"))
            assert "TTFT" not in detail and "DECODE" not in detail and "KV CACHE" not in detail
        labels = [(cell.text, cell.role) for cell in frame.cells if cell.text in {"GPU 0", "GPU 1"}]
        expected_roles = (("primary", "muted"), ("muted", "primary"), ("muted", "muted"))[index]
        assert labels == list(zip(("GPU 0", "GPU 1"), expected_roles))
        history = [cell for cell in right if service.row + 10 <= cell.row <= service.row + service.height - 3]
        zeros = [cell.column for cell in history if cell.text == "·"]
        assert zeros == ([42] if index == 0 else [117])
        bars = [cell.column for cell in history if cell.text in "▁▂▃▄▅▆▇█"]
        assert set(bars) == ({117} if index == 0 else {42} if index == 1 else set())
    assert all(frame.regions == frames[0].regions for frame in frames)
    assert all([(cell.row, cell.column, cell.text) for cell in frame.cells if cell.text in {"GPU 0", "GPU 1"}]
               == [(3, 2, "GPU 0"), (6, 2, "GPU 1")] for frame in frames)
    assert (config, snapshot) == before
    actions.on_key("up")
    actions.on_key("up")
    assert render(snapshot, config, actions) == frames[0]


def test_refresh_missing_data_failure_and_recovery_do_not_move_selection():
    config, healthy = sample_for_navigation()
    actions = SessionViewActions(config.models)
    actions.on_key("down")
    selected = config.models[1]
    missing = replace(healthy, objects=tuple(obj for obj in healthy.objects
                                            if obj.key != ObjectKey("vllm", selected.id)), revision=30)
    failed = replace(healthy, objects=tuple(replace(obj, stale=True) if obj.key == ObjectKey("vllm", selected.id)
                                           else obj for obj in healthy.objects), revision=31)
    baseline_regions = None
    for snapshot in (healthy, missing, failed, failed, healthy):
        frame = render(snapshot, config, actions)
        service = next(region for region in frame.regions if region.name == "service")
        detail = [cell for cell in frame.cells if service.row < cell.row < service.row + service.height - 1
                  and cell.column >= 42]
        assert selected.base_url in {cell.text for cell in detail}
        assert ("STALE" in {cell.text for cell in detail}) is (snapshot is failed)
        assert actions.selection() == ViewSelection("embedding", "moonlight")
        baseline_regions = baseline_regions or frame.regions
        assert frame.regions == baseline_regions
    actions.on_key("down")
    assert actions.selection().model_id == "reranker"


def test_long_list_selection_stays_visible_through_navigation_and_resize():
    configured = tuple(ModelConfig(f"m{index:02d}", ModelType.CHAT, f"Model {index:02d}",
                                  f"http://offline.invalid:{8100 + index}") for index in range(12))
    config = AppConfig(models=configured, mount_points=())
    sample = StateSnapshot(())
    actions = SessionViewActions(configured)

    def assert_visible(size):
        frame = render(sample, config, actions, size, gpu_slots=())
        assert not frame.too_small
        service = next(region for region in frame.regions if region.name == "service")
        selected = next(model for model in configured if model.id == actions.selection().model_id)
        left_names = [cell for cell in frame.cells if service.row < cell.row < service.row + service.height - 1
                      and cell.column < service.width // 3 and cell.text == selected.name]
        assert len(left_names) == 1 and left_names[0].role == "primary"
        assert frame.minimum_size == TerminalSize(120, 36)
        assert service.row == size.rows - size.rows // 2

    assert_visible(TerminalSize(120, 36))
    for _ in range(11):
        actions.on_key("down")
        assert_visible(TerminalSize(120, 36))
    for size in (TerminalSize(120, 60), TerminalSize(120, 37), TerminalSize(120, 40)):
        assert_visible(size)
        assert actions.selection().model_id == "m11"
    assert render(sample, config, actions, TerminalSize(80, 24), gpu_slots=()).too_small
    assert actions.selection().model_id == "m11"
    assert_visible(TerminalSize(120, 36))
    for _ in range(11):
        actions.on_key("up")
        assert_visible(TerminalSize(120, 36))
    assert actions.selection().model_id == "m00"


def test_empty_model_navigation_retains_english_empty_state_and_disabled_service():
    config = AppConfig(models=(), mount_points=())
    actions = SessionViewActions(config.models)
    for key in ("down", "up", "left", "right", "enter", "p", "tab"):
        actions.on_key(key)
        frame = render(StateSnapshot(()), config, actions, gpu_slots=())
        content = " ".join(cell.text for cell in frame.cells)
        assert "No models configured" in content
        assert "WebUI (disabled)" in content
        assert actions.selection().model_id is None
