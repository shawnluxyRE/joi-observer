"""Theme presentation contracts through public, immutable view inputs.

These tests exercise real composition and session actions. The snapshots model
the read-only display boundary; no collector, process or remote service runs.
Palette installation and actual terminal color output are covered separately.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import unicodedata

import pytest

from joi_observer.config import AppConfig, ContainerConfig, ModelConfig, ModelType
from joi_observer.data.models import HistoryPoint, Metric, ObjectKey, ObjectSnapshot, StateSnapshot
from joi_observer.tui.layout import HostInfo, TerminalSize, ViewSelection, compose_frame
from joi_observer.tui.navigation import SessionViewActions


NOW = datetime(2026, 11, 4, 11, 0, tzinfo=timezone.utc)
HOST = HostInfo("offline", "Ubuntu 24.04")
UUIDS = tuple(f"GPU-00000000-0000-0000-0000-{index:012d}" for index in range(2))
THEMES = ("hologram", "moonlight")
GIB = 2**30


def configured(*, long_names=False):
    return AppConfig(
        mount_points=("/", "/data", "/cache"),
        containers=tuple(ContainerConfig(f"c{i}", "Container-" + ("界" * 60 if long_names else str(i)))
                         for i in range(8)),
        models=tuple(ModelConfig(kind.value, kind, "Model-" + ("界" * 60 if long_names else kind.value),
                                 f"http://offline.invalid:{8000 + index}", (UUIDS[index],) if index < 2 else ())
                     for index, kind in enumerate(ModelType)),
    )


def snapshot(*, waiting=0, stale=False, sampled_at=100.0, long_names=False):
    objects = []
    for index, identifier in enumerate(UUIDS):
        objects.append(ObjectSnapshot(ObjectKey("gpu", identifier), (
            Metric("index", index), Metric("name", "Device-" + ("界" * 60 if long_names else str(index))),
            Metric("utilization_percent", 50, "%"), Metric("memory_used_bytes", 4 * GIB, "B"),
            Metric("memory_total_bytes", 16 * GIB, "B"), Metric("temperature_c", 60, "°C"),
            Metric("power_w", 120, "W"),
        ), stale=stale, sampled_at=sampled_at))
    objects.extend((
        ObjectSnapshot(ObjectKey("host", "cpu"), (Metric("cpu_percent", 50, "%"),),
                       stale=stale, sampled_at=sampled_at),
        ObjectSnapshot(ObjectKey("host", "ram"), (
            Metric("ram_percent", 25, "%"), Metric("ram_used_bytes", 4 * GIB, "B"),
            Metric("ram_total_bytes", 16 * GIB, "B"),
        ), stale=stale, sampled_at=sampled_at),
    ))
    objects.extend(ObjectSnapshot(ObjectKey("storage", f"mount-{i}"), (
        Metric("used_bytes", GIB, "B"), Metric("total_bytes", 4 * GIB, "B"),
        Metric("used_percent", 25, "%"),
    ), stale=stale, sampled_at=sampled_at) for i in range(3))
    objects.extend(ObjectSnapshot(ObjectKey("docker", f"c{i}"),
                                  (Metric("state", "Exited" if i % 2 else "Restarting"),),
                                  stale=stale, sampled_at=sampled_at) for i in range(8))
    for kind in ModelType:
        chat = kind == ModelType.CHAT
        metrics = (
            Metric("running", 3, "seq"), Metric("waiting", waiting, "seq"),
            Metric("total", 3 + waiting if waiting is not None else None, "seq"),
            Metric("decode_rate", 100 if chat else None, "tok/s", chat),
            Metric("prefill_rate", 500 if chat else None, "tok/s", chat),
            Metric("rate", None if chat else 3, "seq/s", not chat),
            Metric("ttft_seconds", 0.2 if chat else None, "s", chat),
            Metric("queue_seconds", 0.5, "s"),
            Metric("latency_seconds", None if chat else 0.4, "s", not chat),
            Metric("kv_cache_percent", 20 if chat else None, "%", chat),
        )
        rate = "decode_rate" if chat else "rate"
        unit = "tok/s" if chat else "seq/s"
        history = (HistoryPoint(90.0, (Metric(rate, 1, unit),)), HistoryPoint(95.0, None),
                   HistoryPoint(100.0, (Metric(rate, 2, unit),)))
        objects.append(ObjectSnapshot(ObjectKey("vllm", kind.value), metrics, stale, sampled_at, history))
    return StateSnapshot(tuple(objects), revision=17)


def draw(data=None, config=None, *, theme="hologram", model_id="chat", size=TerminalSize(120, 44),
         history_scales=None):
    return compose_frame(data if data is not None else snapshot(), config or configured(), size, HOST, NOW,
                         gpu_slots=UUIDS, view=ViewSelection(model_id, theme), monotonic_now=100.0,
                         history_scales=history_scales)


def regions(frame):
    return {region.name: region for region in frame.regions}


def cells_in(frame, name):
    area = regions(frame)[name]
    return tuple(cell for cell in frame.cells
                 if area.row <= cell.row < area.row + area.height
                 and area.column <= cell.column < area.column + area.width)


def width(text):
    return sum(0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in "WF" else 1
               for char in text)


def plot(frame):
    area = regions(frame)["service"]
    return tuple(cell for cell in frame.cells if area.column + 30 <= cell.column < area.column + area.width - 2
                 and area.row + 13 <= cell.row <= area.row + area.height - 3)


def row_text(cells, row):
    """Compose one public row by terminal columns without depending on chunks."""
    pixels = {}
    for cell in cells:
        if cell.row != row:
            continue
        column = cell.column
        for char in cell.text:
            if unicodedata.combining(char):
                continue
            pixels[column] = char
            column += width(char)
    return "".join(pixels.get(column, " ") for column in range(max(pixels, default=-1) + 1))


@pytest.mark.parametrize("count", (0, 3))
def test_new_session_starts_hologram_and_two_toggles_restore_it(count):
    config = configured()
    actions = SessionViewActions(config.models[:count])
    expected_id = config.models[0].id if count else None
    assert actions.selection() == ViewSelection(expected_id, "hologram")
    actions.on_key("t")
    assert actions.selection() == ViewSelection(expected_id, "moonlight")
    actions.on_key("t")
    assert actions.selection() == ViewSelection(expected_id, "hologram")
    assert SessionViewActions(config.models[:count]).selection() == ViewSelection(expected_id, "hologram")


def test_default_view_and_implicit_first_frame_use_hologram():
    assert ViewSelection().theme == "hologram"
    frame = compose_frame(snapshot(), configured(), TerminalSize(120, 44), HOST, NOW,
                          gpu_slots=UUIDS, monotonic_now=100.0)
    assert frame.theme == "hologram"
    assert any(cell.text == "Theme: Hologram [t]" for cell in frame.cells)


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("size", (TerminalSize(120, 44), TerminalSize(80, 24)), ids=("full", "too-small"))
def test_frame_carries_selected_theme_even_when_window_is_too_small(theme, size):
    frame = draw(theme=theme, size=size)
    assert frame.theme == theme
    if not frame.too_small:
        assert any(cell.text == f"Theme: {theme.title()} [t]" for cell in frame.cells)
    else:
        assert frame.regions == ()
        assert any("q Quit" in cell.text for cell in frame.cells)


@pytest.mark.parametrize("theme", THEMES)
def test_brand_hardware_model_route_and_footer_use_semantic_roles(theme):
    frame = draw(theme=theme)
    header = cells_in(frame, "header")
    strokes = [cell for cell in header if cell.row < 4 and cell.column < 60]
    assert all(" " not in cell.text for cell in strokes)
    pixels = {(cell.row, cell.column + offset): (char, cell.role)
              for cell in strokes for offset, char in enumerate(cell.text)}
    assert pixels[0, 1] == ("▀", "secondary")
    assert pixels[1, 14] == pixels[1, 16] == ("▀", "muted")
    assert pixels[0, 18] == ("▄", "primary")
    assert (0, 4) not in pixels
    assert all(role != "brand_shadow" and char not in "─│╭╮╰╯╷╶" for char, role in pixels.values())
    assert all(row < 3 for row, column in pixels)
    info = next(cell for cell in header if "offline" in cell.text)
    clock = next(cell for cell in header if "2026-11-04" in cell.text)
    assert info.row == clock.row == 4 and info.column + width(info.text) < clock.column
    gpu = cells_in(frame, "gpu")
    for label, role in (("[0]", "primary"), ("[1]", "muted")):
        identity = next(cell for cell in gpu if cell.text == label)
        bar = [cell for cell in gpu if cell.row == identity.row + 1]
        filled = next(cell for cell in bar if cell.column == 2 and set(cell.text) == {"▌"})
        empty = next(cell for cell in bar if cell.column == 19 and set(cell.text) == {"▌"})
        percent = next(cell for cell in bar if cell.text == "50%")
        assert filled.role == percent.role == role
        assert empty.role == "track"
        assert len(filled.text + empty.text) == 33  # 71-column GPU panel, 67-column content.
        assert percent.column == empty.column + len(empty.text) + 1
    assert all(cell.role == "muted" for cell in gpu if "GiB" in cell.text)
    host = cells_in(frame, "host")
    assert all(cell.role == "secondary" for cell in host if set(cell.text) == {"▌"} and cell.column == 74)
    assert all(cell.role == "track" for cell in host if set(cell.text) == {"▌"} and cell.column > 74)
    ram_row = regions(frame)["host"].row + 3
    assert "4 / 16 GiB" in row_text(host, ram_row)
    assert next(cell for cell in host if cell.row == ram_row and cell.text == "4 / ").role == "muted"
    assert next(cell for cell in host if cell.row == ram_row and cell.text == "16").role == "text"
    service = cells_in(frame, "service")
    assert next(cell for cell in service if cell.text == " vLLM ").role == "secondary"
    assert all(cell.role == "primary" for cell in service if cell.text == "Model-chat")
    assert next(cell for cell in service if cell.text == ":8000").role == "secondary"
    assert "Total 3 seq" in row_text(service, regions(frame)["service"].row + 7)
    assert "Avg queue 0.5s" in row_text(service, regions(frame)["service"].row + 7)
    assert all(cell.role == "primary" for cell in cells_in(frame, "footer"))
    text = " ".join(cell.text for cell in frame.cells)
    assert all(token not in text for token in ("Details", "Pause", "MOCK", "SIMULATED", "!"))


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("waiting,stale,sampled_at,queued", (
    (0, False, 100.0, False), (7, False, 100.0, True),
    (7, True, 100.0, False), (7, False, None, False),
    (None, False, 100.0, False),
), ids=("zero", "queued", "stale-old-positive", "not-sampled", "unknown"))
def test_amber_is_reserved_for_fresh_queued_status_and_positive_waiting(theme, waiting, stale, sampled_at, queued):
    frame = draw(snapshot(waiting=waiting, stale=stale, sampled_at=sampled_at), theme=theme)
    amber = [cell for cell in frame.cells if cell.role == "amber"]
    assert {cell.text for cell in amber} == ({"QUEUED", "7"} if queued else set())
    waiting_labels = [cell for cell in frame.cells if cell.text == "WAITING"]
    assert waiting_labels and all(cell.role == "text" for cell in waiting_labels)
    if waiting == 0:
        service = regions(frame)["service"]
        zero_values = [cell for cell in cells_in(frame, "service") if cell.text == "0"
                       and (cell.column < service.column + 27 or cell.row < service.row + 12)]
        assert zero_values and all(cell.role == "text" for cell in zero_values)
    if stale:
        assert all(cell.role == "text" for cell in frame.cells if cell.text == "STALE")
    assert all("!" not in cell.text for cell in frame.cells)
    assert not any(cell.role == "amber" for cell in cells_in(frame, "docker"))


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("kind", tuple(ModelType), ids=lambda kind: kind.value)
def test_failures_and_recovery_keep_regions_metric_slots_and_history_geometry(theme, kind):
    data, config = snapshot(), configured()
    failed = replace(data, objects=tuple(replace(obj, stale=True) for obj in data.objects))
    before = deepcopy((data, failed, config))
    frames = [draw(item, config, theme=theme, model_id=kind.value) for item in (data, failed, data)]
    assert frames[0] == frames[2]
    assert frames[0].regions == frames[1].regions
    assert plot(frames[0]) == plot(frames[1])
    assert not any(cell.text == "STALE" for cell in frames[0].cells)
    statuses = [cell for cell in frames[1].cells if cell.text == "STALE"]
    assert statuses
    for name in ("gpu", "host", "storage", "docker", "service"):
        assert any(cell.text == "STALE" for cell in cells_in(frames[1], name))
    # A failure may replace an existing value/status but cannot add a new row.
    assert {cell.row for cell in frames[1].cells} == {cell.row for cell in frames[0].cells}
    for frame in frames:
        text = " ".join(cell.text for cell in frame.cells).lower()
        assert all(forbidden not in text for forbidden in ("last success", "ago", "exception", "timeout", "error", "failed"))
    assert (data, failed, config) == before


@pytest.mark.parametrize("theme", THEMES)
def test_theme_change_is_presentation_only_for_same_selection_and_snapshot(theme):
    data, config = snapshot(), configured()
    before = deepcopy((data, config))
    frames = [draw(data, config, theme=value, model_id="embedding") for value in (theme, THEMES[1 - THEMES.index(theme)])]
    assert frames[0].regions == frames[1].regions
    # Palette metadata and the theme label are the only changes to a pure frame.
    assert tuple(cell for cell in frames[0].cells if not cell.text.startswith("Theme:")) == tuple(
        cell for cell in frames[1].cells if not cell.text.startswith("Theme:"))
    assert plot(frames[0]) == plot(frames[1])
    for frame in frames:
        assert next(cell for cell in frame.cells if cell.text == "[0]").role == "muted"
        assert next(cell for cell in frame.cells if cell.text == "[1]").role == "primary"
    assert (data, config) == before


@pytest.mark.parametrize("theme", THEMES)
def test_resize_keeps_half_page_storage_three_rows_and_docker_visible_prefix(theme):
    data, config = snapshot(), configured()
    for height, header_height, visible in ((36, 3, 0), (37, 3, 1), (40, 3, 2),
                                           (41, 6, 0), (44, 6, 1), (48, 6, 3), (42, 6, 0)):
        frame = draw(data, config, theme=theme, size=TerminalSize(120, height))
        area = regions(frame)
        assert not frame.too_small
        assert area["service"].row == height - height // 2
        assert sum(area[name].height for name in ("service", "service_switch", "footer")) == height // 2
        assert area["header"].height == header_height
        header = cells_in(frame, "header")
        separator_row = header_height - 1
        assert row_text(header, separator_row) == "─" * area["header"].width
        assert {cell.role for cell in header if cell.row == separator_row} == {"muted"}
        assert area["gpu"].row == area["host"].row == header_height
        assert (area["storage"].row, area["storage"].height) == (header_height + 6, 6)
        assert area["docker"].row == area["storage"].row + area["storage"].height
        paths = [cell for cell in cells_in(frame, "storage") if cell.text in ("/", "/data", "/cache")
                 or cell.text.startswith(("/ ", "/data ", "/cache "))]
        assert [cell.row for cell in paths] == list(range(header_height + 8, header_height + 11))
        assert [cell.text for cell in cells_in(frame, "docker") if cell.text in {item.id for item in config.containers}] == [
            item.id for item in config.containers[:visible]]
        assert area["docker"].row + area["docker"].height == area["service"].row
        assert all(token not in " ".join(cell.text for cell in frame.cells).lower()
                   for token in ("enlarge", "hidden", "more", "overflow", "…", "..."))
    assert len(config.containers) == 8 and len(data.objects) == 18


@pytest.mark.parametrize("theme", THEMES)
def test_long_names_preserve_status_and_metric_slots_without_crossing_regions(theme):
    frame = draw(snapshot(stale=True, long_names=True), configured(long_names=True), theme=theme)
    for cell in frame.cells:
        owners = [area for area in frame.regions if area.row <= cell.row < area.row + area.height
                  and area.column <= cell.column and cell.column + width(cell.text) <= area.column + area.width]
        assert len(owners) == 1, cell
        if cell.text == "STALE":
            # Later drawing must not overwrite a visible status with a long name.
            index = frame.cells.index(cell)
            assert not any(later.row == cell.row
                           and later.column < cell.column + width(cell.text)
                           and later.column + width(later.text) > cell.column
                           for later in frame.cells[index + 1:])
    service = cells_in(frame, "service")
    area = regions(frame)["service"]
    assert "Total 3 seq" in row_text(service, area.row + 7)
    assert "Avg queue 0.5s" in row_text(service, area.row + 7)
    assert "CHAT / :8000" in row_text(service, area.row + 3)
    assert not any(cell.text == "[chat]" for cell in service)
    assert any(cell.text == "50%" for cell in cells_in(frame, "gpu"))


@pytest.mark.parametrize("kind", tuple(ModelType), ids=lambda kind: kind.value)
def test_explicit_history_scale_survives_theme_and_width_changes_without_mutating_inputs(kind):
    from joi_observer.tui.history import HistoryScale

    data, config = snapshot(), configured()
    field, unit = ("decode_rate", "tok/s") if kind == ModelType.CHAT else ("rate", "seq/s")
    scales = (HistoryScale(kind.value, field, 5),)
    before = deepcopy((data, config, scales))
    for size in (TerminalSize(120, 44), TerminalSize(140, 48), TerminalSize(120, 44)):
        frames = [draw(data, config, theme=theme, model_id=kind.value, size=size,
                       history_scales=scales) for theme in THEMES]
        assert plot(frames[0]) == plot(frames[1])
        for frame in frames:
            service = regions(frame)["service"]
            label = next(cell for cell in frame.cells if cell.text == f"Scale ≤ 5 {unit}")
            title = next(cell for cell in frame.cells if "HISTORY |" in cell.text)
            assert label.row == title.row == service.row + 12
            assert label.role == "muted" and title.role == "secondary"
            assert label.column + width(label.text) == service.column + service.width - 2
            assert title.column + width(title.text) < label.column
            curve = [cell for cell in plot(frame) if any("\u2800" <= char <= "\u28ff" for char in cell.text)]
            assert curve and all(cell.role == "primary" and not cell.bold for cell in curve)
            assert all(cell.row > service.row + 13 for cell in curve)
            marker = next(cell for cell in plot(frame) if cell.text == "▼")
            assert marker.row == service.row + 13 and marker.role == "text" and marker.bold
            assert any(cell.text == f"Model-{kind.value}" and cell.role == "primary"
                       for cell in cells_in(frame, "service"))
    assert (data, config, scales) == before
