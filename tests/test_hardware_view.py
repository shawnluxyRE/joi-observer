"""Hardware view contracts; immutable samples only, with no OS or network IO.

Existing formatters and GPU mapping stay unchanged. Updated HTML-oriented
geometry remains a target; layout differences are ordinary failing assertions.
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
    Region("gpu", 2, 0, 71, 20),
    Region("host", 2, 72, 48, 6),
    Region("storage", 8, 72, 48, 6),
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


def device_rows(cells, region=GPU_REGION):
    return sorted(cell.row for cell in cells if cell.column == region.column + 2
                  and region.row < cell.row < region.row + region.height - 1 and cell.text.startswith("["))


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
def test_five_gpu_groups_have_separate_rules_and_titles_and_only_associated_highlights(selected, highlighted):
    names = ["NVIDIA GeForce RTX 5090"] * 4 + ["NVIDIA GeForce RTX 5060 Ti"]
    cards = tuple(gpu(index, name=name) for index, name in enumerate(names))
    sample = StateSnapshot((inventory(5, sampled_at=1.0), *cards))
    before = deepcopy(sample)
    config = configured()
    config = replace(config, models=(*config.models, model("reranker", (UUIDS[4],))))
    cells = hardware_cells(sample, config, REGIONS, gpu_slots=UUIDS, view=ViewSelection(selected))
    rows = device_rows(cells)
    assert len(rows) == 5
    assert [cell.text for cell in cells if cell.text.startswith("GPU ")] == ["GPU 0–3", "GPU 4"]
    divider_rows = {cell.row for cell in cells if "─" in cell.text}
    assert divider_rows == {rows[4] - 3}
    assert rows[3] + 1 < rows[4] - 3
    for index, row in enumerate(rows):
        heading = line(cells, row - 2, GPU_REGION)
        if index in (0, 4):
            assert line(cells, row - 1, GPU_REGION) == " " * GPU_REGION.width
        header = line(cells, row, GPU_REGION)
        bar = line(cells, row + 1, GPU_REGION)
        role = "primary" if index in highlighted else "muted"
        assert header.startswith(f"  [{index}] {names[index]} ")
        assert text_roles(cells, row, GPU_REGION, f"[{index}]") == {role}
        assert text_roles(cells, row, GPU_REGION, names[index]) == {"text"}
        expected_percent, expected_filled = ("25%", 8) if index % 2 == 0 else ("50%", 17)
        assert bar[2:35] == "▌" * 33
        assert expected_percent in bar and bar.index(expected_percent) == 36
        grid = pixels(cells)
        assert {grid[row + 1, column][1] for column in range(2, 2 + expected_filled)} == {role}
        assert text_roles(cells, row + 1, GPU_REGION, expected_percent) == {role}
        assert {grid[row + 1, column][1] for column in range(2 + expected_filled, 35)} == {"track"}
        assert f"{index + 1}.0 / 16.0 GiB" in header and "60°C" in header
        assert f"{100 + index} W" in bar
        if index == 0:
            assert row - 2 == GPU_REGION.row + 1
            assert heading.startswith("  GPU 0–3 ") and heading.endswith(" TP 4  ")
            assert not heading[10:-7].strip()
        elif index == 4:
            assert heading.startswith("  GPU 4 ") and heading.endswith(" SHARED  ")
            assert not heading[8:-9].strip()
            rule = "─" * (GPU_REGION.width - 4)
            assert line(cells, row - 3, GPU_REGION) == "  " + rule + "  "
            assert text_roles(cells, row - 3, GPU_REGION, rule) == {"muted"}
        assert text_roles(cells, row, GPU_REGION, f"{index + 1}.0 / 16.0 GiB") == {"muted"}
        assert text_roles(cells, row, GPU_REGION, "60°C") == {"text"}
        assert text_roles(cells, row + 1, GPU_REGION, f"{100 + index} W") == {"muted"}
    assert sample == before
    assert_contained(cells)


@pytest.mark.parametrize("assignments,types_by_slot", [
    pytest.param((("0", "1", "2", "3"), ("4",), (UUIDS[4],)), {0: "TP 4", 4: "SHARED"}, id="shared-last-card"),
    pytest.param((("0", UUIDS[0], "1", "2", "3"), ("4",)), {0: "TP 4", 4: "TP 1"}, id="duplicate-alias"),
    pytest.param((("0", "1"), ("1", "2"), ("3",), ("4",)), {0: "SHARED", 3: "TP 1", 4: "TP 1"}, id="overlap"),
    pytest.param(((UUIDS[2], "0"), ("1",), ("3", "4")), {3: "TP 2"}, id="interleaved-models"),
    pytest.param((("0", "1"), (), ("3", "4")), {0: "TP 2", 3: "TP 2"}, id="unknown-card-between-groups"),
    pytest.param((), {}, id="no-models"),
])
def test_group_types_follow_model_assignments_in_display_order(assignments, types_by_slot):
    sample = StateSnapshot(tuple(gpu(index) for index in reversed(range(5))))
    config = AppConfig(models=tuple(model(str(index), ids) for index, ids in enumerate(assignments)))
    cells = hardware_cells(sample, config, REGIONS, gpu_slots=UUIDS)
    rows = device_rows(cells)
    assert len(rows) == len(UUIDS)
    assert [(cell.row, cell.text) for cell in cells if cell.text.startswith("TP ") or cell.text == "SHARED"] == [
        (rows[slot] - 2, value) for slot, value in types_by_slot.items()
    ]
    for cell in cells:
        if cell.text.startswith("GPU "):
            assert line(cells, cell.row + 1, GPU_REGION) == " " * GPU_REGION.width
    if not assignments:
        assert not any(cell.text.startswith("GPU ") for cell in cells)
        assert "[0] Device-0" in line(cells, GPU_REGION.row + 1, GPU_REGION)


def test_nonconsecutive_gpu_indices_do_not_expand_the_group_range():
    config = AppConfig(models=(model("pair", ("0", UUIDS[2])),))
    sample = StateSnapshot((gpu(0), gpu(2)))
    cells = hardware_cells(sample, config, REGIONS, gpu_slots=(UUIDS[0], UUIDS[2]))
    heading = line(cells, GPU_REGION.row + 1, GPU_REGION).strip()
    assert heading.startswith("GPU 0,") and "2 " in heading and heading.endswith("TP 2")
    assert "0–2" not in heading


def test_partially_resolved_config_does_not_report_a_smaller_tp_size():
    config = AppConfig(models=(model("pair", ("0", "1")),))
    cells = hardware_cells(StateSnapshot((gpu(0),)), config, REGIONS, gpu_slots=UUIDS[:1])
    assert not any(cell.text.startswith("TP ") for cell in cells)


@pytest.mark.parametrize("alias,first_assigned", [("0", False), (UUIDS[0], True)])
def test_gpu_group_header_respects_stale_alias_and_leaves_room_for_status(alias, first_assigned):
    sample = StateSnapshot((gpu(0, stale=True), gpu(1)))
    config = AppConfig(models=(model("A", (alias,)), model("B", ("1",))))
    cells = hardware_cells(sample, config, REGIONS, gpu_slots=UUIDS[:2])
    first, second = device_rows(cells)
    assert ("GPU 0" in line(cells, first - 2, GPU_REGION)) == first_assigned
    assert "GPU 1" in line(cells, second - 2, GPU_REGION)
    bar_row = first + 1
    content = line(cells, bar_row, GPU_REGION)
    assert content.index("25%") < content.index("STALE") < content.index("100 W")
    assert text_roles(cells, bar_row, GPU_REGION, "STALE") == {"text"}


def test_ambiguous_index_does_not_create_a_gpu_group_boundary():
    sample = StateSnapshot((gpu(1, uuid=UUIDS[0]), gpu(1), gpu(2)))
    config = AppConfig(models=(model("A", ("1",)), model("B", ("2",))))
    cells = hardware_cells(sample, config, REGIONS, gpu_slots=UUIDS[:3])
    assert [cell.text for cell in cells if cell.text.startswith("GPU ")] == ["GPU 2"]


def test_uuid_assignments_survive_reused_index_without_ambiguous_group_titles():
    sample = StateSnapshot((gpu(1, uuid=UUIDS[0], stale=True), gpu(1), gpu(2)))
    config = AppConfig(models=tuple(model(str(index), (uuid,)) for index, uuid in enumerate(UUIDS[:3])))
    for selected, uuid in enumerate(UUIDS[:3]):
        view = ViewSelection(str(selected))
        assert linked_gpu_ids(sample, config, view) == (uuid,)
        cells = hardware_cells(sample, config, REGIONS, gpu_slots=UUIDS[:3], view=view)
        assert [cell.text for cell in cells if cell.text.startswith("GPU ")] == ["GPU 2"]
        rows = device_rows(cells)
        assert len(rows) == 3
        group = line(cells, rows[2] - 2, GPU_REGION)
        assert group.startswith("  GPU 2 ") and group.endswith(" TP 1  ")
        for slot, index in enumerate((1, 1, 2)):
            assert text_roles(cells, rows[slot], GPU_REGION, f"[{index}]") == {
                "primary" if slot == selected else "muted"
            }


def test_gpu_unknown_field_keeps_other_fields_and_failure_reuses_fixed_slot():
    sample = StateSnapshot((gpu(0, stale=True, temperature=None),))
    cells = hardware_cells(sample, configured(), REGIONS, gpu_slots=(UUIDS[0],))
    header_row = GPU_REGION.row + 1
    assert "STALE" in line(cells, header_row + 2, GPU_REGION)
    assert "—" in line(cells, header_row, GPU_REGION)
    assert "1.0 / 16.0 GiB" in line(cells, header_row, GPU_REGION)
    assert "100 W" in line(cells, header_row + 1, GPU_REGION)
    assert all(cell.row == header_row + 2 and cell.column == GPU_REGION.column + GPU_REGION.width - 7
               for cell in cells if cell.text == "STALE")
    assert not any("last" in cell.text.lower() or "error" in cell.text.lower() for cell in cells)
    assert_contained(cells)


def test_unsupported_gpu_field_is_unknown_without_stale_or_zero_substitution():
    cells = hardware_cells(StateSnapshot((gpu(0, temperature=None),)), AppConfig(),
                           REGIONS, gpu_slots=(UUIDS[0],))
    details = line(cells, 3, GPU_REGION)
    assert "—" in details and "1.0 / 16.0 GiB" in details and "100 W" in line(cells, 4, GPU_REGION)
    assert "STALE" not in line(cells, 3, GPU_REGION)
    assert "0°C" not in details and "0 °C" not in details


def test_gpu_name_is_clipped_without_losing_number_or_status_and_unknown_index_is_not_uuid():
    known = gpu(0, stale=True, name="界" * 100)
    unknown = replace(gpu(1), metrics=tuple(replace(metric, value=None) if metric.name == "index" else metric
                                           for metric in gpu(1).metrics))
    cells = hardware_cells(StateSnapshot((known, unknown)), configured(), REGIONS, gpu_slots=UUIDS[:2])
    assert "[0]" in line(cells, 3, GPU_REGION) and "STALE" in line(cells, 5, GPU_REGION)
    assert "[—]" in line(cells, 6, GPU_REGION)
    assert UUIDS[1] not in "".join(cell.text for cell in cells)
    assert_contained(cells)


@pytest.mark.parametrize("cpu_stale,ram_stale", [(False, False), (True, False), (False, True)])
def test_host_fields_are_named_and_ram_capacity_colors_are_separate(cpu_stale, ram_stale):
    # Reverse object and metric order so the view cannot mistake RAM bytes for CPU.
    cpu, ram = host_objects(cpu_stale=cpu_stale, ram_stale=ram_stale)
    sample = StateSnapshot((replace(ram, metrics=tuple(reversed(ram.metrics))), cpu))
    cells = hardware_cells(sample, AppConfig(mount_points=()), REGIONS, gpu_slots=())
    assert "CPU" in line(cells, 3, HOST_REGION) and "25.0%" in line(cells, 3, HOST_REGION)
    assert "RAM" in line(cells, 5, HOST_REGION) and "4 / 16 GiB" in line(cells, 5, HOST_REGION)
    assert text_roles(cells, 4, HOST_REGION, "▌") == {"secondary"}
    assert text_roles(cells, 6, HOST_REGION, "▌") == {"secondary"}
    assert text_roles(cells, 5, HOST_REGION, "4") == {"muted"}
    assert text_roles(cells, 5, HOST_REGION, "16") == {"text"}
    assert text_roles(cells, 5, HOST_REGION, "GiB") == {"muted"}
    assert text_roles(cells, 3, HOST_REGION, "25.0") == {"text"}
    assert text_roles(cells, 3, HOST_REGION, "%") == {"muted"}
    assert ("STALE" in line(cells, HOST_REGION.row, HOST_REGION)) == (cpu_stale or ram_stale)
    assert_contained(cells)


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_storage_has_three_content_rows_with_ordered_numbered_identity(count):
    paths = ("/", "/data", "/cache")[:count]
    cells = hardware_cells(StateSnapshot(tuple(mount(index) for index in range(count))),
                           configured(paths), REGIONS, gpu_slots=())
    storage_cells = tuple(cell for cell in cells if STORAGE_REGION.column <= cell.column
                          and STORAGE_REGION.row <= cell.row < STORAGE_REGION.row + STORAGE_REGION.height)
    assert all(10 <= cell.row <= 12 or cell.row == STORAGE_REGION.row and not cell.text.strip()
               for cell in storage_cells)
    if not count:
        assert any("No mount points configured" in cell.text and cell.role == "text"
                   for cell in storage_cells)
    for index, path in enumerate(paths):
        row = line(cells, 10 + index, STORAGE_REGION)
        assert path in row and "1 / 4 GiB · 25.0%" in row
    for unused in range(count or 1, 3):
        assert not line(cells, 10 + unused, STORAGE_REGION).strip()
    assert_contained(cells)


def test_storage_long_path_reserves_capacity_percent_and_heading_state_without_fourth_item_replacement():
    long_path = "/very-long-mount-" + "segment" * 30
    config = configured((long_path, "/data", "/cache", "/DO-NOT-SHOW"))
    sample = StateSnapshot((mount(0, stale=True), mount(1), mount(2), mount(3, used=3 * GIB)))
    cells = hardware_cells(sample, config, REGIONS, gpu_slots=())
    first = line(cells, 10, STORAGE_REGION)
    assert "/very" in first and "1 / 4 GiB" in first and "25.0%" in first
    assert "STALE" not in first
    assert "STALE" in line(cells, STORAGE_REGION.row, STORAGE_REGION)
    assert "/data" in line(cells, 11, STORAGE_REGION) and "/cache" in line(cells, 12, STORAGE_REGION)
    assert "DO-NOT-SHOW" not in "".join(cell.text for cell in cells)
    assert_contained(cells)


def test_numbered_storage_identity_wins_over_legacy_path_fixture():
    legacy = replace(mount(0, used=3 * GIB), key=ObjectKey("storage", "/"))
    cells = hardware_cells(StateSnapshot((legacy, mount(0))), configured(("/",)), REGIONS, gpu_slots=())
    row = line(cells, 10, STORAGE_REGION)
    assert "1 / 4 GiB" in row and "25.0%" in row and "3 / 4 GiB" not in row and "75.0%" not in row


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
    assert "[0]" in line(cells, 3, GPU_REGION) and "STALE" in line(cells, 5, GPU_REGION)
    assert "No NVIDIA GPUs" not in "".join(cell.text for cell in cells)


def test_compose_frame_integrates_named_hardware_values_without_generic_metric_dump():
    sample = StateSnapshot((inventory(1, sampled_at=1.0), gpu(0), *host_objects(), mount(0)))
    frame = compose_frame(sample, configured(("/",)), TerminalSize(120, 44),
                          HostInfo("offline-host", "Ubuntu"), NOW, gpu_slots=(UUIDS[0],))
    combined = "".join(cell.text for cell in frame.cells)
    assert "[0]" in combined and "Device-0" in combined and "25%" in combined
    assert "▌" in combined and "4 / 16 GiB" in combined
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
        rows = device_rows(frame.cells, region)
        assert len(rows) == 5
        for index, row in enumerate(rows):
            assert f"[{index}]" in line(frame.cells, row, region)
        assert "987654321" not in "".join(cell.text for cell in frame.cells)
    gpu_area = next(region for region in frames[1].regions if region.name == "gpu")
    storage = next(region for region in frames[1].regions if region.name == "storage")
    gpu2 = device_rows(frames[1].cells, gpu_area)[2]
    assert "STALE" in line(frames[1].cells, gpu2 + 1, gpu_area)
    assert "STALE" in line(frames[1].cells, storage.row, storage)
    assert not any(cell.text == "STALE" for cell in frames[2].cells)
    assert (normal, failed, config) == (normal_before, failed_before, config_before)
