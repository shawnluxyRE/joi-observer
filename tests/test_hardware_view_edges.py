"""Hardware presentation boundary checks using immutable source snapshots."""

from datetime import datetime, timezone
import unicodedata

import pytest

from joi_observer.config import AppConfig, ModelConfig, ModelType
from joi_observer.data.models import Metric, ObjectKey, ObjectSnapshot, StateSnapshot
from joi_observer.tui.layout import HostInfo, TerminalSize, ViewSelection, compose_frame, format_metric
from joi_observer.tui.widgets import capacity_text, hardware_cells, linked_gpu_ids, percentage_bar


UUIDS = tuple(f"GPU-00000000-0000-0000-0000-{index:012d}" for index in range(5))
NOW = datetime(2026, 10, 30, tzinfo=timezone.utc)


def sample(index, value=0, *, name="Device", stale=False):
    return ObjectSnapshot(ObjectKey("gpu", UUIDS[index]), (
        Metric("index", index), Metric("name", name),
        Metric("utilization_percent", value, "%"),
        Metric("memory_used_bytes", 0, "B"), Metric("memory_total_bytes", 16 * 2**30, "B"),
        Metric("temperature_c", 0, "°C"), Metric("power_w", 0, "W"),
    ), stale=stale, sampled_at=1.0)


def positions(cell):
    column = cell.column
    for character in cell.text:
        width = 0 if unicodedata.combining(character) else 2 if unicodedata.east_asian_width(character) in "WF" else 1
        for offset in range(width):
            yield cell.row, column + offset
        column += width


def test_negative_zero_is_a_real_zero_without_a_minus_sign():
    bar = percentage_bar(-0.0, 28)
    assert bar.text == "0%" and not bar.filled and len(bar.empty) == 28


@pytest.mark.parametrize("height", [37, 38, 45])
def test_five_card_content_has_no_overlapping_cells_at_minimum_or_odd_height(height):
    snapshot = StateSnapshot(tuple(sample(index, 100 if index % 2 else 0) for index in range(5)))
    config = AppConfig(mount_points=("/", "/data", "/cache"))
    frame = compose_frame(snapshot, config, TerminalSize(120, height), HostInfo("local", "Ubuntu"), NOW,
                          gpu_slots=UUIDS)
    assert not frame.too_small
    cells = hardware_cells(snapshot, config, frame.regions, gpu_slots=UUIDS)
    occupied = set()
    for cell in cells:
        coordinates = set(positions(cell))
        assert not occupied.intersection(coordinates), cell
        occupied.update(coordinates)
        region = next(region for region in frame.regions if region.row <= cell.row < region.row + region.height
                      and region.column <= cell.column < region.column + region.width)
        assert all(region.row <= row < region.row + region.height
                   and region.column < column < region.column + region.width - 1
                   for row, column in coordinates)
    text = " ".join(cell.text for cell in cells)
    assert "0%" in text and "100%" in text and "0.0 GiB" in text
    assert "0°C" in text and "0W" in text


def test_new_missing_uuid_slot_keeps_unknown_identity_without_exposing_uuid():
    frame = compose_frame(StateSnapshot(()), AppConfig(), TerminalSize(120, 37),
                          HostInfo("local", "Ubuntu"), NOW, gpu_slots=(UUIDS[0],))
    text = " ".join(cell.text for cell in frame.cells)
    assert "GPU —" in text and UUIDS[0] not in text


def test_control_characters_and_wide_names_cannot_damage_status_or_adjacent_panel():
    snapshot = StateSnapshot((sample(0, name="界\n\x1b\u202e" * 100, stale=True),))
    frame = compose_frame(snapshot, AppConfig(mount_points=("/mount\n\x1b" + "界" * 100,)),
                          TerminalSize(120, 37), HostInfo("local", "Ubuntu"), NOW,
                          gpu_slots=(UUIDS[0],))
    for cell in frame.cells:
        assert all(not unicodedata.category(character).startswith("C") for character in cell.text)
    stale = [cell for cell in frame.cells if cell.text == "STALE"]
    assert len(stale) == 1 and (stale[0].row, stale[0].column) == (3, 53)


def test_legacy_numeric_gpu_key_is_not_treated_as_an_explicit_uuid_mapping():
    legacy = ObjectSnapshot(ObjectKey("gpu", "0"), (Metric("usage", 25, "%"),), stale=True, sampled_at=1)
    config = AppConfig(models=(ModelConfig("model", ModelType.CHAT, "Model", "http://offline.invalid", ("0",)),))
    assert linked_gpu_ids(StateSnapshot((legacy,)), config, ViewSelection()) == ()


@pytest.mark.parametrize("sign", [1, -1])
def test_integer_metric_formatting_is_exact_beyond_float_and_integer_string_limits(sign):
    value = sign * (10**5000 + 7)
    expected = ("-" if sign < 0 else "") + "1" + "0" * 4999 + "7"
    assert format_metric(Metric("counter", value, "B")) == expected + "B"


def test_large_capacity_rounding_is_exact_without_decimal_context_or_string_limits():
    # Exactly 1.25 TiB beyond a 5001-digit integer rounds upward to 1.3.
    whole = 10**5000
    used = whole * 2**40 + 5 * 2**38
    total = (whole + 2) * 2**40
    prefix = "1" + "0" * 4999
    assert capacity_text(used, total) == (prefix + "1.3 TiB", prefix + "2.0 TiB")
    assert capacity_text(used - 1, total) == (prefix + "1.2 TiB", prefix + "2.0 TiB")


@pytest.mark.parametrize("value", [10**309, -(10**309), float("nan"), float("inf")])
def test_invalid_percentage_is_value_error_without_attempting_float_conversion(value):
    with pytest.raises(ValueError):
        percentage_bar(value, 28)


def test_large_gpu_index_mapping_and_frame_keep_exact_alias_and_bounded_cells():
    huge = 10**5000 + 7
    alias = "1" + "0" * 4999 + "7"
    original = sample(0)
    metrics = tuple(Metric("index", huge) if metric.name == "index" else metric
                    for metric in original.metrics)
    snapshot = StateSnapshot((ObjectSnapshot(original.key, metrics, sampled_at=1),))
    config = AppConfig(models=(ModelConfig("model", ModelType.CHAT, "Model", "http://offline.invalid", (alias,)),))
    assert linked_gpu_ids(snapshot, config, ViewSelection()) == (UUIDS[0],)
    frame = compose_frame(snapshot, config, TerminalSize(120, 37), HostInfo("local", "Ubuntu"), NOW,
                          gpu_slots=(UUIDS[0],))
    assert not frame.too_small
    labels = [cell for cell in frame.cells if cell.text.startswith("GPU 1")]
    assert len(labels) == 1 and labels[0].role == "primary"
    for cell in frame.cells:
        assert all(0 <= row < 37 and 0 <= column < 120 for row, column in positions(cell))
