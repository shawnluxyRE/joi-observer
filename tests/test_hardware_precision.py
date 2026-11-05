"""Presentation precision changes preserve raw values, roles and public helpers."""

from copy import deepcopy
from dataclasses import replace

import pytest

from joi_observer.data.models import StateSnapshot
from joi_observer.tui.widgets import capacity_text, hardware_cells, percentage_bar
from test_hardware_view import GIB, TIB, REGIONS, UUIDS, configured, gpu, host_objects, mount, pixels


def rendered(*objects):
    return hardware_cells(StateSnapshot(objects), configured(("/",)), REGIONS, gpu_slots=(UUIDS[0],))


def text(cells, row, start, end):
    grid = pixels(cells)
    return "".join(grid.get((row, column), (" ", "text"))[0] for column in range(start, end))


@pytest.mark.parametrize("used,total,expected", (
    (0, 16 * GIB, "0 / 16 GiB"),
    (None, 16 * GIB, "— / 16 GiB"),
    (4 * GIB, None, "4 / — GiB"),
    (None, None, "— / —"),
    (GIB // 2 - 1, 4 * GIB, "0 / 4 GiB"),
    (GIB // 2, 4 * GIB, "1 / 4 GiB"),
    (149 * GIB // 100, 4 * GIB, "1 / 4 GiB"),
    (3 * GIB // 2 - 1, 4 * GIB, "1 / 4 GiB"),
    (3 * GIB // 2, 4 * GIB, "2 / 4 GiB"),
    (GIB, 149 * GIB // 100, "1 / 1 GiB"),
    (TIB // 2 - 1, 4 * TIB, "0 / 4 TiB"),
    (TIB // 2, 4 * TIB, "1 / 4 TiB"),
    (149 * TIB // 100, 4 * TIB, "1 / 4 TiB"),
    (3 * TIB // 2 - 1, 4 * TIB, "1 / 4 TiB"),
    (3 * TIB // 2, 4 * TIB, "2 / 4 TiB"),
    (TIB, 149 * TIB // 100, "1 / 1 TiB"),
    (None, 3 * TIB // 2, "— / 2 TiB"),
    (3 * TIB // 2, None, "2 / — TiB"),
    ((10**29 + 7) * TIB + TIB // 2 - 1, None, str(10**29 + 7) + " / — TiB"),
    ((10**29 + 7) * TIB + TIB // 2, None, str(10**29 + 8) + " / — TiB"),
))
def test_ram_rounds_raw_bytes_once_for_either_unit_without_adding_percentage(used, total, expected):
    ram = host_objects()[1]
    values = {"ram_used_bytes": used, "ram_total_bytes": total}
    ram = replace(ram, metrics=tuple(replace(metric, value=values[metric.name])
                                    if metric.name in values else metric for metric in ram.metrics))
    before = deepcopy(ram)
    cells = rendered(ram)
    assert text(cells, 5, 78, 118).strip() == expected
    assert "%" not in text(cells, 5, 74, 118) + text(cells, 6, 74, 118)
    assert ram == before


@pytest.mark.parametrize("percent,expected", (
    (0, "0.0%"), (-0.0, "0.0%"), (30, "30.0%"), (100, "100.0%"),
    (24.95, "25.0%"), (25.45, "25.5%"), (25.44, "25.4%"), (None, "—"),
))
def test_cpu_storage_fixed_decimal_preserves_rounding_roles_and_gpu_percent(percent, expected):
    cpu, disk, card = host_objects()[0], mount(0), gpu(0)
    objects = tuple(replace(obj, metrics=tuple(replace(metric, value=percent) if metric.name == field else metric
                                             for metric in obj.metrics))
                    for obj, field in ((cpu, "cpu_percent"), (disk, "used_percent"),
                                       (card, "utilization_percent")))
    before = deepcopy(objects)
    cells = rendered(*objects)
    assert text(cells, 3, 78, 118).strip() == expected
    assert text(cells, 10, 74, 118).endswith("1 / 4 GiB · " + expected)
    assert text(cells, 4, 36, 42).strip() == percentage_bar(percent, 33).text
    grid = pixels(cells)
    assert {grid[3, column][1] for column in range(118 - len(expected), 117 if percent is not None else 118)} == {"text"}
    if percent is not None:
        assert grid[3, 117][1] == "muted"
    assert {grid[10, column][1] for column in range(118 - len(expected), 118)} == {"text"}
    assert objects == before


def test_public_helpers_keep_original_precision_contracts():
    assert capacity_text(149 * TIB // 100, 4 * TIB) == ("1.5 TiB", "4.0 TiB")
    assert percentage_bar(30, 4).text == "30%"
    assert percentage_bar(24.95, 4).text == "25%"
