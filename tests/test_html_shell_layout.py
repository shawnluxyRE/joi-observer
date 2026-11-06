"""Header, panel chrome and Docker rows through the public frame boundary.

Inputs are immutable snapshots and local wall times. No collection, terminal,
subprocess or network operation is needed to verify these character contracts.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unicodedata

import pytest

from joi_observer.config import AppConfig, ContainerConfig
from joi_observer.data.models import Metric, ObjectKey, ObjectSnapshot, StateSnapshot
from joi_observer.tui.layout import HostInfo, TerminalSize, ViewSelection, compose_frame


THEMES = ("hologram", "moonlight")
NOW = datetime(2026, 11, 4, 12, 34, 56, tzinfo=timezone(timedelta(hours=8)))
HOST = HostInfo("H3C R5300 G6", "Ubuntu 24.04")
STATES = ("Created", "Running", "Paused", "Restarting", "Removing", "Exited", "Dead")


def width(text):
    return sum(0 if unicodedata.combining(char) else
               2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def pixels(cells):
    result = {}
    for cell in cells:
        column = cell.column
        for char in cell.text:
            count = width(char)
            if not count:
                continue
            result[cell.row, column] = (char, cell.role)
            for offset in range(1, count):
                result[cell.row, column + offset] = (" ", cell.role)
            column += count
    return result


def segment(frame, row, start, end):
    grid = pixels(frame.cells)
    return "".join(grid.get((row, column), (" ", "text"))[0] for column in range(start, end))


def draw(*, theme="hologram", columns=120, height=44, config=None, snapshot=None, host=HOST, now=NOW):
    return compose_frame(snapshot if snapshot is not None else StateSnapshot(()),
                         config if config is not None else AppConfig(mount_points=()),
                         TerminalSize(columns, height), host, now,
                         view=ViewSelection(theme=theme), monotonic_now=100)


@pytest.mark.parametrize("columns", (120, 121, 160))
@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("height,host_row", [(40, 1), (41, 4)])
def test_header_theme_and_local_clock_share_the_right_edge_and_roles(columns, theme, height, host_row):
    frame = draw(theme=theme, columns=columns, height=height)
    label = f"Theme: {theme.title()} [t]"
    assert segment(frame, 0, columns - len(label), columns) == label
    assert segment(frame, host_row, columns - 19, columns) == "2026-11-04 12:34:56"
    grid = pixels(frame.cells)
    assert {grid[0, columns - len(label) + index][1] for index, char in enumerate(label)
            if not char.isspace()} == {"primary"}
    assert {grid[host_row, columns - 19 + index][1] for index, char in enumerate("2026-11-04 12:34:56")
            if not char.isspace()} == {"muted"}
    if host_row == 1:
        assert segment(frame, 0, 0, 13) == "Joi::Observer"
        for start, end, role in ((0, 3, "secondary"), (3, 5, "muted"), (5, 13, "primary")):
            assert {grid[0, column][1] for column in range(start, end)} == {role}
    else:
        assert grid[0, 1] == ("▀", "secondary")
        assert grid[1, 14] == grid[1, 16] == ("▀", "muted")
        assert grid[0, 18] == ("▄", "primary")
        assert grid[3, 1] == ("╶", "brand_shadow")
    host_text = "H3C R5300 G6 / Ubuntu 24.04"
    assert segment(frame, host_row, 0, len(host_text)) == host_text
    assert {grid[host_row, column][1] for column in range(len(HOST.hostname))} == {"text"}
    assert grid[host_row, len(HOST.hostname) + 1] == ("/", "muted")
    assert {grid[host_row, len(HOST.hostname) + 3 + index][1] for index, char in enumerate("Ubuntu 24.04")
            if not char.isspace()} == {"muted"}
    assert segment(frame, host_row, columns - 21, columns - 19) == "  "
    assert next(region for region in frame.regions if region.name == "header").height == host_row + 2
    assert [grid[host_row + 1, column] for column in range(columns)] == [("─", "muted")] * columns
    assert all(token not in " ".join(cell.text for cell in frame.cells)
               for token in ("CST", "UTC", "Details", "Pause", "NEON GRID"))


@pytest.mark.parametrize("offset", (8, -5.5))
def test_clock_uses_supplied_aware_local_time_without_utc_conversion(offset):
    local = datetime(2026, 11, 4, 0, 1, 2, tzinfo=timezone(timedelta(hours=offset)))
    frame = draw(now=local)
    assert segment(frame, 4, 101, 120) == "2026-11-04 00:01:02"
    assert local.strftime("%Y-%m-%d %H:%M:%S") != local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@pytest.mark.parametrize("host", (
    HostInfo("界e\u0301" * 100, "Ubuntu"),
    HostInfo("node", "界e\u0301" * 100),
    HostInfo("node\x1b[7m\n\r\u202e", "Ubuntu\x1b[0m\u2066\u2028\u2029" + "界" * 100),
), ids=("wide-hostname", "wide-system", "terminal-and-bidi-controls"))
@pytest.mark.parametrize("columns", (120, 161))
def test_long_host_fields_preserve_clock_gap_and_strip_terminal_controls(host, columns):
    frame = draw(host=host, columns=columns)
    clock = "2026-11-04 12:34:56"
    assert segment(frame, 4, columns - 19, columns) == clock
    assert segment(frame, 4, columns - 21, columns - 19) == "  "
    for cell in frame.cells:
        assert all(not unicodedata.category(char).startswith("C")
                   and char not in "\u2028\u2029" for char in cell.text)
        if cell.row == 4 and cell.text != clock:
            assert cell.column + width(cell.text) <= columns - 21
    # Text cannot activate reverse-video or alter the meaning of the clock.
    assert "\x1b" not in "".join(cell.text for cell in frame.cells)


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("height", (36, 37, 48))
def test_all_panel_titles_and_outer_borders_have_explicit_roles_without_extra_rows(theme, height):
    frame = draw(theme=theme, height=height)
    grid = pixels(frame.cells)
    areas = {region.name: region for region in frame.regions}
    for name, title, role in (("gpu", "GPU", "primary"), ("host", "Host Resources", "secondary"),
                               ("storage", "Storage", "secondary"), ("docker", "Docker", "secondary"),
                               ("service", "vLLM", "secondary")):
        area = areas[name]
        headings = [cell for cell in frame.cells if cell.row == area.row and cell.text == f" {title} "]
        assert len(headings) == 1 and headings[0].role == role
        assert headings[0].column == area.column + 2
        for row, column, char in ((area.row, area.column, "┌"),
                                  (area.row, area.column + area.width - 1, "┐"),
                                  (area.row + area.height - 1, area.column, "└"),
                                  (area.row + area.height - 1, area.column + area.width - 1, "┘")):
            assert grid[row, column] == (char, "muted")
    assert areas["service"].row == height - height // 2
    assert sum(areas[name].height for name in ("service", "service_switch", "footer")) == height // 2


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("columns", (120, 161))
def test_all_docker_lifecycle_unknown_and_stale_values_end_at_the_same_reserved_edge(theme, columns):
    cases = [(state, False, 100, state, "primary" if state == "Running" else "text")
             for state in STATES]
    cases += [(None, False, None, "—", "text"), ("Running", True, 100, "STALE", "text"),
              ("Running", False, None, "Running", "text")]
    config = AppConfig(mount_points=(), containers=tuple(ContainerConfig(f"c{index}", f"Container-{index}")
                                                        for index in range(len(cases))))
    objects = tuple(ObjectSnapshot(ObjectKey("docker", f"c{index}"),
                                   () if state is None else (Metric("state", state),), stale, sampled_at)
                    for index, (state, stale, sampled_at, _, _) in enumerate(cases))
    data = StateSnapshot(objects, 4)
    before = deepcopy((config, data))
    # At this height ten Docker content rows fit below the full header.
    frame = draw(theme=theme, columns=columns, height=62, config=config, snapshot=data)
    area = next(region for region in frame.regions if region.name == "docker")
    right = area.column + area.width - 2
    for index, (_, _, _, expected, role) in enumerate(cases):
        row = area.row + 2 + index
        assert segment(frame, row, right - len(expected), right) == expected
        assert segment(frame, row, right - 14, right - len(expected)).strip() == ""
        assert segment(frame, row, right - 15, right - 14) == " "
        grid = pixels(frame.cells)
        assert {grid[row, column][1] for column in range(right - len(expected), right)} == {role}
        names = [cell for cell in frame.cells if cell.row == row and cell.text == f"Container-{index}"]
        assert len(names) == 1 and names[0].column == area.column + 2
        assert names[0].column + width(names[0].text) <= right - 15
    assert not any(cell.role == "amber" for cell in frame.cells)
    assert (config, data) == before


@pytest.mark.parametrize("columns", (120, 121, 160))
def test_docker_long_unicode_name_keeps_fixed_slot_across_failure_and_recovery(columns):
    config = AppConfig(mount_points=(), containers=(ContainerConfig("c", "界e\u0301" * 100),))
    healthy = ObjectSnapshot(ObjectKey("docker", "c"), (Metric("state", "Restarting"),), sampled_at=100)
    frames = [draw(columns=columns, config=config, snapshot=StateSnapshot((item,)))
              for item in (healthy, replace(healthy, stale=True), healthy)]
    assert frames[0] == frames[2]
    assert frames[0].regions == frames[1].regions
    area = next(region for region in frames[0].regions if region.name == "docker")
    row, right = area.row + 2, area.column + area.width - 2
    for frame, state in zip(frames, ("Restarting", "STALE", "Restarting")):
        assert segment(frame, row, right - len(state), right) == state
        names = [cell for cell in frame.cells if cell.row == row and cell.column == area.column + 2]
        assert len(names) == 1 and names[0].column + width(names[0].text) <= right - 15
    assert segment(frames[0], row, area.column + 2, right - 15) == segment(
        frames[1], row, area.column + 2, right - 15)


@pytest.mark.parametrize("height,count,capacity", (
    (36, 0, 0), (36, 10, 0), (37, 0, 1), (37, 10, 1),
    (40, 10, 2), (41, 0, 0), (41, 10, 0), (43, 0, 1), (48, 10, 3),
))
def test_shell_changes_preserve_docker_capacity_empty_state_and_configuration(height, count, capacity):
    config = AppConfig(mount_points=(), containers=tuple(ContainerConfig(f"c{i}", f"Container-{i}")
                                                        for i in range(count)))
    before = deepcopy(config)
    frame = draw(height=height, config=config)
    names = [cell.text for cell in frame.cells if cell.text.startswith("Container-")]
    assert names == [f"Container-{index}" for index in range(min(count, capacity))]
    empty = [cell for cell in frame.cells if cell.text == "No containers configured"]
    assert bool(empty) is (count == 0 and capacity > 0)
    assert config == before and frame.minimum_size == TerminalSize(120, 36)
    assert not frame.too_small
