"""Hardware geometry matching the HTML hierarchy within terminal cell limits.

Only immutable inputs are supplied. Tests read real composition/widget cells;
collector behavior and existing formatting APIs are not replaced.
"""

from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import re

import pytest

from joi_observer.config import AppConfig
from joi_observer.data.models import Metric, ObjectKey, ObjectSnapshot, StateSnapshot
from joi_observer.tui.layout import HostInfo, Region, TerminalSize, ViewSelection, compose_frame
from joi_observer.tui.widgets import hardware_cells
from test_hardware_view import GIB, TIB, NOW, UUIDS, configured, gpu, host_objects, mount, pixels


def regions_for(gpu_width=71, right_column=72, right_width=48):
    return (Region("gpu", 2, 0, gpu_width, 20),
            Region("host", 2, right_column, right_width, 6),
            Region("storage", 8, right_column, right_width, 6))


def draw(sample, config=None, *, regions=None):
    return hardware_cells(sample, config or AppConfig(mount_points=("/",)), regions or regions_for(),
                          gpu_slots=(UUIDS[0],), view=ViewSelection("A", "hologram"))


def text_at(cells, row, start, end):
    grid = pixels(cells)
    return "".join(grid.get((row, column), (" ", "text"))[0] for column in range(start, end))


def assert_right_aligned(cells, row, text, end, role=None):
    assert text_at(cells, row, end - len(text), end) == text
    if role is not None:
        grid = pixels(cells)
        assert {grid[row, column][1] for column in range(end - len(text), end)} == {role}


def assert_roles(cells, row, start, end, role):
    """Whitespace has no visible foreground; inspect every nonblank glyph."""
    grid = pixels(cells)
    visible = [grid[row, column] for column in range(start, end)
               if (row, column) in grid and grid[row, column][0].strip()]
    assert visible and {style for _, style in visible} == {role}


def assert_no_overlaps(cells):
    occupied = set()
    for cell in cells:
        positions = set(pixels((cell,)))
        assert not positions.intersection(occupied), cell
        occupied.update(positions)


@pytest.mark.parametrize("columns,gpu_width,right_column,right_width", (
    (120, 71, 72, 48), (121, 72, 73, 48), (160, 95, 96, 64),
))
def test_top_regions_use_three_to_two_columns_and_six_line_host(columns, gpu_width, right_column, right_width):
    frame = compose_frame(StateSnapshot(()), AppConfig(), TerminalSize(columns, 44),
                          HostInfo("offline", "Ubuntu"), NOW, gpu_slots=(UUIDS[0],))
    areas = {region.name: region for region in frame.regions}
    assert areas["gpu"] == Region("gpu", 6, 0, gpu_width, 16)
    assert areas["host"] == Region("host", 6, right_column, right_width, 6)
    assert areas["storage"] == Region("storage", 12, right_column, right_width, 6)
    assert areas["docker"] == Region("docker", 18, right_column, right_width, 4)
    assert areas["service"].row == 22
    assert frame.minimum_size == TerminalSize(120, 36)


@pytest.mark.parametrize("gpu_width,right_column,right_width,bar_width", (
    (71, 72, 48, 33), (72, 73, 48, 34), (95, 96, 64, 45),
))
@pytest.mark.parametrize("stale", (False, True))
def test_gpu_memory_temperature_power_and_status_keep_separate_right_edges(
    gpu_width, right_column, right_width, bar_width, stale,
):
    areas = regions_for(gpu_width, right_column, right_width)
    data = StateSnapshot((gpu(0, stale=stale),))
    cells = draw(data, regions=areas)
    right = gpu_width - 2
    assert text_at(cells, 3, 2, 6) == "[0] "
    assert "Device-0" in text_at(cells, 3, 6, right - 12)
    assert_right_aligned(cells, 3, "1.0 / 16.0 GiB", right - 12, "muted")
    assert_right_aligned(cells, 3, "60°C", right, "text")
    assert_right_aligned(cells, 4, "100 W", right, "muted")
    assert text_at(cells, 3, right - 12, right - 10) == "  "
    assert text_at(cells, 4, 2, 2 + bar_width) == "▌" * bar_width
    assert len(text_at(cells, 4, 2, 2 + bar_width)) == bar_width
    assert text_at(cells, 4, 2 + bar_width, 3 + bar_width) == " "
    assert text_at(cells, 4, 3 + bar_width, 6 + bar_width) == "25%"
    assert 6 + bar_width <= right - 10
    assert text_at(cells, 5, 2, right - 5).strip() == ""
    assert text_at(cells, 5, right - 5, right) == ("STALE" if stale else "     ")
    assert "STALE" not in text_at(cells, 3, 2, right)
    assert_no_overlaps(cells)


