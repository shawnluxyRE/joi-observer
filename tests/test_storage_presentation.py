"""Storage GUI feedback: one heading status, full-width values and integer GiB."""

from copy import deepcopy
from dataclasses import replace

import pytest

from joi_observer.data.models import StateSnapshot
from joi_observer.tui.widgets import capacity_text, hardware_cells
from test_hardware_view import GIB, TIB, REGIONS, STORAGE_REGION, configured, mount, pixels


def draw(objects, mounts=("/", "/data", "/cache", "/ignored")):
    return hardware_cells(StateSnapshot(tuple(objects)), configured(mounts), REGIONS, gpu_slots=())


def row_text(cells, row, start=74, end=118):
    grid = pixels(cells)
    return "".join(grid.get((row, column), (" ", "text"))[0] for column in range(start, end))


@pytest.mark.parametrize("failed", ((), (0,), (1,), (2,), (0, 1, 2), (3,)))
def test_only_first_three_configured_mounts_contribute_to_one_heading_status(failed):
    objects = tuple(mount(index, stale=index in failed) for index in range(4))
    before = deepcopy(objects)
    cells = draw(objects)
    status = [cell for cell in cells if cell.text == "STALE"]
    assert len(status) == int(any(index < 3 for index in failed))
    if status:
        assert (status[0].row, status[0].column, status[0].role) == (8, 113, "text")
    for row in (10, 11, 12):
        assert row_text(cells, row).endswith("1 / 4 GiB · 25.0%")
        assert "STALE" not in row_text(cells, row)
    assert objects == before


def test_storage_heading_recovers_without_moving_or_changing_numeric_rows():
    healthy = tuple(mount(index) for index in range(3))
    frames = [draw(objects) for objects in (healthy,
              tuple(replace(obj, stale=True) for obj in healthy), healthy)]
    assert frames[0] == frames[2]
    assert row_text(frames[1], STORAGE_REGION.row).endswith("STALE")
    for row in (10, 11, 12):
        assert row_text(frames[0], row) == row_text(frames[1], row) == row_text(frames[2], row)


@pytest.mark.parametrize("used,total,expected", (
    (0, 4 * GIB, "0 / 4 GiB"),
    (GIB // 2 - 1, 4 * GIB, "0 / 4 GiB"),
    (GIB // 2, 4 * GIB, "1 / 4 GiB"),
    (149 * GIB // 100, 4 * GIB, "1 / 4 GiB"),
    (3 * GIB // 2 - 1, 4 * GIB, "1 / 4 GiB"),
    (3 * GIB // 2, 4 * GIB, "2 / 4 GiB"),
    (GIB, 149 * GIB // 100, "1 / 1 GiB"),
    (None, 4 * GIB, "— / 4 GiB"),
    (3 * GIB // 2, None, "2 / — GiB"),
    (None, None, "— / —"),
    (TIB // 2, TIB, "0.5 / 1.0 TiB"),
    (512 * GIB, TIB - 1, "512 / 1024 GiB"),
))
def test_storage_rounds_gib_directly_from_bytes_and_preserves_tib_unknown_and_zero(used, total, expected):
    source = mount(0)
    values = {"used_bytes": used, "total_bytes": total, "used_percent": None}
    source = replace(source, metrics=tuple(replace(metric, value=values[metric.name]) for metric in source.metrics))
    cells = draw((source,), ("/",))
    assert row_text(cells, 10).endswith(expected + " · —")
    assert row_text(cells, 10).startswith("/")


def test_storage_integer_display_does_not_change_public_capacity_formatter():
    assert capacity_text(149 * GIB // 100, 4 * GIB) == ("1.5 GiB", "4.0 GiB")
