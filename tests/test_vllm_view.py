"""Public vLLM presentation contracts with immutable, offline state fixtures."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import math
import socket
import subprocess
import sys
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


def cells_for(item=None, *, kind=ModelType.CHAT, view=None, region=REGION, now=NOW,
              history_scales=None):
    item = item or object_snapshot(kind=kind)
    return vllm_cells(StateSnapshot((item,), 17), config(model(kind=kind)), region,
                      view or ViewSelection("chat"), now=now, history_scales=history_scales)


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
    return tuple(cell for cell in cells if cell.column >= region.column + 30)


def row(cells, offset, region=REGION, *, right=True):
    grid = pixels(cells)
    start = region.column + 30 if right else region.column + 1
    return "".join(grid.get((region.row + offset, column), (" ", "text"))[0]
                   for column in range(start, region.column + region.width - 1))


def slot_text(cells, row_index, start, end):
    grid = pixels(cells)
    return "".join(grid.get((row_index, column), (" ", "text"))[0] for column in range(start, end))


def assert_span_role(cells, row_index, start, text, role):
    grid = pixels(cells)
    assert slot_text(cells, row_index, start, start + len(text)) == text
    assert {grid[row_index, start + index][1] for index, char in enumerate(text) if not char.isspace()} == {role}


def token_roles(cells, offset, token, region=REGION):
    grid = pixels(cells)
    text = row(cells, offset, region)
    start = text.index(token) + region.column + 30
    return {grid[region.row + offset, column][1] for column in range(start, start + len(token))}


def plot(cells, region=REGION):
    return tuple(cell for cell in right_cells(cells, region)
                 if region.row + 13 <= cell.row <= region.row + region.height - 3)


def bar_eighths(cells, column):
    """Measure the visible vertical bar, including its fractional top cell."""
    return sum("▁▂▃▄▅▆▇█".index(character) + 1
               for (_, x), (character, _) in pixels(plot(cells)).items()
               if x == column and character in "▁▂▃▄▅▆▇█")


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
    counts = row(cells, 6)
    assert "RUNNING" in counts and "WAITING" in counts and "Total" not in counts
    assert "3" in counts and "7" in counts and "/" not in counts
    assert "Total 10 seq" in row(cells, 7) and "Avg queue 0.5s" in row(cells, 7)
    assert "DECODE / tok/s" in row(cells, 9) and "PREFILL / tok/s" in row(cells, 9)
    assert "TTFT / s" in row(cells, 9) and "KV CACHE / %" in row(cells, 9)
    assert row(cells, 10).split() == ["100", "500", "3", "25"]
    assert "DECODE HISTORY" in row(cells, 12) and "tok/s" in row(cells, 12)
    assert "Avg latency" not in content(right_cells(cells))
    assert_contained(cells)


@pytest.mark.parametrize("kind", [ModelType.EMBEDDING, ModelType.RERANKER])
def test_pooling_uses_sequence_rate_and_its_own_latency_slots(kind):
    cells = cells_for(kind=kind)
    text = content(right_cells(cells))
    assert "RATE / seq/s" in row(cells, 9)
    assert "Avg queue / s" in row(cells, 9) and "Avg latency / s" in row(cells, 9)
    assert "KV CACHE / %" in row(cells, 9)
    assert "Total 10 seq" in row(cells, 7) and "Unit: seq" in row(cells, 7)
    assert "RATE HISTORY" in row(cells, 12) and "seq/s" in row(cells, 12)
    assert row(cells, 10).split() == ["3", "0.5", "3", "N/A"]
    for forbidden in ("TTFT", "DECODE", "PREFILL", "tok/s", "req/s"):
        assert forbidden not in text
    assert_contained(cells)


def test_unknown_total_is_not_recomputed_from_potentially_mixed_values():
    cells = cells_for(object_snapshot(total=None))
    counts = row(cells, 7)
    total = counts.split("Total", 1)[1]
    assert "—" in total and "10" not in total


@pytest.mark.parametrize("theme", ["moonlight", "hologram"])
def test_queued_and_positive_waiting_alone_receive_amber(theme):
    cells = cells_for(view=ViewSelection("chat", theme))
    assert token_roles(cells, 2, "QUEUED") == {"amber"}
    assert token_roles(cells, 6, "WAITING") == {"text"}
    assert token_roles(cells, 6, "7") == {"amber"}
    assert all(cell.text.strip() in ("QUEUED", "7", "7 seq", "7seq")
               for cell in cells if cell.role == "amber")
    assert "!" not in content(cells)


@pytest.mark.parametrize("theme", ["moonlight", "hologram"])
def test_zero_waiting_is_ready_and_ordinary_text(theme):
    cells = cells_for(object_snapshot(waiting=0, total=3), view=ViewSelection("chat", theme))
    assert "READY" in row(cells, 2) and "QUEUED" not in content(cells)
    assert token_roles(cells, 6, "WAITING") == {"text"}
    assert token_roles(cells, 6, "0") == {"text"}
    assert not any(cell.role == "amber" for cell in cells)


@pytest.mark.parametrize("values", [dict(waiting=None, total=None),
                                    dict(running=None, total=None),
                                    dict(waiting=0, sampled_at=None)])
def test_unknown_load_or_initial_snapshot_never_reports_ready(values):
    item = object_snapshot(**values)
    cells = cells_for(item)
    assert "READY" not in row(cells, 2) and "QUEUED" not in row(cells, 2)
    assert "—" in row(cells, 2)
    assert not any(cell.role == "amber" for cell in cells)


def test_stale_replaces_queued_without_diagnostics_or_amber_old_waiting():
    cells = cells_for(object_snapshot(stale=True, sampled_at=97))
    assert "STALE" in row(cells, 2)
    assert "QUEUED" not in content(cells) and "READY" not in row(cells, 2)
    assert "7" in row(cells, 6)
    assert not any(cell.role == "amber" for cell in cells)
    for forbidden in ("97", "last", "ago", "timeout", "error", "STALE 3"):
        assert forbidden not in content(cells)


def test_unavailable_values_remain_dash_but_observed_zero_is_zero():
    cells = cells_for(object_snapshot(decode_rate=None, prefill_rate=0,
                                     ttft_seconds=None, queue_seconds=0))
    assert row(cells, 10).split() == ["—", "0", "—", "25"]
    assert "Avg queue 0s" in row(cells, 7)


def test_missing_snapshot_object_is_initial_unknown_state():
    cells = vllm_cells(StateSnapshot(()), config(), REGION, ViewSelection(), now=NOW)
    assert "—" in row(cells, 2) and "—" in row(cells, 6)
    assert "READY" not in content(cells) and "STALE" not in content(cells)


def test_unknown_denominators_and_raw_metrics_are_not_invented_or_dumped():
    item = object_snapshot()
    item = replace(item, metrics=item.metrics + (Metric("internal_debug_counter", 123456789),))
    cells = cells_for(item)
    counts = row(cells, 6)
    assert "/" not in counts
    for forbidden in ("internal_debug_counter", "123456789", "TP=", "max_num", "15", "MOCK DATA"):
        assert forbidden not in content(cells)


def test_configured_route_is_secondary_without_unknown_parameters():
    cells = cells_for()
    assert "↳ http://offline.invalid:8000" in row(cells, 3)
    assert token_roles(cells, 3, "http://offline.invalid:8000") == {"secondary"}


def test_duplicate_display_names_remain_separate_configured_id_rows():
    models = (model("a", name="shared"), model("b", ModelType.EMBEDDING, name="shared"))
    snapshot = StateSnapshot((object_snapshot("a", running=1, waiting=0, total=1),
                              object_snapshot("b", ModelType.EMBEDDING, running=5, waiting=0, total=5)))
    cells = vllm_cells(snapshot, config(*models), REGION, ViewSelection("b"), now=NOW)
    names = [cell for cell in cells if cell.column < 27 and cell.text.removeprefix("› ") == "shared"]
    assert len(names) == 2 and {cell.row for cell in names} == {REGION.row + 2, REGION.row + 6}
    assert names[0].role == "text" and names[1].role == "primary"
    assert "[embedding]" not in row(cells, 2) and "5" in row(cells, 6)
    assert "EMBEDDING / :8000" in row(tuple(cell for cell in cells if cell.column < 27), 7, right=False)


def test_display_name_is_shared_by_both_titles_while_metrics_match_only_configured_id():
    configured_model = replace(model("stable-id", name="Flash-Next"),
                               served_model_name="upstream-model")
    configuration = config(configured_model)
    snapshot = StateSnapshot((
        object_snapshot("stable-id", running=13, waiting=17, total=30),
        object_snapshot("Flash-Next", running=91, waiting=0, total=91),
        object_snapshot("upstream-model", running=92, waiting=0, total=92),
    ))
    before = deepcopy((configuration, snapshot))
    cells = vllm_cells(snapshot, configuration, REGION, ViewSelection("stable-id"), now=NOW)
    titles = [cell for cell in cells if cell.text == "Flash-Next"]
    assert {(cell.row, cell.column, cell.role) for cell in titles} == {
        (REGION.row + 2, REGION.column + 4, "primary"),
        (REGION.row + 2, REGION.column + 30, "primary"),
    }
    assert slot_text(cells, REGION.row + 6, 38, 73).strip() == "13"
    assert slot_text(cells, REGION.row + 6, 84, 118).strip() == "17"
    assert "Total 30 seq" in row(cells, 7)
    assert "QUEUED" in row(cells, 2)
    assert "stable-id" not in content(cells) and "upstream-model" not in content(cells)
    assert (configuration, snapshot) == before


@pytest.mark.parametrize("selection", [None, "unknown"])
def test_default_or_unknown_selection_uses_first_configured_model(selection):
    models = (model("first"), model("second", ModelType.EMBEDDING))
    snapshot = StateSnapshot((object_snapshot("first", waiting=0, total=3),
                              object_snapshot("second", ModelType.EMBEDDING)))
    cells = vllm_cells(snapshot, config(*models), REGION, ViewSelection(selection), now=NOW)
    assert "first" in row(cells, 2) and "DECODE" in row(cells, 9)
    assert any(cell.text.removeprefix("› ") == "first" and cell.role == "primary" and cell.column < 27 for cell in cells)


def test_long_model_list_scrolls_to_selected_item_without_changing_input():
    models = tuple(model(f"MODEL-{index:02}") for index in range(12))
    configuration = config(*models)
    snapshot = StateSnapshot(tuple(object_snapshot(item.id) for item in models), 99)
    before = deepcopy((snapshot, configuration))
    cells = vllm_cells(snapshot, configuration, REGION, ViewSelection("MODEL-09"), now=NOW)
    visible = [cell.text.removeprefix("› ") for cell in cells
               if cell.column < 27 and cell.text.removeprefix("› ").startswith("MODEL-")]
    assert visible == [f"MODEL-{index:02}" for index in range(7, 10)]
    assert (snapshot, configuration) == before
    assert_contained(cells)


def test_unselected_models_keep_independent_status_counts_and_waiting_color_in_the_list():
    models = (model("first"), model("second", ModelType.EMBEDDING))
    snapshot = StateSnapshot((object_snapshot("first", stale=True, running=1, waiting=2),
                              object_snapshot("second", ModelType.EMBEDDING, running=5, waiting=6)))
    cells = vllm_cells(snapshot, config(*models), REGION, ViewSelection("second"), now=NOW)
    left = tuple(cell for cell in cells if cell.column < 27)
    assert "STALE" in row(left, 2, right=False)
    assert "QUEUED" in row(left, 6, right=False)
    assert "1" in row(left, 4, right=False) and "2" in row(left, 4, right=False)
    assert "5" in row(left, 8, right=False) and "6" in row(left, 8, right=False)
    assert not any(cell.role == "amber" for cell in left if cell.row == REGION.row + 4)
    assert any(cell.text.strip() == "6" and cell.role == "amber"
               for cell in left if cell.row == REGION.row + 8)


def test_same_id_in_another_collector_cannot_contaminate_model_status():
    unrelated = ObjectSnapshot(ObjectKey("gpu", "chat"), stale=True, sampled_at=NOW)
    snapshot = StateSnapshot((unrelated, object_snapshot(waiting=0, total=3)))
    cells = vllm_cells(snapshot, config(), REGION, ViewSelection("chat"), now=NOW)
    assert "READY" in row(cells, 2) and "STALE" not in content(cells)


def test_empty_configuration_has_one_compact_empty_message():
    cells = vllm_cells(StateSnapshot(()), AppConfig(models=()), REGION, ViewSelection(), now=NOW)
    assert content(cells).count("No models configured") == 1
    assert "RUNNING" not in content(cells) and "HISTORY" not in content(cells)
    assert_contained(cells)


@pytest.mark.parametrize("kind", list(ModelType))
def test_history_uses_selected_primary_metric_on_fixed_sixty_second_axis(kind):
    history = (point(98, 1, kind), point(100, 3, kind))
    cells = cells_for(object_snapshot(kind=kind, history=history), kind=kind)
    assert any("█" in cell.text or any("▁" <= char <= "▇" for char in cell.text) for cell in plot(cells))
    axis = row(cells, REGION.height - 2)
    assert "-60s" in axis and "0s" in axis
    assert "-2s" not in axis and "98" not in axis and "100" not in axis
    # W=88 gives 60/87s buckets anchored at monotonic zero, not the first point.
    assert {cell.column for cell in plot(cells)} == {114, 117}
    assert bar_eighths(cells, 117) == 5  # 3/5 of the one-row minimum plot, rounded up to eighths.
    assert f"Scale ≤ 5 {'tok/s' if kind == ModelType.CHAT else 'seq/s'}" in row(cells, 12)


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
    assert row(cells, 14).split() == ["-60s", "0s"]


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
    assert row(a, 14).split() == row(b, 14).split() == ["-60s", "0s"]
    assert {cell.column for cell in plot(a)} == {114, 117}
    assert {cell.column for cell in plot(b)} == {111, 117}
    assert a == again and sample == before


@pytest.mark.parametrize("kind,stale", [(kind, stale) for kind in ModelType for stale in (False, True)])
def test_types_failure_and_recovery_use_same_fixed_slots(kind, stale):
    cells = cells_for(object_snapshot(kind=kind, stale=stale), kind=kind)
    assert row(cells, 2).strip() and row(cells, 3).strip()
    assert "RUNNING" in row(cells, 6)
    assert row(cells, 8).strip() and row(cells, 9).strip() and row(cells, 10).strip()
    assert "HISTORY" in row(cells, 12)
    assert_contained(cells)


@pytest.mark.parametrize("region", [REGION, Region("service", 22, 5, 160, 20)])
def test_unicode_long_names_and_control_characters_stay_inside_service_content(region):
    configured_model = model(name="长模型e\u0301" * 40 + "\x1b[31m\nleak")
    configuration = config(configured_model)
    cells = vllm_cells(StateSnapshot((object_snapshot(),)), configuration, region,
                      ViewSelection("chat"), now=NOW)
    assert_contained(cells, region)
    assert "RUNNING" in row(cells, 6, region)


@pytest.mark.parametrize("region", [REGION, Region("service", 22, 5, 160, 20)])
def test_long_names_do_not_overwrite_internal_columns_or_reserved_status(region):
    configuration = config(model(name="Very-long-model-" * 30))
    cells = vllm_cells(StateSnapshot((object_snapshot(),)), configuration, region,
                      ViewSelection("chat"), now=NOW)
    divider = region.column + 27
    left = tuple(cell for cell in cells if cell.column < divider)
    assert all(column < divider for cell in left for _, column in pixels((cell,)))
    assert "QUEUED" in row(cells, 2, region)
    assert token_roles(cells, 2, "QUEUED", region) == {"amber"}
    right_status = set()
    for cell in right_cells(cells, region):
        if cell.row == region.row + 2 and cell.text == "QUEUED":
            right_status.update(pixels((cell,)))
    assert right_status
    assert all(not right_status.intersection(pixels((cell,)))
               for cell in cells
               if cell.row == region.row + 2 and cell.role != "amber")
    assert any(cell.text == "QUEUED" and cell.row == region.row + 2 for cell in left)
    assert "RUNNING" in row(cells, 6, region) and "WAITING" in row(cells, 6, region)
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
    assert columns == [30, 51, 117]


def test_single_history_point_at_now_retains_fixed_axis_and_rightmost_position():
    cells = cells_for(object_snapshot(history=(point(NOW, 0),)))
    assert row(cells, 14).split() == ["-60s", "0s"]
    assert "·" in content(plot(cells))
    assert pixels(plot(cells)) == {(REGION.row + 13, 117): ("·", "primary")}
    assert "Scale ≤ 1 tok/s" in row(cells, 12)


def test_compose_frame_uses_monotonic_default_and_explicit_clock_without_wall_conversion(monkeypatch):
    snapshot = StateSnapshot((object_snapshot(history=(point(98, 2), point(100, 4))),))
    monkeypatch.setattr("joi_observer.tui.layout.time.monotonic", lambda: NOW)
    args = (snapshot, config(), TerminalSize(120, 36), HostInfo("local", "Ubuntu"), WALL_NOW)
    default = compose_frame(*args)
    injected = compose_frame(*args, monotonic_now=NOW)
    assert default == injected
    assert "-60s" in content(default.cells) and "0s" in content(default.cells)
    assert "-2s" not in content(default.cells)


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
    unit = "tok/s" if kind == ModelType.CHAT else "seq/s"
    assert f"Scale ≤ 10 {unit}" in row(spike_cells, 12)


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
    assert models[-1].name in row(cells, 2, service)
    assert "QUEUED" in row(cells, 2, service)
    assert "RUNNING" in row(cells, 6, service) and "Total" in row(cells, 7, service)
    assert "HISTORY" in row(cells, 12, service)
    assert "-60s" in row(cells, service.height - 2, service)
    assert "0s" in row(cells, service.height - 2, service)


def test_history_stays_in_fixed_buckets_until_current_bucket_advances():
    item = object_snapshot(history=(point(60, 5), point(98, 0), point(100, 10)))
    before = deepcopy(item)
    first = pixels(plot(cells_for(item, now=100)))
    same_bucket = pixels(plot(cells_for(item, now=100.1)))
    next_bucket = pixels(plot(cells_for(item, now=100.81)))
    assert first == same_bucket
    assert {column for _, column in first} == {59, 114, 117}
    assert next_bucket == {(row_index, column - 1): pixel
                           for (row_index, column), pixel in first.items()}
    assert item == before


def test_expiring_first_point_does_not_stretch_remaining_history():
    item = object_snapshot(history=(point(40, 0), point(60, 5), point(100, 10)))
    first = pixels(plot(cells_for(item, now=100)))
    expired = pixels(plot(cells_for(item, now=100.1)))
    assert expired == {coordinate: pixel for coordinate, pixel in first.items() if coordinate[1] != 30}
    assert {column for _, column in expired} == {59, 117}


def test_bucket_boundary_keeps_left_value_separate_from_gap_on_and_after_boundary():
    # 60s is an exactly representable bucket boundary: before x58, on/after x59.
    boundary = 60
    item = object_snapshot(history=(point(boundary - 1e-6, 5), HistoryPoint(boundary, None),
                                    point(boundary + 1e-6, 1e300), point(100, 10)))
    cells = cells_for(item)
    assert {cell.column for cell in plot(cells)} == {58, 117}
    assert bar_eighths(cells, 58) == 4
    assert bar_eighths(cells, 117) == 8
    assert "Scale ≤ 10 tok/s" in row(cells, 12)


@pytest.mark.parametrize("maximum,upper,eighths", (
    (0, 1, 0), (0.25, 1, 2), (1, 1, 8), (1.1, 2, 5),
    (2, 2, 8), (3, 5, 5), (23, 50, 4), (121, 200, 5),
))
def test_pure_history_uses_smallest_nice_scale_without_stretching_peak(maximum, upper, eighths):
    cells = cells_for(object_snapshot(history=(point(100, maximum),)))
    assert f"Scale ≤ {upper} tok/s" in row(cells, 12)
    assert bar_eighths(cells, 117) == eighths
    assert {cell.column for cell in plot(cells)} == {117}
    if maximum == 0:
        assert pixels(plot(cells)) == {(REGION.row + 13, 117): ("·", "primary")}


def test_pure_rendering_does_not_keep_hidden_scale_or_delay_a_lower_default():
    high = object_snapshot(history=(point(100, 121),))
    low = object_snapshot(history=(point(100, 23),))
    before = deepcopy((high, low))
    assert "Scale ≤ 200 tok/s" in row(cells_for(high), 12)
    lower = cells_for(low)
    assert "Scale ≤ 50 tok/s" in row(lower, 12)
    assert bar_eighths(lower, 117) == 4
    cells_for(high)
    assert cells_for(low) == lower
    assert (high, low) == before


@pytest.mark.parametrize("kind", tuple(ModelType), ids=lambda kind: kind.value)
@pytest.mark.parametrize("region", (REGION, Region("service", 22, 5, 160, 20)))
def test_explicit_scale_sets_bar_height_and_muted_right_aligned_label(kind, region):
    from joi_observer.tui.history import HistoryScale

    field, unit = ("decode_rate", "tok/s") if kind == ModelType.CHAT else ("rate", "seq/s")
    item = object_snapshot(kind=kind, history=(point(100, 100, kind),))
    view = ViewSelection("chat", "hologram")
    scales = (HistoryScale("chat", field, 200),)
    before = deepcopy((item, view, scales))
    cells = cells_for(item, kind=kind, region=region, view=view, history_scales=scales)
    title = next(cell for cell in cells if "HISTORY /" in cell.text)
    label = next(cell for cell in cells if cell.text == f"Scale ≤ 200 {unit}")
    assert label.row == title.row == region.row + 12
    assert label.role == "muted"
    assert label.column + len(label.text) == region.column + region.width - 2
    assert title.column + len(title.text) < label.column
    # A value of 100 against the explicit 200 upper uses exactly half the
    # remaining plot height, including a half block for odd plot heights.
    bars = pixels(plot(cells, region))
    assert {x for _, x in bars} == {region.column + region.width - 3}
    assert len(bars) == (region.height - 14) // 2
    assert sum("▁▂▃▄▅▆▇█".index(character) + 1 for character, _ in bars.values()) == (region.height - 15) * 4
    assert all(role == "primary" for _, role in bars.values())
    assert sum(character == "▄" for character, _ in bars.values()) == 1
    assert (item, view, scales) == before
    assert_contained(cells, region)


def test_explicit_scales_match_model_and_field_and_flow_through_compose_frame():
    from joi_observer.tui.history import HistoryScale

    item = object_snapshot(history=(point(100, 23),))
    sample, configured, view = StateSnapshot((item,), 17), config(), ViewSelection("chat", "moonlight")
    unrelated = (HistoryScale("other", "decode_rate", 1000), HistoryScale("chat", "rate", 500))
    matching = unrelated + (HistoryScale("chat", "decode_rate", 200),)
    before = deepcopy((sample, configured, view, matching))
    baseline = cells_for(item)
    assert cells_for(item, history_scales=()) == baseline
    assert cells_for(item, history_scales=unrelated) == baseline
    explicit = cells_for(item, view=view, history_scales=matching)
    assert bar_eighths(baseline, 117) == 4
    assert bar_eighths(explicit, 117) == 1
    frame = compose_frame(sample, configured, TerminalSize(120, 36), HostInfo("offline", "Ubuntu"),
                          WALL_NOW, view=view, monotonic_now=100, history_scales=matching)
    assert set(explicit).issubset(frame.cells)
    assert (sample, configured, view, matching) == before


@pytest.mark.parametrize("upper", (0, -1, True, 2.0, "200", 3, 25, 10))
def test_invalid_or_peak_clipping_explicit_scale_is_rejected(upper):
    from joi_observer.tui.history import HistoryScale

    scales = (HistoryScale("chat", "decode_rate", upper),)
    with pytest.raises(ValueError):
        cells_for(object_snapshot(history=(point(100, 23),)), history_scales=scales)


def test_duplicate_explicit_scale_keys_are_rejected():
    from joi_observer.tui.history import HistoryScale

    scales = (HistoryScale("chat", "decode_rate", 50), HistoryScale("chat", "decode_rate", 200))
    with pytest.raises(ValueError):
        cells_for(object_snapshot(history=(point(100, 23),)), history_scales=scales)


@pytest.mark.parametrize("maximum", (1e300, 10**300), ids=("float", "integer"))
@pytest.mark.parametrize("explicit", (False, True), ids=("automatic", "explicit"))
def test_large_finite_history_uses_bounded_scientific_scale_label_without_overflow(maximum, explicit):
    from joi_observer.tui.history import HistoryScale

    scales = (HistoryScale("chat", "decode_rate", 2 * 10**300),) if explicit else None
    cells = cells_for(object_snapshot(history=(point(100, maximum),)), history_scales=scales)
    assert bar_eighths(cells, 117) > 0
    title = next(cell for cell in cells if "HISTORY /" in cell.text)
    label = next(cell for cell in cells if cell.text.startswith("Scale ≤ "))
    assert label.role == "muted" and label.row == title.row
    assert label.column + len(label.text) == REGION.column + REGION.width - 2
    assert title.column + len(title.text) < label.column
    assert label.text.endswith(" tok/s")
    assert "inf" not in label.text.lower() and "nan" not in label.text.lower()
    assert_contained(cells)


@pytest.mark.parametrize("explicit", (False, True), ids=("automatic", "explicit"))
def test_largest_finite_float_uses_arbitrary_precision_scale_without_overflow(explicit):
    from joi_observer.tui.history import HistoryScale

    upper = 2 * 10**308
    scales = (HistoryScale("chat", "decode_rate", upper),) if explicit else None
    item = object_snapshot(history=(point(100, sys.float_info.max),))
    before = deepcopy((item, scales))
    cells = cells_for(item, history_scales=scales)
    assert bar_eighths(cells, 117) == 8
    assert "·" not in content(plot(cells))
    title = next(cell for cell in cells if "HISTORY /" in cell.text)
    label = next(cell for cell in cells if cell.text.startswith("Scale ≤ "))
    assert label.role == "muted" and label.row == title.row
    assert label.column + len(label.text) == REGION.column + REGION.width - 2
    assert title.column + len(title.text) < label.column
    assert label.text.endswith(" tok/s")
    # Decimal accepts scientific notation without coercing the valid integer
    # upper to an overflowing binary float or fixing cosmetic exponent syntax.
    assert Decimal(label.text.removeprefix("Scale ≤ ").removesuffix(" tok/s")) == Decimal(upper)
    assert (item, scales) == before
    assert_contained(cells)


@pytest.mark.parametrize("mode", ("automatic-minimum", "automatic-large", "explicit-large"))
def test_smallest_positive_float_stays_one_eighth_even_when_ratio_underflows(mode):
    from joi_observer.tui.history import HistoryScale

    tiny = math.nextafter(0.0, 1.0)
    history = ((point(98, sys.float_info.max),) if mode == "automatic-large" else ()) + (point(100, tiny),)
    scales = (HistoryScale("chat", "decode_rate", 2 * 10**308),) if mode == "explicit-large" else None
    item = object_snapshot(history=history)
    before = deepcopy((item, scales))
    cells = cells_for(item, history_scales=scales)
    actual = {coordinate: pixel for coordinate, pixel in pixels(plot(cells)).items() if coordinate[1] == 117}
    assert actual == {(REGION.row + 13, 117): ("▁", "primary")}
    assert (item, scales) == before
    assert_contained(cells)


@pytest.mark.parametrize("region", (REGION, Region("service", 22, 5, 160, 20)))
@pytest.mark.parametrize("kind", tuple(ModelType), ids=lambda kind: kind.value)
def test_html_service_rail_counts_and_four_metric_columns_keep_fixed_slots(region, kind):
    cells = cells_for(kind=kind, region=region)
    grid = pixels(cells)
    left, right = region.column + 30, region.column + region.width - 2
    for offset in (1, 5, 11):
        assert slot_text(cells, region.row + offset, left, right).strip() == ""
        assert not any(cell.row == region.row + offset and left <= cell.column < right for cell in cells)
    middle = left + (right - left) // 2
    left_end, right_start = middle - 1, middle + 2
    rail = tuple(cell for cell in cells if cell.column < region.column + 27)
    header = next(cell for cell in rail if cell.text == "MODELS / 1")
    assert (header.row, header.column, header.role) == (region.row + 1, region.column + 2, "muted")
    name = next(cell for cell in rail if cell.text == "chat")
    assert (name.row, name.column, name.role) == (region.row + 2, region.column + 4, "primary")
    assert name.column + len(name.text) <= region.column + 19
    marker = next(cell for cell in rail if cell.text == "›")
    assert (marker.row, marker.column) == (name.row, region.column + 2)
    status = next(cell for cell in rail if cell.text == "QUEUED")
    assert (status.row, status.column) == (name.row, region.column + 20)
    type_port = next(cell for cell in rail if cell.text == f"{kind.value.upper()} / :8000")
    assert (type_port.row, type_port.column, type_port.role) == (region.row + 3, region.column + 2, "muted")
    assert all(region.column + 2 <= column < region.column + 26
               for cell in rail for _, column in pixels((cell,)))
    assert not any(cell.row == region.row + 5 for cell in rail)
    for offset in (4, 8):
        assert all(grid[region.row + offset, column][0] in "─━"
                   for column in range(left, right))
        assert {grid[region.row + offset, column][1] for column in range(left, right)} == {"muted"}
    assert grid[region.row + 6, middle][0] in "│┃"
    assert grid[region.row + 7, middle][0] in "│┃"
    assert grid[region.row + 6, middle][1] == grid[region.row + 7, middle][1] == "muted"
    detail = right_cells(cells, region)
    bold_positions = set()
    for label, start, end, expected in (("RUNNING", left, left_end, "3"),
                                        ("WAITING", right_start, right, "7")):
        label_cell = next(cell for cell in detail if cell.row == region.row + 6 and cell.text == label)
        value = next(cell for cell in detail if cell.row == region.row + 6 and cell.text == expected)
        assert label_cell.column == start
        assert label_cell.role == "text"
        assert not label_cell.bold and value.bold
        bold_positions.add((value.row, value.column))
        assert value.column + len(value.text) == end
        assert label_cell.column + len(label_cell.text) < value.column
    assert_span_role(cells, region.row + 7, left, "Total 10 seq", "muted")
    assert_span_role(cells, region.row + 7, right_start,
                     "Avg queue 0.5s" if kind == ModelType.CHAT else "Unit: seq", "muted")
    assert "Total" not in row(cells, 6, region)
    captions = ("DECODE / tok/s", "PREFILL / tok/s", "TTFT / s", "KV CACHE / %") if kind == ModelType.CHAT else (
        "RATE / seq/s", "Avg queue / s", "Avg latency / s", "KV CACHE / %")
    values = ("100", "500", "3", "25") if kind == ModelType.CHAT else ("3", "0.5", "3", "N/A")
    width = (right - left - 3) // 4
    for index, (caption, value) in enumerate(zip(captions, values)):
        start = left + index * (width + 1)
        stop = right if index == 3 else start + width
        label_cells = [cell for cell in detail if cell.row == region.row + 9 and start <= cell.column < stop]
        value_cells = [cell for cell in detail if cell.row == region.row + 10 and start <= cell.column < stop]
        assert [(cell.column, cell.text) for cell in label_cells] == [(start, caption)]
        assert label_cells[0].role == "muted"
        assert len(value_cells) == 1 and value_cells[0].text == value
        assert value_cells[0].role == "text"
        assert not label_cells[0].bold
        assert value_cells[0].bold is (value != "N/A")
        if value != "N/A":
            bold_positions.add((value_cells[0].row, value_cells[0].column))
        assert value_cells[0].column + len(value) <= stop
    assert "[" not in row(cells, 2, region)
    assert {(cell.row, cell.column) for cell in cells if cell.bold} == bold_positions
    assert_contained(cells, region)


@pytest.mark.parametrize("url,expected", (
    ("http://offline.invalid", "CHAT"),
    ("https://offline.invalid/path?q=:9999", "CHAT"),
    ("http://[::1]:8100/v1", "CHAT / :8100"),
))
def test_model_type_port_uses_only_explicit_configured_url_port(url, expected):
    configured = config(replace(model(), base_url=url))
    cells = vllm_cells(StateSnapshot((object_snapshot(),)), configured, REGION, ViewSelection("chat"), now=NOW)
    type_cells = [cell for cell in cells if cell.row == REGION.row + 3 and cell.column < 27]
    assert [(cell.text, cell.role) for cell in type_cells] == [(expected, "muted")]
    assert "↳ " + url in row(cells, 3)


@pytest.mark.parametrize("kind", tuple(ModelType), ids=lambda kind: kind.value)
@pytest.mark.parametrize("running,waiting,stale", (
    (3, 7, False), (1234, 123, False), (0, 0, False), (None, None, False), (3, 7, True),
), ids=("normal", "multiple-digits", "zero", "unknown", "stale"))
def test_model_rail_counts_have_fixed_alignment_and_separate_label_roles(kind, running, waiting, stale):
    item = object_snapshot(kind=kind, running=running, waiting=waiting, stale=stale,
                           total=None if running is None or waiting is None else running + waiting)
    before = deepcopy(item)
    cells = cells_for(item, kind=kind)
    r = REGION.row + 4
    run_text, wait_text = ("—" if value is None else str(value) for value in (running, waiting))
    left, right = run_text + " running", wait_text + " waiting"
    assert slot_text(cells, r, 2, 14) == left.ljust(12)
    assert slot_text(cells, r, 14, 15) == " "
    assert slot_text(cells, r, 15, 26) == right.rjust(11)
    assert_span_role(cells, r, 2, run_text, "text")
    assert_span_role(cells, r, 3 + len(run_text), "running", "muted")
    wait_start = 26 - len(right)
    assert_span_role(cells, r, wait_start, wait_text,
                     "amber" if waiting is not None and waiting > 0 and not stale else "text")
    assert_span_role(cells, r, wait_start + len(wait_text) + 1, "waiting", "muted")
    assert item == before
    assert_contained(cells)


@pytest.mark.parametrize("kind", tuple(ModelType), ids=lambda kind: kind.value)
@pytest.mark.parametrize("value", (None, 0), ids=("unknown", "zero"))
def test_all_model_types_keep_missing_and_zero_values_in_their_four_fixed_slots(kind, value):
    item = object_snapshot(kind=kind, decode_rate=value, prefill_rate=value, ttft_seconds=value,
                           kv_cache_percent=value, rate=value, queue_seconds=value, latency_seconds=value,
                           running=value, waiting=value, total=value)
    cells = cells_for(item, kind=kind)
    expected = "—" if value is None else "0"
    values = [expected] * 4 if kind == ModelType.CHAT else [expected] * 3 + ["N/A"]
    for start, end, text in zip((30, 52, 74, 96), (51, 73, 95, 118), values):
        actual = slot_text(cells, REGION.row + 10, start, end)
        assert actual.strip() == text
        assert_span_role(cells, REGION.row + 10, start + actual.index(text), text, "text")
    assert_span_role(cells, REGION.row + 6, 72, expected, "text")
    assert_span_role(cells, REGION.row + 6, 117, expected, "text")
    assert_span_role(cells, REGION.row + 7, 30, f"Total {expected} seq", "muted")
    caption = ("Avg queue —" if value is None else "Avg queue 0s") if kind == ModelType.CHAT else "Unit: seq"
    assert_span_role(cells, REGION.row + 7, 76, caption, "muted")
    assert not any(cell.role == "amber" for cell in cells)
    expected_bold = set() if value is None else {
        (REGION.row + 6, 72), (REGION.row + 6, 117),
        *((REGION.row + 10, start) for start in ((30, 52, 74, 96) if kind == ModelType.CHAT else (30, 52, 74))),
    }
    assert {(cell.row, cell.column) for cell in cells if cell.bold} == expected_bold


@pytest.mark.parametrize("kind", tuple(ModelType), ids=lambda kind: kind.value)
@pytest.mark.parametrize("stale", (False, True), ids=("fresh", "stale"))
def test_statistic_lines_caption_ownership_and_title_status_edge(kind, stale):
    # A focused check reaches the detail contract independently of the new rail.
    cells = cells_for(object_snapshot(kind=kind, stale=stale), kind=kind)
    assert {(cell.row, cell.column) for cell in cells if cell.bold} == {
        (REGION.row + 6, 72), (REGION.row + 6, 117),
        *((REGION.row + 10, start) for start in ((30, 52, 74, 96) if kind == ModelType.CHAT else (30, 52, 74))),
    }
    grid = pixels(cells)
    for offset in (4, 8):
        for column in range(30, 118):
            char, role = grid[REGION.row + offset, column]
            assert char in "─━" and role == "muted"
    for offset in (6, 7):
        char, role = grid[REGION.row + offset, 74]
        assert char in "│┃" and role == "muted"
    status = "STALE" if stale else "QUEUED"
    assert_span_role(cells, REGION.row + 2, 118 - len(status), status, "text" if stale else "amber")
    assert slot_text(cells, REGION.row + 2, 112, 118) == status.rjust(6)
    assert_span_role(cells, REGION.row + 6, 30, "RUNNING", "text")
    assert_span_role(cells, REGION.row + 6, 76, "WAITING", "text")
    assert_span_role(cells, REGION.row + 7, 30, "Total 10 seq", "muted")
    assert_span_role(cells, REGION.row + 7, 76,
                     "Avg queue 0.5s" if kind == ModelType.CHAT else "Unit: seq", "muted")


@pytest.mark.parametrize("kind", tuple(ModelType), ids=lambda kind: kind.value)
def test_large_latest_statistics_and_metrics_keep_exponents_and_stay_inside_slots(kind):
    import re
    from joi_observer.tui.layout import format_metric

    item = object_snapshot(kind=kind, running=10**300, waiting=10**300, total=2 * 10**300,
                           decode_rate=1e300, prefill_rate=1e300, ttft_seconds=1e300,
                           rate=1e300, queue_seconds=1e300, latency_seconds=1e300)
    before = deepcopy(item)
    public_format = tuple(format_metric(metric) for metric in item.metrics)
    cells = cells_for(item, kind=kind)

    def assert_scientific(text, expected):
        assert re.fullmatch(r"\d(?:\.\d{1,2})?[eE][+-]?\d+", text), text
        assert Decimal(text) == Decimal(expected)

    for start, end in ((30 + len("RUNNING") + 1, 73), (76 + len("WAITING") + 1, 118)):
        value = slot_text(cells, REGION.row + 6, start, end)
        assert value.endswith(value.strip())
        assert_scientific(value.strip(), "1e300")
    for start, end, label in ((2, 14, "run"), (15, 26, "wait")):
        slot = slot_text(cells, REGION.row + 4, start, end)
        text = slot.strip()
        assert slot == (text.ljust(end - start) if start == 2 else text.rjust(end - start))
        number, actual_label = text.split()
        assert actual_label == label
        assert_scientific(number, "1e300")
    for start, end in ((30, 51), (52, 73), (74, 95)):
        assert_scientific(slot_text(cells, REGION.row + 10, start, end).strip(), "1e300")
    expected_last = "25" if kind == ModelType.CHAT else "N/A"
    assert slot_text(cells, REGION.row + 10, 96, 118).strip() == expected_last
    caption = slot_text(cells, REGION.row + 7, 30, 73).strip()
    assert caption.startswith("Total ") and caption.endswith(" seq")
    assert_scientific(caption.removeprefix("Total ").removesuffix(" seq"), "2e300")
    if kind == ModelType.CHAT:
        queue = slot_text(cells, REGION.row + 7, 76, 118).strip()
        assert queue.startswith("Avg queue ") and queue.endswith("s")
        assert_scientific(queue.removeprefix("Avg queue ").removesuffix("s"), "1e300")
    else:
        assert slot_text(cells, REGION.row + 7, 76, 118).strip() == "Unit: seq"
    assert item == before
    emphasized = [cell for cell in cells if cell.bold]
    assert len(emphasized) == (6 if kind == ModelType.CHAT else 5)
    assert all(cell.column >= 30 and cell.row in (REGION.row + 6, REGION.row + 10) for cell in emphasized)
    assert sum("e" in cell.text for cell in emphasized) == 5
    assert tuple(format_metric(metric) for metric in item.metrics) == public_format
    assert_contained(cells)


def test_rail_value_too_wide_even_after_short_label_uses_explicit_ellipsis():
    item = object_snapshot(running=10**10000, waiting=10**10000, total=2 * 10**10000)
    cells = cells_for(item)
    # Even '1e10000 wait' needs 12 columns, beyond the 11-column right slot.
    assert slot_text(cells, REGION.row + 4, 15, 26).strip() == "… wait"
    number, label = slot_text(cells, REGION.row + 4, 2, 14).strip().split()
    assert label == "run" and Decimal(number) == Decimal("1e10000")
    assert_contained(cells)


def test_right_metric_text_placeholders_and_elision_are_not_emphasized():
    cells = cells_for(object_snapshot(decode_rate="123", prefill_rate="x" * 100, ttft_seconds=None))
    assert row(cells, 10).split() == ["123", "…", "—", "25"]
    assert {(cell.row, cell.column) for cell in cells if cell.bold} == {
        (REGION.row + 6, 72), (REGION.row + 6, 117), (REGION.row + 10, 96),
    }


@pytest.mark.parametrize("values,status,role", (
    ({"running": 3, "waiting": 7}, "QUEUED", "amber"),
    ({"running": 3, "waiting": 0}, "READY", "text"),
    ({"running": 3, "waiting": 7, "stale": True}, "STALE", "text"),
    ({"running": None, "waiting": None, "sampled_at": None}, "—", "text"),
))
def test_status_text_in_both_reserved_slots_ends_at_its_right_edge(values, status, role):
    cells = cells_for(object_snapshot(**values))
    for offset, start, end in ((2, 112, 118), (2, 20, 26)):
        row_index = REGION.row + offset
        assert slot_text(cells, row_index, start, end) == status.rjust(6)
        assert_span_role(cells, row_index, end - len(status), status, role)