@pytest.mark.parametrize("used,total,expected", (
    (0, 16 * GIB, "0.0 / 16.0 GiB"),
    (None, 16 * GIB, "— / 16.0 GiB"),
    (4 * GIB, None, "4.0 / — GiB"),
    (None, None, "— / —"),
    (TIB // 2, TIB, "0.5 / 1.0 TiB"),
))
def test_gpu_compact_capacity_keeps_zero_unknown_and_shared_unit(used, total, expected):
    card = gpu(0)
    values = {"memory_used_bytes": used, "memory_total_bytes": total}
    card = replace(card, metrics=tuple(replace(metric, value=values[metric.name])
                                      if metric.name in values else metric for metric in card.metrics))
    cells = draw(StateSnapshot((card,)))
    assert_right_aligned(cells, 3, expected, 57, "muted")
    assert_no_overlaps(cells)


def test_gpu_wide_name_cannot_overwrite_memory_or_temperature_and_status_uses_third_line():
    card = gpu(0, name="界e\u0301" * 60, stale=True)
    data, config = StateSnapshot((card,)), configured(("/",))
    before = deepcopy((data, config))
    cells = draw(data, config)
    assert text_at(cells, 3, 2, 6) == "[0] "
    assert_right_aligned(cells, 3, "1.0 / 16.0 GiB", 57, "muted")
    assert text_at(cells, 3, 42, 43) == " "
    assert_right_aligned(cells, 3, "60°C", 69, "text")
    assert text_at(cells, 5, 64, 69) == "STALE"
    assert_no_overlaps(cells)
    assert (data, config) == before


@pytest.mark.parametrize("stale", (False, True))
def test_host_four_rows_keep_labels_values_and_bars_in_html_order(stale):
    data = StateSnapshot(host_objects(cpu_stale=stale))
    cells = draw(data)
    assert text_at(cells, 3, 74, 77) == "CPU"
    assert_right_aligned(cells, 3, "25.0%", 118)
    assert_roles(cells, 3, 113, 117, "text")
    assert_roles(cells, 3, 117, 118, "muted")
    assert text_at(cells, 4, 74, 96) == "▌" * 22
    assert text_at(cells, 4, 96, 118).strip() == ""
    assert text_at(cells, 5, 74, 77) == "RAM"
    assert_right_aligned(cells, 5, "4 / 16 GiB", 118)
    grid = pixels(cells)
    assert {grid[5, column][1] for column in range(108, 109)} == {"muted"}
    assert_roles(cells, 5, 109, 112, "muted")
    assert_roles(cells, 5, 112, 114, "text")
    assert_roles(cells, 5, 114, 118, "muted")
    assert text_at(cells, 6, 74, 96) == "▌" * 22
    assert text_at(cells, 6, 96, 118).strip() == ""
    for row in (4, 6):
        assert {grid[row, column][1] for column in range(74, 80)} == {"secondary"}
        assert {grid[row, column][1] for column in range(80, 96)} == {"track"}
    assert text_at(cells, 2, 113, 118) == ("STALE" if stale else "     ")
    assert_no_overlaps(cells)


@pytest.mark.parametrize("percent,used,total,cpu_text,ram_text", (
    (0, 0, 16 * GIB, "0.0%", "0 / 16 GiB"),
    (None, None, None, "—", "— / —"),
))
def test_host_unknown_and_zero_keep_empty_tracks_without_repeating_values(
    percent, used, total, cpu_text, ram_text,
):
    values = {"cpu_percent": percent, "ram_percent": percent,
              "ram_used_bytes": used, "ram_total_bytes": total}
    objects = tuple(replace(obj, metrics=tuple(replace(metric, value=values[metric.name])
                                             for metric in obj.metrics)) for obj in host_objects())
    cells = draw(StateSnapshot(objects))
    assert_right_aligned(cells, 3, cpu_text, 118)
    if percent is None:
        assert_roles(cells, 3, 117, 118, "text")
    else:
        assert_roles(cells, 3, 118 - len(cpu_text), 117, "text")
        assert_roles(cells, 3, 117, 118, "muted")
    assert_right_aligned(cells, 5, ram_text, 118)
    for row in (4, 6):
        assert text_at(cells, row, 74, 96) == "▌" * 22
        assert_roles(cells, row, 74, 96, "track")
        assert text_at(cells, row, 96, 118).strip() == ""
    assert_no_overlaps(cells)


@pytest.mark.parametrize("stale", (False, True))
def test_storage_numeric_group_ends_at_content_edge_and_status_is_in_heading(stale):
    cells = draw(StateSnapshot((mount(0, stale=stale),)), configured(("/data",)))
    assert text_at(cells, 10, 74, 79) == "/data"
    assert_right_aligned(cells, 10, "1 / 4 GiB · 25.0%", 118)
    assert_roles(cells, 10, 74, 79, "text")
    assert_roles(cells, 10, 101, 113, "muted")
    assert_roles(cells, 10, 113, 118, "text")
    assert text_at(cells, 8, 113, 118) == ("STALE" if stale else "     ")
    assert "STALE" not in text_at(cells, 10, 74, 118)
    assert_no_overlaps(cells)


def test_storage_long_unicode_path_is_clipped_before_numeric_group_without_shifting_values():
    config = configured(("/界" * 80, "/data", "/cache", "/ignored"))
    data = StateSnapshot((mount(0, stale=True), mount(1), mount(2)))
    cells = draw(data, config)
    for row in (10, 11, 12):
        assert_right_aligned(cells, row, "1 / 4 GiB · 25.0%", 118)
    assert text_at(cells, 8, 113, 118) == "STALE"
    assert "ignored" not in "".join(cell.text for cell in cells)
    assert_no_overlaps(cells)


def test_storage_unknown_values_keep_the_same_right_edge_and_clear_heading_status():
    unknown = replace(mount(0), metrics=tuple(replace(metric, value=None) for metric in mount(0).metrics))
    cells = draw(StateSnapshot((unknown,)), configured(("/",)))
    assert_right_aligned(cells, 10, "— / — · —", 118)
    assert_roles(cells, 10, 109, 117, "muted")
    assert_roles(cells, 10, 117, 118, "text")
    assert text_at(cells, 8, 113, 118) == " " * 5
    assert_no_overlaps(cells)


def test_legacy_generic_gpu_keeps_original_status_and_metric_rows():
    legacy = ObjectSnapshot(ObjectKey("gpu", "0"), (Metric("usage", 25, "%"),), stale=True)
    cells = hardware_cells(StateSnapshot((legacy,)), AppConfig(mount_points=()), regions_for(),
                           gpu_slots=("0",), view=ViewSelection())
    assert text_at(cells, 3, 2, 5) == "[0]"
    assert text_at(cells, 3, 64, 69) == "STALE"
    assert "usage: 25%" in text_at(cells, 4, 2, 69)


@pytest.mark.parametrize("temperature,power,temp_text,power_text", (
    (0, 0, "0°C", "0 W"), (None, None, "—", "—"),
    (123.5, 987.25, "123.5°C", "987.25 W"),
))
def test_temperature_and_power_keep_independent_roles_for_zero_unknown_and_multidigit_values(
    temperature, power, temp_text, power_text,
):
    card = gpu(0, temperature=temperature, stale=True)
    card = replace(card, metrics=tuple(replace(metric, value=power) if metric.name == "power_w" else metric
                                      for metric in card.metrics))
    cells = draw(StateSnapshot((card,)))
    assert_right_aligned(cells, 3, temp_text, 69, "text")
    assert_right_aligned(cells, 4, power_text, 69, "muted")
    assert_right_aligned(cells, 5, "STALE", 69, "text")
    assert_no_overlaps(cells)


@pytest.mark.parametrize("percent,expected", ((0, "0.0%"), (25.5, "25.5%"), (100, "100.0%"), (None, "—")))
def test_cpu_digits_and_percent_unit_are_not_the_bar_accent(percent, expected):
    cpu = host_objects()[0]
    cpu = replace(cpu, metrics=(Metric("cpu_percent", percent, "%"),))
    cells = draw(StateSnapshot((cpu,)))
    assert_right_aligned(cells, 3, expected, 118)
    start = 118 - len(expected)
    assert_roles(cells, 3, start, 118 if percent is None else 117, "text")
    if percent is not None:
        assert_roles(cells, 3, 117, 118, "muted")
    assert text_at(cells, 3, 74, 77) == "CPU"
    assert_no_overlaps(cells)


@pytest.mark.parametrize("used,total,left,right,unit", (
    (0, 16 * GIB, "0", "16", "GiB"),
    (None, 16 * GIB, "—", "16", "GiB"),
    (4 * GIB, None, "4", "—", "GiB"),
    (None, None, "—", "—", ""),
    (512 * GIB, TIB - 1, "512", "1024", "GiB"),
))
def test_ram_used_total_and_shared_unit_have_separate_roles(used, total, left, right, unit):
    ram = host_objects()[1]
    values = {"ram_used_bytes": used, "ram_total_bytes": total}
    ram = replace(ram, metrics=tuple(replace(metric, value=values[metric.name])
                                    if metric.name in values else metric for metric in ram.metrics))
    cells = draw(StateSnapshot((ram,)))
    value = left + " / " + right + (" " + unit if unit else "")
    assert_right_aligned(cells, 5, value, 118)
    start = 118 - len(value)
    total_start = start + len(left) + 3
    assert_roles(cells, 5, start, total_start, "muted")
    assert_roles(cells, 5, total_start, total_start + len(right), "text")
    if unit:
        assert_roles(cells, 5, 118 - len(unit), 118, "muted")
    assert_no_overlaps(cells)


@pytest.mark.parametrize("used,total,percent,value", (
    (0, 4 * GIB, 0, "0 / 4 GiB · 0.0%"),
    (None, None, None, "— / — · —"),
    (100 * GIB, 400 * GIB, 25, "100 / 400 GiB · 25.0%"),
))
def test_storage_shared_capacity_separator_percent_and_status_roles(used, total, percent, value):
    item = mount(0, stale=True)
    values = {"used_bytes": used, "total_bytes": total, "used_percent": percent}
    item = replace(item, metrics=tuple(replace(metric, value=values[metric.name]) for metric in item.metrics))
    cells = draw(StateSnapshot((item,)), configured(("/data",)))
    assert_right_aligned(cells, 10, value, 118)
    prefix, number = value.rsplit(" · ", 1)
    start = 118 - len(value)
    assert_roles(cells, 10, start, start + len(prefix) + 3, "muted")
    assert_roles(cells, 10, 118 - len(number), 118, "text")
    assert_roles(cells, 10, 74, 79, "text")
    assert_right_aligned(cells, 8, "STALE", 118, "text")
    assert_no_overlaps(cells)


def scientific_number(text):
    """Check a readable normalized number, without dictating exponent styling."""
    assert re.fullmatch(r"[1-9](?:\.\d{1,2})?[eE][+-]?\d+", text), text
    return Decimal(text)


def test_extreme_gpu_temperature_and_power_keep_exponent_units_and_right_hand_slots():
    card = gpu(0, temperature=1e300, stale=True)
    card = replace(card, metrics=tuple(replace(metric, value=1e300) if metric.name == "power_w" else metric
                                      for metric in card.metrics))
    data = StateSnapshot((card,))
    before = deepcopy(data)
    cells = draw(data)
    temperature = text_at(cells, 3, 59, 69).strip()
    power = text_at(cells, 4, 59, 69).strip()
    assert temperature.endswith("°C") and power.endswith(" W")
    assert scientific_number(temperature[:-2]).adjusted() == 300
    assert scientific_number(power[:-2]).adjusted() == 300
    assert_roles(cells, 3, 59, 69, "text")
    assert_roles(cells, 4, 59, 69, "muted")
    assert text_at(cells, 3, 2, 6) == "[0] "
    assert_right_aligned(cells, 3, "1.0 / 16.0 GiB", 57, "muted")
    assert_right_aligned(cells, 5, "STALE", 69, "text")
    assert_no_overlaps(cells)
    assert data == before


def test_extreme_capacity_groups_stay_readable_without_covering_identity_labels_or_status():
    huge = 10**5000
    values = {"memory_used_bytes": huge, "memory_total_bytes": 2 * huge}
    card = gpu(0, stale=True)
    card = replace(card, metrics=tuple(replace(metric, value=values[metric.name])
                                      if metric.name in values else metric for metric in card.metrics))
    ram = host_objects(ram_stale=True)[1]
    values = {"ram_used_bytes": huge, "ram_total_bytes": 2 * huge, "ram_percent": 50}
    ram = replace(ram, metrics=tuple(replace(metric, value=values[metric.name]) for metric in ram.metrics))
    disk = mount(0, stale=True)
    values = {"used_bytes": huge, "total_bytes": 2 * huge, "used_percent": 50}
    disk = replace(disk, metrics=tuple(replace(metric, value=values[metric.name]) for metric in disk.metrics))
    data = StateSnapshot((card, ram, disk))
    before = deepcopy(data)
    cells = draw(data, configured(("/",)))
    gpu_group = text_at(cells, 3, 14, 57).strip()
    # The GPU name may occupy unused space to the left of the value group.
    number = r"[1-9](?:\.\d{1,2})?[eE][+-]?\d+"
    capacity = re.search(rf"({number} / {number} TiB)$", gpu_group)
    assert capacity is not None, gpu_group
    gpu_group = capacity.group(1)
    ram_group = text_at(cells, 5, 78, 118).strip()
    storage_group = text_at(cells, 10, 76, 118).strip()
    assert storage_group.endswith(" · 50.0%")
    storage_capacity = storage_group.removesuffix(" · 50.0%")
    for group in (gpu_group, ram_group, storage_capacity):
        assert group.endswith(" TiB")
        used, total = group.removesuffix(" TiB").split(" / ")
        assert scientific_number(used).adjusted() == 4987
        assert scientific_number(total).adjusted() == 4988
        assert "…" not in group and "—" not in group and "N/A" not in group
    assert text_at(cells, 3, 2, 6) == "[0] "
    assert text_at(cells, 5, 74, 77) == "RAM"
    assert text_at(cells, 10, 74, 75) == "/"
    assert_right_aligned(cells, 5, "STALE", 69, "text")
    assert_right_aligned(cells, 2, "STALE", 118, "text")
    assert_right_aligned(cells, 8, "STALE", 118, "text")
    assert_no_overlaps(cells)
    assert data == before
