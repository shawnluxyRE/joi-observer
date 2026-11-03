"""Public vLLM presentation contracts with immutable, offline state fixtures."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import math
import socket
import subprocess
import unicodedata

import pytest

from joi_observer.config import AppConfig, ModelConfig, ModelType
from joi_observer.data.models import HistoryPoint, Metric, ObjectKey, ObjectSnapshot, StateSnapshot
from joi_observer.tui.layout import HostInfo, Region, TerminalSize, ViewSelection, compose_frame
from joi_observer.tui.vllm import vllm_cells


REGION = Region("service", 18, 0, 120, 16)
NOW = 100.0
WALL_NOW = datetime(2026, 11, 2, 15, 10, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Presentation must not access external services or processes.")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


def model(identifier="chat", kind=ModelType.CHAT, *, name=None):
    return ModelConfig(identifier, kind, name or identifier, "http://offline.invalid:8000")


def config(*models):
    return AppConfig(models=models or (model(),), mount_points=())


def object_snapshot(identifier="chat", kind=ModelType.CHAT, *, stale=False,
                    sampled_at=NOW, history=(), **values):
    chat = kind == ModelType.CHAT
    defaults = dict(running=3, waiting=7, total=10, decode_rate=100,
                    prefill_rate=500, rate=3, ttft_seconds=3, queue_seconds=0.5,
                    latency_seconds=3, kv_cache_percent=25)
    defaults.update(values)
    specs = (
        ("running", "seq", True), ("waiting", "seq", True), ("total", "seq", True),
        ("decode_rate", "tok/s", chat), ("prefill_rate", "tok/s", chat),
        ("rate", "seq/s", not chat), ("ttft_seconds", "s", chat),
        ("queue_seconds", "s", True), ("latency_seconds", "s", not chat),
        ("kv_cache_percent", "%", chat),
    )
    metrics = tuple(Metric(name, defaults[name] if applicable else None, unit, applicable)
                    for name, unit, applicable in specs)
    return ObjectSnapshot(ObjectKey("vllm", identifier), metrics, stale, sampled_at, history)


def point(at, value, kind=ModelType.CHAT):
    name = "decode_rate" if kind == ModelType.CHAT else "rate"
    unit = "tok/s" if kind == ModelType.CHAT else "seq/s"
    return HistoryPoint(at, (Metric(name, value, unit),))


def cells_for(item=None, *, kind=ModelType.CHAT, view=None, region=REGION, now=NOW):
    item = item or object_snapshot(kind=kind)
    return vllm_cells(StateSnapshot((item,), 17), config(model(kind=kind)), region,
                      view or ViewSelection("chat"), now=now)


def pixels(cells):
    result = {}
    for cell in cells:
        column = cell.column
        for character in cell.text:
            if unicodedata.combining(character):
                continue
            width = 2 if unicodedata.east_asian_width(character) in "WF" else 1
            result[cell.row, column] = (character, cell.role)
            for offset in range(1, width):
                result[cell.row, column + offset] = (" ", cell.role)
            column += width
    return result


def content(cells):
    return " ".join(cell.text for cell in cells)


def right_cells(cells, region=REGION):
    return tuple(cell for cell in cells if cell.column >= region.column + region.width // 3 + 2)


def row(cells, offset, region=REGION, *, right=True):
    grid = pixels(cells)
    start = region.column + region.width // 3 + 2 if right else region.column + 1
    return "".join(grid.get((region.row + offset, column), (" ", "text"))[0]
                   for column in range(start, region.column + region.width - 1))


def token_roles(cells, offset, token, region=REGION):
    grid = pixels(cells)
    text = row(cells, offset, region)
    start = text.index(token) + region.column + region.width // 3 + 2
    return {grid[region.row + offset, column][1] for column in range(start, start + len(token))}


def plot(cells, region=REGION):
    return tuple(cell for cell in right_cells(cells, region)
                 if region.row + 10 <= cell.row <= region.row + region.height - 3)


def assert_contained(cells, region=REGION):
    assert isinstance(cells, tuple)
    for cell in cells:
        assert isinstance(cell.text, str)
        assert all(not unicodedata.category(c).startswith("C") and c not in "\u2028\u2029"
                   for c in cell.text)
        assert all(region.row < row_index < region.row + region.height - 1
                   and region.column < column < region.column + region.width - 1
                   for row_index, column in pixels((cell,)))


def test_chat_named_metrics_units_and_precomputed_total():
    cells = cells_for()
    counts = row(cells, 4)
    assert "RUNNING" in counts and "WAITING" in counts and "Total" in counts
    assert "3" in counts and "7" in counts and "10" in counts and "seq" in counts
    assert "DECODE" in row(cells, 6) and "PREFILL" in row(cells, 6)
    assert "100" in row(cells, 6) and "500" in row(cells, 6) and "tok/s" in row(cells, 6)
    assert "TTFT" in row(cells, 7) and "Avg queue" in row(cells, 7)
    assert "KV CACHE" in row(cells, 8) and "25" in row(cells, 8) and "%" in row(cells, 8)
    assert "DECODE HISTORY" in row(cells, 9) and "tok/s" in row(cells, 9)
    assert "Avg latency" not in content(right_cells(cells))
    assert_contained(cells)


@pytest.mark.parametrize("kind", [ModelType.EMBEDDING, ModelType.RERANKER])
def test_pooling_uses_sequence_rate_and_its_own_latency_slots(kind):
    cells = cells_for(kind=kind)
    text = content(right_cells(cells))
    assert "RATE" in row(cells, 6) and "seq/s" in row(cells, 6)
    assert "Avg queue" in row(cells, 7) and "Avg latency" in row(cells, 7)
    assert "RATE HISTORY" in row(cells, 9) and "seq/s" in row(cells, 9)
    assert "N/A" in row(cells, 8)
    for forbidden in ("TTFT", "DECODE", "PREFILL", "KV CACHE", "tok/s", "req/s"):
        assert forbidden not in text
    assert_contained(cells)


def test_unknown_total_is_not_recomputed_from_potentially_mixed_values():
    cells = cells_for(object_snapshot(total=None))
    counts = row(cells, 4)
    total = counts.split("Total", 1)[1]
    assert "—" in total and "10" not in total


@pytest.mark.parametrize("theme", ["moonlight", "hologram"])
def test_queued_and_positive_waiting_alone_receive_amber(theme):
    cells = cells_for(view=ViewSelection("chat", theme))
    assert token_roles(cells, 1, "QUEUED") == {"amber"}
    assert token_roles(cells, 4, "WAITING") == {"text"}
    assert token_roles(cells, 4, "7") == {"amber"}
    assert all(cell.text.strip() in ("QUEUED", "7", "7 seq", "7seq")
               for cell in cells if cell.role == "amber")
    assert "!" not in content(cells)


@pytest.mark.parametrize("theme", ["moonlight", "hologram"])
def test_zero_waiting_is_ready_and_ordinary_text(theme):
    cells = cells_for(object_snapshot(waiting=0, total=3), view=ViewSelection("chat", theme))
    assert "READY" in row(cells, 1) and "QUEUED" not in content(cells)
    assert token_roles(cells, 4, "WAITING") == {"text"}
    assert token_roles(cells, 4, "0") == {"text"}
    assert not any(cell.role == "amber" for cell in cells)


@pytest.mark.parametrize("values", [dict(waiting=None, total=None),
                                    dict(running=None, total=None),
                                    dict(waiting=0, sampled_at=None)])
def test_unknown_load_or_initial_snapshot_never_reports_ready(values):
    item = object_snapshot(**values)
    cells = cells_for(item)
    assert "READY" not in row(cells, 1) and "QUEUED" not in row(cells, 1)
    assert "—" in row(cells, 1)
    assert not any(cell.role == "amber" for cell in cells)


def test_stale_replaces_queued_without_diagnostics_or_amber_old_waiting():
    cells = cells_for(object_snapshot(stale=True, sampled_at=97))
    assert "STALE" in row(cells, 1)
    assert "QUEUED" not in content(cells) and "READY" not in row(cells, 1)
    assert "7" in row(cells, 4)
    assert not any(cell.role == "amber" for cell in cells)
    for forbidden in ("97", "last", "ago", "timeout", "error", "STALE 3"):
        assert forbidden not in content(cells)


def test_unavailable_values_remain_dash_but_observed_zero_is_zero():
    cells = cells_for(object_snapshot(decode_rate=None, prefill_rate=0,
                                     ttft_seconds=None, queue_seconds=0))
    assert "—" in row(cells, 6) and "0" in row(cells, 6)
    assert "—" in row(cells, 7) and "0" in row(cells, 7)


def test_missing_snapshot_object_is_initial_unknown_state():
    cells = vllm_cells(StateSnapshot(()), config(), REGION, ViewSelection(), now=NOW)
    assert "—" in row(cells, 1) and "—" in row(cells, 4)
    assert "READY" not in content(cells) and "STALE" not in content(cells)


def test_unknown_denominators_and_raw_metrics_are_not_invented_or_dumped():
    item = object_snapshot()
    item = replace(item, metrics=item.metrics + (Metric("internal_debug_counter", 123456789),))
    cells = cells_for(item)
    counts = row(cells, 4)
    assert "/" not in counts
    for forbidden in ("internal_debug_counter", "123456789", "TP=", "max_num", "15", "MOCK DATA"):
        assert forbidden not in content(cells)


def test_configured_route_is_secondary_without_unknown_parameters():
    cells = cells_for()
    assert "http://offline.invalid:8000" in row(cells, 2)
    assert token_roles(cells, 2, "http://offline.invalid:8000") == {"secondary"}


def test_duplicate_display_names_remain_separate_configured_id_rows():
    models = (model("a", name="shared"), model("b", ModelType.EMBEDDING, name="shared"))
    snapshot = StateSnapshot((object_snapshot("a", running=1, waiting=0, total=1),
                              object_snapshot("b", ModelType.EMBEDDING, running=5, waiting=0, total=5)))
    cells = vllm_cells(snapshot, config(*models), REGION, ViewSelection("b"), now=NOW)
    names = [cell for cell in cells if cell.column < 40 and cell.text == "shared"]
    assert len(names) == 2 and {cell.row for cell in names} == {REGION.row + 1, REGION.row + 3}
    assert names[0].role == "text" and names[1].role == "primary"
    assert "embedding" in row(cells, 1) and "5" in row(cells, 4)


@pytest.mark.parametrize("selection", [None, "unknown"])
def test_default_or_unknown_selection_uses_first_configured_model(selection):
    models = (model("first"), model("second", ModelType.EMBEDDING))
    snapshot = StateSnapshot((object_snapshot("first", waiting=0, total=3),
                              object_snapshot("second", ModelType.EMBEDDING)))
    cells = vllm_cells(snapshot, config(*models), REGION, ViewSelection(selection), now=NOW)
    assert "first" in row(cells, 1) and "DECODE" in row(cells, 6)
    assert any(cell.text == "first" and cell.role == "primary" and cell.column < 40 for cell in cells)


def test_long_model_list_scrolls_to_selected_item_without_changing_input():
    models = tuple(model(f"MODEL-{index:02}") for index in range(12))
    configuration = config(*models)
    snapshot = StateSnapshot(tuple(object_snapshot(item.id) for item in models), 99)
    before = deepcopy((snapshot, configuration))
    cells = vllm_cells(snapshot, configuration, REGION, ViewSelection("MODEL-09"), now=NOW)
    visible = [cell.text for cell in cells if cell.column < 40 and cell.text.startswith("MODEL-")]
    assert visible == [f"MODEL-{index:02}" for index in range(3, 10)]
    assert (snapshot, configuration) == before
    assert_contained(cells)


def test_unselected_models_keep_independent_status_in_the_list():
    models = (model("first"), model("second", ModelType.EMBEDDING))
    snapshot = StateSnapshot((object_snapshot("first", stale=True),
                              object_snapshot("second", ModelType.EMBEDDING)))
    cells = vllm_cells(snapshot, config(*models), REGION, ViewSelection("second"), now=NOW)
    left = tuple(cell for cell in cells if cell.column < 40)
    assert "STALE" in row(left, 1, right=False)
    assert "QUEUED" in row(left, 3, right=False)
    assert "RUNNING" in row(left, 2, right=False) and "WAITING" in row(left, 4, right=False)


def test_same_id_in_another_collector_cannot_contaminate_model_status():
    unrelated = ObjectSnapshot(ObjectKey("gpu", "chat"), stale=True, sampled_at=NOW)
    snapshot = StateSnapshot((unrelated, object_snapshot(waiting=0, total=3)))
    cells = vllm_cells(snapshot, config(), REGION, ViewSelection("chat"), now=NOW)
    assert "READY" in row(cells, 1) and "STALE" not in content(cells)


def test_empty_configuration_has_one_compact_empty_message():
    cells = vllm_cells(StateSnapshot(()), AppConfig(models=()), REGION, ViewSelection(), now=NOW)
    assert content(cells).count("No models configured") == 1
    assert "RUNNING" not in content(cells) and "HISTORY" not in content(cells)
    assert_contained(cells)


@pytest.mark.parametrize("kind", list(ModelType))
def test_history_uses_selected_primary_metric_and_actual_short_time_range(kind):
    history = (point(98, 1, kind), point(100, 3, kind))
    cells = cells_for(object_snapshot(kind=kind, history=history), kind=kind)
    assert any("█" in cell.text or any("▁" <= char <= "▇" for char in cell.text) for cell in plot(cells))
    axis = row(cells, REGION.height - 2)
    assert "-2s" in axis and "0s" in axis
    assert "-60s" not in axis and "98" not in axis and "100" not in axis


def test_history_gap_is_blank_while_observed_zero_has_baseline_marker():
    zero = (point(98, 0), point(100, 5))
    gap = (HistoryPoint(98, None), point(100, 5))
    zero_cells = cells_for(object_snapshot(history=zero))
    gap_cells = cells_for(object_snapshot(history=gap))
    assert "·" in content(plot(zero_cells))
    assert "·" not in content(plot(gap_cells))
    assert pixels(plot(zero_cells)) != pixels(plot(gap_cells))


def test_unknown_primary_value_is_a_gap_not_an_observed_zero():
    cells = cells_for(object_snapshot(history=(point(98, None), point(100, 5))))
    assert "·" not in content(plot(cells))


def test_mixed_gap_and_value_in_one_time_bin_does_not_fill_the_gap():
    # At 120 columns these almost coincident points occupy the same time bin,
    # while the two endpoints establish a genuine 60-second axis.
    endpoints = (point(40, 10), point(100, 1000))
    gap_at = 70.123
    gap_only = (endpoints[0], HistoryPoint(gap_at, None), endpoints[1])
    mixed = (endpoints[0], point(gap_at - 1e-9, 500), HistoryPoint(gap_at, None),
             point(gap_at + 1e-9, 400), endpoints[1])
    gap_cells = cells_for(object_snapshot(history=gap_only))
    mixed_cells = cells_for(object_snapshot(history=mixed))
    # Endpoints fix the scale, so the mixed bin must remain visually identical.
    assert pixels(plot(mixed_cells)) == pixels(plot(gap_cells))


def test_old_and_future_history_points_are_not_drawn():
    valid = (point(98, 2), point(100, 4))
    extra = (point(39, 999999), *valid, point(101, 999999))
    assert pixels(plot(cells_for(object_snapshot(history=valid)))) == pixels(
        plot(cells_for(object_snapshot(history=extra))))


def test_empty_history_is_unavailable_without_a_fabricated_zero_line():
    cells = cells_for(object_snapshot(history=()))
    assert "—" in content(plot(cells))
    assert "·" not in content(plot(cells))
    assert not any("█" in cell.text for cell in plot(cells))


def test_switching_models_reuses_their_retained_history_without_mutating_snapshot():
    models = (model("a"), model("b", ModelType.EMBEDDING))
    sample = StateSnapshot((object_snapshot("a", history=(point(98, 2), point(100, 4))),
                            object_snapshot("b", ModelType.EMBEDDING,
                                            history=(point(96, 3, ModelType.EMBEDDING),
                                                     point(100, 5, ModelType.EMBEDDING)))), 123)
    before = deepcopy(sample)
    a = vllm_cells(sample, config(*models), REGION, ViewSelection("a"), now=NOW)
    b = vllm_cells(sample, config(*models), REGION, ViewSelection("b"), now=NOW)
    again = vllm_cells(sample, config(*models), REGION, ViewSelection("a"), now=NOW)
    assert "-2s" in row(a, 14) and "-4s" in row(b, 14)
    assert a == again and sample == before


@pytest.mark.parametrize("kind,stale", [(kind, stale) for kind in ModelType for stale in (False, True)])
def test_types_failure_and_recovery_use_same_fixed_slots(kind, stale):
    cells = cells_for(object_snapshot(kind=kind, stale=stale), kind=kind)
    assert row(cells, 1).strip() and row(cells, 2).strip()
    assert "RUNNING" in row(cells, 4)
    assert row(cells, 6).strip() and row(cells, 7).strip() and row(cells, 8).strip()
    assert "HISTORY" in row(cells, 9)
    assert_contained(cells)


@pytest.mark.parametrize("region", [REGION, Region("service", 22, 5, 160, 20)])
def test_unicode_long_names_and_control_characters_stay_inside_service_content(region):
    configured_model = model(name="长模型e\u0301" * 40 + "\x1b[31m\nleak")
    configuration = config(configured_model)
    cells = vllm_cells(StateSnapshot((object_snapshot(),)), configuration, region,
                      ViewSelection("chat"), now=NOW)
    assert_contained(cells, region)
    assert "RUNNING" in row(cells, 4, region)


@pytest.mark.parametrize("region", [REGION, Region("service", 22, 5, 160, 20)])
def test_long_names_do_not_overwrite_internal_columns_or_reserved_status(region):
    configuration = config(model(name="Very-long-model-" * 30))
    cells = vllm_cells(StateSnapshot((object_snapshot(),)), configuration, region,
                      ViewSelection("chat"), now=NOW)
    divider = region.column + region.width // 3
    left = tuple(cell for cell in cells if cell.column < divider)
    assert all(column < divider for cell in left for _, column in pixels((cell,)))
    assert "QUEUED" in row(cells, 1, region)
    assert token_roles(cells, 1, "QUEUED", region) == {"amber"}
    right_status = set()
    for cell in right_cells(cells, region):
        if cell.row == region.row + 1 and cell.text == "QUEUED":
            right_status.update(pixels((cell,)))
    assert right_status
    assert all(not right_status.intersection(pixels((cell,)))
               for cell in cells
               if cell.row == region.row + 1 and cell.role != "amber")
    assert any(cell.text == "QUEUED" and cell.row == region.row + 1 for cell in left)
    assert "RUNNING" in row(cells, 4, region) and "WAITING" in row(cells, 4, region)
    assert_contained(cells, region)


@pytest.mark.parametrize("now", [-1, math.nan, math.inf, True, "100"])
def test_invalid_monotonic_now_is_rejected(now):
    with pytest.raises(ValueError):
        cells_for(now=now)


@pytest.mark.parametrize("region", [Region("docker", 0, 0, 120, 16),
                                      Region("service", -1, 0, 120, 16),
                                      Region("service", 0, True, 120, 16),
                                      Region("service", 0, 0, 119, 16),
                                      Region("service", 0, 0, 120, 15)])
def test_invalid_service_region_is_rejected(region):
    with pytest.raises(ValueError):
        cells_for(region=region)


def test_compose_frame_integrates_model_type_metrics_into_existing_half_page():
    configured = config(model(kind=ModelType.EMBEDDING))
    sample = StateSnapshot((object_snapshot(kind=ModelType.EMBEDDING),))
    frame = compose_frame(sample, configured, TerminalSize(120, 36),
                          HostInfo("offline", "Ubuntu"), WALL_NOW,
                          view=ViewSelection("chat"), monotonic_now=NOW)
    service = next(region for region in frame.regions if region.name == "service")
    assert service == REGION
    text = content(tuple(cell for cell in frame.cells
                         if service.row < cell.row < service.row + service.height - 1))
    assert "RATE HISTORY" in text and "Avg latency" in text and "seq/s" in text
    assert "decode_rate" not in text and "kv_cache_percent" not in text
    assert next(region for region in frame.regions if region.name == "service_switch").row == 34
    assert next(region for region in frame.regions if region.name == "footer").row == 35


def test_history_uses_time_spacing_and_maximum_of_a_valid_shared_bin():
    endpoints = (point(40, 5), point(100, 10))
    single = (endpoints[0], point(55, 8), endpoints[1])
    same_bin = (endpoints[0], point(55 - 1e-9, 3), point(55, 8), endpoints[1])
    expected = plot(cells_for(object_snapshot(history=single)))
    actual = plot(cells_for(object_snapshot(history=same_bin)))
    assert pixels(actual) == pixels(expected)
    columns = sorted({cell.column for cell in expected})
    assert len(columns) == 3
    assert columns[1] - columns[0] < (columns[2] - columns[0]) / 3


def test_single_history_point_at_now_has_only_zero_axis_label():
    cells = cells_for(object_snapshot(history=(point(NOW, 0),)))
    assert row(cells, 14).strip() == "0s"
    assert "·" in content(plot(cells))


def test_compose_frame_uses_monotonic_default_and_explicit_clock_without_wall_conversion(monkeypatch):
    snapshot = StateSnapshot((object_snapshot(history=(point(98, 2), point(100, 4))),))
    monkeypatch.setattr("joi_observer.tui.layout.time.monotonic", lambda: NOW)
    args = (snapshot, config(), TerminalSize(120, 36), HostInfo("local", "Ubuntu"), WALL_NOW)
    default = compose_frame(*args)
    injected = compose_frame(*args, monotonic_now=NOW)
    assert default == injected
    assert "-2s" in content(default.cells)
    assert "-60s" not in content(default.cells)


@pytest.mark.parametrize("now", [-1, math.nan, math.inf, True, "100"])
def test_compose_frame_rejects_invalid_injected_monotonic_clock_even_when_small(now):
    with pytest.raises(ValueError):
        compose_frame(StateSnapshot(()), config(), TerminalSize(20, 10),
                      HostInfo("local", "Ubuntu"), WALL_NOW, monotonic_now=now)


@pytest.mark.parametrize("kind", list(ModelType))
def test_unknown_history_bin_excludes_its_other_values_from_plot_scale(kind):
    # A failed observation and a much larger valid observation share one time
    # bin. That whole bin is unavailable, including for vertical scaling.
    history = (point(40, 5, kind), HistoryPoint(70, None), point(100, 10, kind))
    spike = (history[0], point(70 - 1e-9, 1e300, kind), history[1], history[2])
    baseline_cells = cells_for(object_snapshot(kind=kind, history=history), kind=kind)
    spike_cells = cells_for(object_snapshot(kind=kind, history=spike), kind=kind)
    assert pixels(plot(spike_cells)) == pixels(plot(baseline_cells))
    assert "█" in content(plot(spike_cells))


@pytest.mark.parametrize("kind", list(ModelType))
def test_history_retains_both_closed_window_boundaries_and_excludes_adjacent_points(kind):
    boundary = (point(NOW - 60, 0, kind), point(NOW, 5, kind))
    outside = (point(NOW - 60 - 1e-6, 1e300, kind), *boundary,
               point(NOW + 1e-6, 1e300, kind))
    cells = cells_for(object_snapshot(kind=kind, history=outside), kind=kind)
    expected = cells_for(object_snapshot(kind=kind, history=boundary), kind=kind)
    assert pixels(plot(cells)) == pixels(plot(expected))
    assert "·" in content(plot(cells)) and "█" in content(plot(cells))
    assert "-60s" in row(cells, REGION.height - 2)


@pytest.mark.parametrize("height", [37, 49])
@pytest.mark.parametrize("kind", list(ModelType))
def test_selected_last_model_keeps_odd_page_half_and_all_detail_slots(height, kind):
    models = tuple(model(f"model-{index:02}", kind) for index in range(30))
    snapshot = StateSnapshot(tuple(object_snapshot(item.id, kind,
                                                   history=(point(98, 0, kind),
                                                            point(100, 5, kind)))
                                   for item in models))
    frame = compose_frame(snapshot, config(*models), TerminalSize(120, height),
                          HostInfo("offline", "Ubuntu"), WALL_NOW,
                          view=ViewSelection(models[-1].id), monotonic_now=NOW)
    service = next(region for region in frame.regions if region.name == "service")
    assert not frame.too_small and frame.minimum_size == TerminalSize(120, 36)
    assert service.row == height - height // 2
    assert service.height + 2 == height // 2
    cells = tuple(cell for cell in frame.cells
                  if service.row < cell.row < service.row + service.height - 1)
    assert models[-1].name in row(cells, 1, service)
    assert "QUEUED" in row(cells, 1, service)
    assert "RUNNING" in row(cells, 4, service) and "Total" in row(cells, 4, service)
    assert "HISTORY" in row(cells, 9, service)
    assert "-2s" in row(cells, service.height - 2, service)
    assert "0s" in row(cells, service.height - 2, service)
