"""REQ-002 hardware view contracts; immutable samples only, with no OS or network IO.

The new public widgets and their compose_frame integration are R4 work. These
assertions expect completed behavior; an unimplemented entry remains a failure.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import unicodedata

import pytest

from joi_observer.config import AppConfig, ModelConfig, ModelType
from joi_observer.data.models import Metric, ObjectKey, ObjectSnapshot, StateSnapshot
from joi_observer.tui.layout import HostInfo, Region, TerminalSize, ViewSelection, compose_frame
from joi_observer.tui.widgets import (
    PercentageBar,
    capacity_text,
    hardware_cells,
    linked_gpu_ids,
    percentage_bar,
)


GIB = 2**30
TIB = 2**40
UUIDS = tuple(f"GPU-00000000-0000-0000-0000-{index:012d}" for index in range(5))
REGIONS = (
    Region("gpu", 2, 0, 60, 20),
    Region("host", 2, 61, 59, 5),
    Region("storage", 8, 61, 59, 6),
)
GPU_REGION, HOST_REGION, STORAGE_REGION = REGIONS
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def model(identifier, gpu_ids=()):
    return ModelConfig(identifier, ModelType.CHAT, identifier, "http://offline.invalid", gpu_ids)


def configured(mounts=("/", "/data")):
    return AppConfig(
        mount_points=mounts,
        models=(model("A", ("0", "1", "2", "3")), model("B", ("4",)), model("unknown")),
    )


def gpu(index, *, stale=False, sampled_at=1.0, uuid=None, name=None, temperature=60):
    return ObjectSnapshot(
        ObjectKey("gpu", uuid or UUIDS[index]),
        (
            Metric("index", index), Metric("name", name or f"Device-{index}"),
            Metric("utilization_percent", 25 if index % 2 == 0 else 50, "%"),
            Metric("memory_used_bytes", (index + 1) * GIB, "B"),
            Metric("memory_total_bytes", 16 * GIB, "B"),
            Metric("temperature_c", temperature, "°C"), Metric("power_w", 100 + index, "W"),
        ),
        stale=stale, sampled_at=sampled_at,
    )


def inventory(count=None, *, stale=False, sampled_at=None):
    return ObjectSnapshot(ObjectKey("gpu_inventory", "local"),
                          (Metric("device_count", count),), stale=stale, sampled_at=sampled_at)


def host_objects(*, cpu_stale=False, ram_stale=False):
    return (
        ObjectSnapshot(ObjectKey("host", "cpu"), (Metric("cpu_percent", 25, "%"),),
                       stale=cpu_stale, sampled_at=1.0),
        ObjectSnapshot(ObjectKey("host", "ram"), (
            Metric("ram_used_bytes", 4 * GIB, "B"), Metric("ram_total_bytes", 16 * GIB, "B"),
            Metric("ram_percent", 25, "%"),
        ), stale=ram_stale, sampled_at=1.0),
    )


def mount(index, *, stale=False, used=GIB, total=4 * GIB):
    return ObjectSnapshot(ObjectKey("storage", f"mount-{index}"), (
        Metric("used_bytes", used, "B"), Metric("total_bytes", total, "B"),
        Metric("used_percent", 100 * used / total, "%"),
    ), stale=stale, sampled_at=1.0)


def pixels(cells):
    """Read the public TextCell output as a terminal would, including wide glyphs."""
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


def line(cells, row, region):
    grid = pixels(cells)
    return "".join(grid.get((row, column), (" ", "text"))[0]
                   for column in range(region.column, region.column + region.width))


def text_roles(cells, row, region, token):
    content = line(cells, row, region)
    start = content.index(token) + region.column
    grid = pixels(cells)
    return {grid[row, column][1] for column in range(start, start + len(token))}


def assert_contained(cells, regions=REGIONS):
    for cell in cells:
        assert "\x1b" not in cell.text and "\n" not in cell.text and "\r" not in cell.text
        assert cell.role != "amber"
        coordinates = pixels((cell,))
        assert any(all(region.row <= row < region.row + region.height
                       and region.column <= column < region.column + region.width
                       for row, column in coordinates) for region in regions)


@pytest.mark.parametrize("value,width,filled,empty,text", [
    (None, 4, "", "░░░░", "—"),
    (0, 4, "", "░░░░", "0%"),
    (100, 4, "████", "", "100%"),
    (25, 4, "█", "░░░", "25%"),
    (25.45, 20, "█████", "░" * 15, "25.5%"),
    (24.95, 2, "█", "░", "25%"),
    (12.5, 4, "█", "░░░", "12.5%"),
])
def test_percentage_bar_uses_one_rounded_value_for_text_and_segments(value, width, filled, empty, text):
    assert percentage_bar(value, width) == PercentageBar(filled, empty, text)


@pytest.mark.parametrize("value,width", [
    (-1, 10), (101, 10), (float("nan"), 10), (float("inf"), 10),
    (True, 10), ("25", 10), (25, 0), (25, -1), (25, True), (25, 1.5),
])
def test_percentage_bar_rejects_invalid_values_and_widths(value, width):
    with pytest.raises(ValueError):
        percentage_bar(value, width)


@pytest.mark.parametrize("used,total,expected", [
    (4 * GIB, 16 * GIB, ("4.0 GiB", "16.0 GiB")),
    (0, 16 * GIB, ("0.0 GiB", "16.0 GiB")),
    (None, 16 * GIB, ("—", "16.0 GiB")),
    (4 * GIB, None, ("4.0 GiB", "—")),
    (None, None, ("—", "—")),
    (TIB // 2, TIB, ("0.5 TiB", "1.0 TiB")),
    (TIB, None, ("1.0 TiB", "—")),
    (5 * GIB // 4, 16 * GIB, ("1.3 GiB", "16.0 GiB")),
    (GIB, TIB - 1, ("1.0 GiB", "1024.0 GiB")),
])
def test_capacity_text_preserves_unknown_zero_and_binary_units(used, total, expected):
    assert capacity_text(used, total) == expected


@pytest.mark.parametrize("used,total", [
    (-1, GIB), (GIB, 0), (GIB, -1), (2 * GIB, GIB),
    (True, GIB), (GIB, True), (1.5, GIB), (GIB, "16"),
])
def test_capacity_text_rejects_inconsistent_or_nonintegral_bytes(used, total):
    with pytest.raises(ValueError):
        capacity_text(used, total)


@pytest.mark.parametrize("selected,expected", [
    (None, UUIDS[:4]), ("A", UUIDS[:4]), ("B", UUIDS[4:]),
    ("unknown", ()), ("missing", ()),
])
def test_model_gpu_mapping_uses_explicit_selection_without_reordering(selected, expected):
    sample = StateSnapshot(tuple(gpu(index) for index in range(5)))
    before = deepcopy(sample)
    assert linked_gpu_ids(sample, configured(), ViewSelection(selected)) == expected
    assert sample == before


@pytest.mark.parametrize("identifiers,expected", [
    ((UUIDS[4],), (UUIDS[4],)),
    (("4", UUIDS[4]), (UUIDS[4],)),
    (("04",), ()), (("+4",), ()), (("4.0",), ()),
    ((UUIDS[4][:-1],), ()), ((UUIDS[4].lower(),), ()), (("Device-4",), ()),
])
def test_gpu_identifiers_match_exact_uuid_or_canonical_index_only(identifiers, expected):
    config = AppConfig(models=(model("selected", identifiers),))
    assert linked_gpu_ids(StateSnapshot((gpu(4),)), config, ViewSelection()) == expected


def test_gpu_mapping_follows_snapshot_order_not_configured_alias_order():
    config = AppConfig(models=(model("selected", (UUIDS[4], "0", "2")),))
    sample = StateSnapshot((gpu(2), gpu(4), gpu(0)))
    assert linked_gpu_ids(sample, config, ViewSelection()) == (UUIDS[2], UUIDS[4], UUIDS[0])


@pytest.mark.parametrize("stale,sampled_at,identifier,expected", [
    (True, 1.0, "4", ()), (True, 1.0, UUIDS[4], (UUIDS[4],)),
    (False, None, "4", ()), (False, 1.0, "4", (UUIDS[4],)),
])
def test_old_index_is_not_an_active_mapping_but_explicit_uuid_remains_reliable(
    stale, sampled_at, identifier, expected,
):
    config = AppConfig(models=(model("selected", (identifier,)),))
    sample = StateSnapshot((gpu(4, stale=stale, sampled_at=sampled_at),))
    assert linked_gpu_ids(sample, config, ViewSelection()) == expected


def test_conflicting_fresh_indices_are_not_guessed_and_uuid_still_matches():
    duplicate = gpu(4, uuid=UUIDS[0])
    sample = StateSnapshot((duplicate, gpu(4)))
    by_index = AppConfig(models=(model("selected", ("4",)),))
    by_uuid = AppConfig(models=(model("selected", ("4", UUIDS[4])),))
    assert linked_gpu_ids(sample, by_index, ViewSelection()) == ()
    assert linked_gpu_ids(sample, by_uuid, ViewSelection()) == (UUIDS[4],)


def test_stale_duplicate_index_does_not_make_a_fresh_gpu_ambiguous():
    sample = StateSnapshot((gpu(4, uuid=UUIDS[0], stale=True), gpu(4)))
    config = AppConfig(models=(model("selected", ("4",)),))
    assert linked_gpu_ids(sample, config, ViewSelection()) == (UUIDS[4],)


def test_no_models_means_no_gpu_highlight():
    assert linked_gpu_ids(StateSnapshot((gpu(0),)), AppConfig(models=()), ViewSelection()) == ()


@pytest.mark.parametrize("invalid_index", [None, -1, True, 4.0, "4"])
def test_gpu_index_alias_requires_a_nonnegative_integer_metric(invalid_index):
    card = gpu(4)
    card = replace(card, metrics=tuple(replace(metric, value=invalid_index) if metric.name == "index" else metric
                                       for metric in card.metrics))
    config = AppConfig(models=(model("selected", ("4",)),))
    assert linked_gpu_ids(StateSnapshot((card,)), config, ViewSelection()) == ()


@pytest.mark.parametrize("selected,highlighted", [("A", {0, 1, 2, 3}), ("B", {4}), ("unknown", set())])
def test_five_gpu_rows_have_stable_three_line_content_and_only_associated_highlights(selected, highlighted):
    sample = StateSnapshot((inventory(5, sampled_at=1.0), *(gpu(index) for index in range(5))))
    before = deepcopy(sample)
    cells = hardware_cells(sample, configured(), REGIONS, gpu_slots=UUIDS, view=ViewSelection(selected))
    for index in range(5):
        row = GPU_REGION.row + 1 + 3 * index
        header = line(cells, row, GPU_REGION)
        bar = line(cells, row + 1, GPU_REGION)
        details = line(cells, row + 2, GPU_REGION)
        role = "primary" if index in highlighted else "muted"
        assert f"GPU {index}" in header and f"Device-{index}" in header
        assert text_roles(cells, row, GPU_REGION, str(index)) == {role}
        assert text_roles(cells, row, GPU_REGION, f"Device-{index}") == {"text"}
        expected_percent, expected_filled = ("25%", 7) if index % 2 == 0 else ("50%", 14)
        assert bar.count("█") == expected_filled and bar.count("░") == 28 - expected_filled
        assert expected_percent in bar and bar.index(expected_percent) >= bar.rindex("░") + 1
        assert text_roles(cells, row + 1, GPU_REGION, "█" * expected_filled) == {role}
        assert text_roles(cells, row + 1, GPU_REGION, expected_percent) == {role}
        assert text_roles(cells, row + 1, GPU_REGION, "░" * (28 - expected_filled)) == {"muted"}
        assert f"{index + 1}.0 GiB" in details and "16.0 GiB" in details
        assert "60" in details and "°C" in details and str(100 + index) in details and "W" in details
        assert text_roles(cells, row + 2, GPU_REGION, f"{index + 1}.0 GiB") == {"muted"}
        assert text_roles(cells, row + 2, GPU_REGION, "16.0 GiB") == {"muted"}
    assert sample == before
    assert_contained(cells)


def test_gpu_unknown_field_keeps_other_fields_and_failure_reuses_fixed_slot():
    sample = StateSnapshot((gpu(0, stale=True, temperature=None),))
    cells = hardware_cells(sample, configured(), REGIONS, gpu_slots=(UUIDS[0],))
    header_row = GPU_REGION.row + 1
    assert "STALE" in line(cells, header_row, GPU_REGION)
    assert "—" in line(cells, header_row + 2, GPU_REGION)
    assert "1.0 GiB" in line(cells, header_row + 2, GPU_REGION)
    assert "100" in line(cells, header_row + 2, GPU_REGION)
    assert all(cell.row == header_row and cell.column == GPU_REGION.column + GPU_REGION.width - 7
               for cell in cells if cell.text == "STALE")
    assert not any("last" in cell.text.lower() or "error" in cell.text.lower() for cell in cells)
    assert_contained(cells)


def test_unsupported_gpu_field_is_unknown_without_stale_or_zero_substitution():
    cells = hardware_cells(StateSnapshot((gpu(0, temperature=None),)), configured(),
                           REGIONS, gpu_slots=(UUIDS[0],))
    details = line(cells, 5, GPU_REGION)
    assert "—" in details and "1.0 GiB" in details and "100" in details
    assert "STALE" not in line(cells, 3, GPU_REGION)
    assert "0°C" not in details and "0 °C" not in details


def test_gpu_name_is_clipped_without_losing_number_or_status_and_unknown_index_is_not_uuid():
    known = gpu(0, stale=True, name="界" * 100)
    unknown = replace(gpu(1), metrics=tuple(replace(metric, value=None) if metric.name == "index" else metric
                                           for metric in gpu(1).metrics))
    cells = hardware_cells(StateSnapshot((known, unknown)), configured(), REGIONS, gpu_slots=UUIDS[:2])
    assert "GPU 0" in line(cells, 3, GPU_REGION) and "STALE" in line(cells, 3, GPU_REGION)
    assert "GPU —" in line(cells, 6, GPU_REGION)
    assert UUIDS[1] not in "".join(cell.text for cell in cells)
    assert_contained(cells)


@pytest.mark.parametrize("cpu_stale,ram_stale", [(False, False), (True, False), (False, True)])
def test_host_fields_are_named_and_ram_capacity_colors_are_separate(cpu_stale, ram_stale):
    # Reverse object and metric order so the view cannot mistake RAM bytes for CPU.
    cpu, ram = host_objects(cpu_stale=cpu_stale, ram_stale=ram_stale)
    sample = StateSnapshot((replace(ram, metrics=tuple(reversed(ram.metrics))), cpu))
    cells = hardware_cells(sample, AppConfig(mount_points=()), REGIONS, gpu_slots=())
    assert "CPU" in line(cells, 3, HOST_REGION) and "25%" in line(cells, 3, HOST_REGION)
    assert "RAM" in line(cells, 4, HOST_REGION) and "25%" in line(cells, 4, HOST_REGION)
    assert text_roles(cells, 3, HOST_REGION, "█") == {"secondary"}
    assert text_roles(cells, 4, HOST_REGION, "█") == {"secondary"}
    assert text_roles(cells, 5, HOST_REGION, "4.0 GiB") == {"muted"}
    assert text_roles(cells, 5, HOST_REGION, "16.0 GiB") == {"text"}
    assert ("STALE" in line(cells, HOST_REGION.row, HOST_REGION)) == (cpu_stale or ram_stale)
    assert_contained(cells)


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_storage_has_three_content_rows_with_ordered_numbered_identity(count):
    paths = ("/", "/data", "/cache")[:count]
    cells = hardware_cells(StateSnapshot(tuple(mount(index) for index in range(count))),
                           configured(paths), REGIONS, gpu_slots=())
    storage_cells = tuple(cell for cell in cells if STORAGE_REGION.column <= cell.column
                          and STORAGE_REGION.row <= cell.row < STORAGE_REGION.row + STORAGE_REGION.height)
    assert all(10 <= cell.row <= 12 for cell in storage_cells)
    if not count:
        assert any("No mount points configured" in cell.text for cell in storage_cells)
    for index, path in enumerate(paths):
        row = line(cells, 10 + index, STORAGE_REGION)
        assert path in row and "1.0 GiB" in row and "4.0 GiB" in row and "25%" in row
    for unused in range(count or 1, 3):
        assert not line(cells, 10 + unused, STORAGE_REGION).strip()
    assert_contained(cells)


def test_storage_long_path_reserves_capacity_percent_and_state_without_fourth_item_replacement():
    long_path = "/very-long-mount-" + "segment" * 30
    config = configured((long_path, "/data", "/cache", "/DO-NOT-SHOW"))
    sample = StateSnapshot((mount(0, stale=True), mount(1), mount(2), mount(3, used=3 * GIB)))
    cells = hardware_cells(sample, config, REGIONS, gpu_slots=())
    first = line(cells, 10, STORAGE_REGION)
    assert "/very" in first and "1.0 GiB" in first and "4.0 GiB" in first and "25%" in first
    assert "STALE" in first
    assert "/data" in line(cells, 11, STORAGE_REGION) and "/cache" in line(cells, 12, STORAGE_REGION)
    assert "DO-NOT-SHOW" not in "".join(cell.text for cell in cells)
    assert_contained(cells)


def test_numbered_storage_identity_wins_over_legacy_path_fixture():
    legacy = replace(mount(0, used=3 * GIB), key=ObjectKey("storage", "/"))
    cells = hardware_cells(StateSnapshot((legacy, mount(0))), configured(("/",)), REGIONS, gpu_slots=())
    row = line(cells, 10, STORAGE_REGION)
    assert "1.0 GiB" in row and "25%" in row and "3.0 GiB" not in row and "75%" not in row


@pytest.mark.parametrize("sample,empty_text,stale", [
    (inventory(), "—", False),
    (inventory(0, sampled_at=1.0), "No NVIDIA GPUs", False),
    (inventory(stale=True, sampled_at=1.0), "—", True),
])
def test_gpu_inventory_distinguishes_initial_unknown_successful_empty_and_failure(sample, empty_text, stale):
    cells = hardware_cells(StateSnapshot((sample,)), AppConfig(mount_points=()), REGIONS, gpu_slots=())
    assert empty_text in line(cells, 3, GPU_REGION)
    assert ("STALE" in line(cells, 2, GPU_REGION)) == stale
    if stale:
        assert "No NVIDIA GPUs" not in "".join(cell.text for cell in cells)
    assert_contained(cells)


def test_successful_empty_inventory_does_not_remove_previously_known_gpu_slot():
    sample = StateSnapshot((inventory(0, sampled_at=2.0), gpu(0, stale=True)))
    cells = hardware_cells(sample, configured(), REGIONS, gpu_slots=(UUIDS[0],))
    assert "GPU 0" in line(cells, 3, GPU_REGION) and "STALE" in line(cells, 3, GPU_REGION)
    assert "No NVIDIA GPUs" not in "".join(cell.text for cell in cells)


def test_compose_frame_integrates_named_hardware_values_without_generic_metric_dump():
    sample = StateSnapshot((inventory(1, sampled_at=1.0), gpu(0), *host_objects(), mount(0)))
    frame = compose_frame(sample, configured(("/",)), TerminalSize(120, 44),
                          HostInfo("offline-host", "Ubuntu"), NOW, gpu_slots=(UUIDS[0],))
    combined = "".join(cell.text for cell in frame.cells)
    assert "GPU 0" in combined and "Device-0" in combined and "25%" in combined
    assert "█" in combined and "4.0 GiB" in combined and "16.0 GiB" in combined
    assert "memory_used_bytes" not in combined and "ram_used_bytes" not in combined
    assert UUIDS[0] not in combined


def test_compose_failure_recovery_and_model_change_keep_regions_gpu_order_and_input_immutable():
    config = configured(("/", "/data", "/cache"))
    normal = StateSnapshot((inventory(5, sampled_at=1.0), *(gpu(index) for index in range(5)),
                            *host_objects(), *(mount(index) for index in range(3))))
    failed = replace(normal, objects=tuple(replace(obj, stale=True, sampled_at=987654321.25)
                                           if obj.key in {ObjectKey("gpu", UUIDS[2]), ObjectKey("storage", "mount-1")}
                                           else obj for obj in normal.objects))
    normal_before, failed_before, config_before = deepcopy((normal, failed, config))
    frames = [compose_frame(snapshot, config, TerminalSize(120, 44), HostInfo("offline", "Ubuntu"),
                            NOW, gpu_slots=UUIDS, view=ViewSelection(selected))
              for snapshot, selected in ((normal, "A"), (failed, "B"), (normal, "unknown"))]
    assert frames[0].regions == frames[1].regions == frames[2].regions
    for frame in frames:
        region = next(region for region in frame.regions if region.name == "gpu")
        for index in range(5):
            assert f"GPU {index}" in line(frame.cells, 3 + index * 3, region)
        assert "987654321" not in "".join(cell.text for cell in frame.cells)
    assert "STALE" in line(frames[1].cells, 9, GPU_REGION)
    assert "STALE" in line(frames[1].cells, 11, STORAGE_REGION)
    assert not any(cell.text == "STALE" for cell in frames[2].cells)
    assert (normal, failed, config) == (normal_before, failed_before, config_before)
