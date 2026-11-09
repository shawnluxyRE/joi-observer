"""Frozen vLLM snapshots through real local ncurses, without any service IO."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import pytest
from test_theme_pty import sgr_at
from test_vllm_view import braille_points, scan_x
from joi_observer.tui.layout import Region, TextCell


pytestmark = pytest.mark.skipif(os.name != "posix", reason="Requires a local Unix PTY; verified in WSL")


CHILD = r'''
import asyncio, curses, json, socket, sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from joi_observer.config import AppConfig, ModelConfig, ModelType
from joi_observer.data.models import HistoryPoint, Metric, ObjectSnapshot, StateSnapshot
from joi_observer.data.vllm import make_vllm_spec
from joi_observer.tui.app import CursesTerminal
from joi_observer.tui.layout import HostInfo, TerminalSize, ViewSelection, compose_frame
from joi_observer.tui.history import HistoryScale

ready, report = map(Path, sys.argv[1:])
connections = []
def forbidden(*args, **kwargs):
    connections.append('attempted')
    raise AssertionError('Network forbidden in local vLLM PTY test')
socket.getaddrinfo = socket.create_connection = forbidden
socket.socket.connect = socket.socket.connect_ex = forbidden

def forbidden_palette_write(*args, **kwargs):
    raise AssertionError('Fixed palettes must not redefine terminal colors')
curses.init_color = forbidden_palette_write

terminal = CursesTerminal()
observations = []
sweep_observations = []
try:
    terminal.enter()
    for height in (36, 48):
        curses.resizeterm(height, 120)
        for kind in ModelType:
            model = ModelConfig('model', kind, 'Local model', 'http://offline.invalid:8000')
            spec = make_vllm_spec(model)
            values = dict(running=3, waiting=7, total=10, decode_rate=100,
                          prefill_rate=500, rate=3, ttft_seconds=3, queue_seconds=0.5,
                          latency_seconds=3, kv_cache_percent=25)
            metrics = tuple(replace(metric, value=values[metric.name] if metric.applicable else None)
                            for metric in spec.metrics)
            primary = 'decode_rate' if kind == ModelType.CHAT else 'rate'
            unit = 'tok/s' if kind == ModelType.CHAT else 'seq/s'
            history = (HistoryPoint(98, (Metric(primary, 0, unit),)),
                       HistoryPoint(99, None), HistoryPoint(100, (Metric(primary, 3, unit),)))
            for stale in (False, True, False):
                snapshot = StateSnapshot((ObjectSnapshot(spec.key, metrics, stale, 100, history),))
                frame = compose_frame(snapshot, AppConfig(models=(model,)), TerminalSize(120, height),
                                      HostInfo('local', 'Ubuntu'), datetime.now(timezone.utc),
                                      view=ViewSelection(model.id), monotonic_now=100)
                terminal.render(frame)
                service = next(region for region in frame.regions if region.name == 'service')
                right = service.column + 30
                status_cell = next(cell for cell in frame.cells
                                   if cell.row == service.row + 2 and cell.column >= right
                                   and cell.text in ('QUEUED', 'STALE'))
                waiting_label = next(cell for cell in frame.cells
                                     if cell.row == service.row + 6 and cell.column >= right
                                     and cell.text.rstrip(':') == 'WAITING')
                waiting_value = next(cell for cell in frame.cells
                                     if cell.row == service.row + 6 and cell.column >= right
                                     and cell.text in ('7', '7seq', '7 seq'))
                def color(row, column):
                    pair = curses.pair_number(terminal._screen.inch(row, column))
                    foreground, background = curses.pair_content(pair)
                    # Observe selected fixed-palette indices. The terminal's
                    # physical RGB cannot be inferred from color_content.
                    return {'foreground': foreground, 'background': background}
                observations.append({
                    'kind': kind.value, 'stale': stale, 'height': height,
                    'regions': {region.name: [region.row, region.height] for region in frame.regions},
                    'screen': [terminal._screen.instr(row, 0).decode('utf-8')
                               for row in range(service.row, service.row + service.height)],
                    'status_color': color(status_cell.row, status_cell.column),
                    'waiting_label_color': color(waiting_label.row, waiting_label.column),
                    'waiting_value_color': color(waiting_value.row, waiting_value.column),
                    'waiting_positions': [waiting_label.column, waiting_value.column],
                    # These are ASCII text/numbers, so narrow inch observes
                    # A_BOLD without Unicode character bits contaminating it.
                    'ascii_weights': [
                        {'text': cell.text, 'row': cell.row - service.row, 'column': cell.column,
                         'bold': bool(terminal._screen.inch(cell.row, cell.column) & curses.A_BOLD)}
                        for cell in frame.cells
                        if service.row < cell.row < service.row + service.height - 1
                        and cell.text.isascii() and cell.text.strip()
                    ],
                    # The gap between the wordmark and Theme is an ASCII blank.
                    'blank_color': color(0, 70),
                    'blank_character': terminal._screen.inch(0, 70) & curses.A_CHARTEXT,
                    'colors': curses.COLORS,
                })
    curses.resizeterm(48, 120)
    model = ModelConfig('scan', ModelType.CHAT, 'Scan model', 'http://offline.invalid:8000')
    spec = make_vllm_spec(model)
    history = tuple(HistoryPoint(at, None if value is None else (Metric('decode_rate', value, 'tok/s'),))
                    for at, value in ((118, 4), (119, 10), (120, 2), (121, None), (122, 6)))
    snapshot = StateSnapshot((ObjectSnapshot(spec.key, spec.metrics, False, 122, history),))
    for now in (119, 119.9, 120, 121, 122):
        frame = compose_frame(snapshot, AppConfig(models=(model,)), TerminalSize(120, 48),
                              HostInfo('local', 'Ubuntu'), datetime.now(timezone.utc),
                              view=ViewSelection(model.id), monotonic_now=now,
                              history_scales=(HistoryScale('scan', 'decode_rate', 20),))
        terminal.render(frame)
        service = next(region for region in frame.regions if region.name == 'service')
        sweep_observations.append({
            'now': now,
            'screen': [terminal._screen.instr(row, 0).decode('utf-8')
                       for row in range(service.row, service.row + service.height)],
        })
    ready.touch()
    async def read_quit():
        while True:
            key = await terminal.read_key(0.05)
            if key == 'q':
                return key
    key = asyncio.run(read_quit())
finally:
    terminal.restore()
report.write_text(json.dumps({'frames': observations, 'sweep_frames': sweep_observations,
                             'connections': connections, 'key': key}))
'''


@pytest.mark.parametrize("checks", ("layout", "colors"))
def test_vllm_types_status_colors_resize_and_quit_in_real_curses(tmp_path, checks):
    import fcntl
    import pty
    import select
    import struct
    import termios

    ready, report = tmp_path / "ready", tmp_path / "report.json"
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 48, 120, 0, 0))
    original = termios.tcgetattr(slave)
    env = dict(os.environ, TERM="xterm-256color", LANG="C.UTF-8")
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    child = subprocess.Popen([sys.executable, "-c", CHILD, str(ready), str(report)],
                             stdin=slave, stdout=slave, stderr=slave, env=env)
    captured = bytearray()

    def drain():
        while select.select([master], [], [], 0)[0]:
            captured.extend(os.read(master, 65536))

    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            drain()
            time.sleep(0.01)
        assert ready.exists(), bytes(captured)
        os.write(master, b"q")
        child.wait(timeout=5)
        drain()
        assert child.returncode == 0, bytes(captured)
        assert termios.tcgetattr(slave) == original
        assert b"\x1b]4;" not in captured
        assert b"\x1b[38;5;215m" in captured and b"\x1b[38;5;253m" in captured
        assert b"\x1b[48;5;233m" in captured
        result = json.loads(report.read_text())
        assert result["connections"] == [] and result["key"] == "q"
        assert len(result["frames"]) == 18
        for frame in result["frames"]:
            if checks == "colors":
                # Mutable-color support must still use the same fixed palette.
                assert frame["colors"] >= 256
                assert frame["blank_character"] == ord(" ")
                text, amber, background = 253, 215, 233
                assert frame["waiting_label_color"]["foreground"] == text
                expected = text if frame["stale"] else amber
                assert frame["status_color"]["foreground"] == expected
                assert frame["waiting_value_color"]["foreground"] == expected
                for field in ("status_color", "waiting_label_color", "waiting_value_color", "blank_color"):
                    assert frame[field]["background"] == background
                weights = frame["ascii_weights"]
                for cell in weights:
                    expected_bold = cell["column"] >= 30 and (
                        cell["row"] == 6 and cell["text"] in ("3", "7")
                        or cell["row"] == 10 and cell["text"] != "N/A")
                    assert cell["bold"] is expected_bold, cell
                assert sum(cell["bold"] for cell in weights) == (6 if frame["kind"] == "chat" else 5)
                continue
            assert frame["waiting_positions"] == [76, 117]
            lower = frame["height"] // 2
            assert frame["regions"]["service"] == [lower, lower - 2]
            assert frame["regions"]["service_switch"] == [frame["height"] - 2, 1]
            assert frame["regions"]["footer"] == [frame["height"] - 1, 1]
            screen = "\n".join(frame["screen"])
            assert "STALE" in screen if frame["stale"] else "QUEUED" in screen
            assert "DECODE HISTORY" in screen if frame["kind"] == "chat" else "RATE HISTORY" in screen
            assert "Avg queue" in screen and "Total" in screen
            assert all(label in screen for label in ("0s", "15s", "30s", "45s", "59s"))
            assert any("\u2801" <= character <= "\u28ff" for character in screen)
            assert not any(label in screen for label in ("-60s", "游标", "分钟内"))
            unit = "tok/s" if frame["kind"] == "chat" else "seq/s"
            assert f"HISTORY | {unit}" in frame["screen"][12]
            assert f"Scale ≤ 5 {unit}" in frame["screen"][12]
            for offset in (1, 5, 11):
                assert frame["screen"][offset][30:118].strip() == ""
            chart = frame["screen"][13:lower - 4]
            region = Region("service", lower, 0, 120, lower - 2)
            cells = tuple(TextCell(region.row + offset, 30, line[30:], "primary")
                          for offset, line in enumerate(frame["screen"]))
            points = braille_points(cells, region)
            assert chart[0][36 + scan_x(100, region) // 2] == "▼"
            assert "│" not in "".join(line[36:118] for line in chart)
            assert {x for x, _ in points} == (
                {scan_x(98, region)} if frame["height"] == 36
                else {scan_x(98, region), scan_x(100, region)})
            assert len(chart) == lower - 17  # One row at the minimum, seven at 48 total rows.
            dot_height = max(1, len(chart) - 1) * 4
            assert (scan_x(98, region), dot_height - 1) in points
            if frame["height"] == 48:
                assert abs(next(y for x, y in points if x == scan_x(100, region)) - (dot_height - 1) * .4) <= 1
        cursor_attributes = [sgr_at(captured, match.start())
                             for match in re.finditer(re.escape("▼".encode()), captured)]
        assert cursor_attributes and all(attribute == (True, False, 253, 233)
                                         for attribute in cursor_attributes)
        sweeps = result["sweep_frames"]
        assert sweeps[0]["screen"] == sweeps[1]["screen"]
        region = Region("service", 24, 0, 120, 22)
        dots = []
        for sweep in sweeps:
            screen = sweep["screen"]
            assert screen[13].index("▼") == 36 + scan_x(sweep["now"], region) // 2
            dots.append(braille_points(tuple(TextCell(region.row + row, 30, line[30:], "primary")
                                             for row, line in enumerate(screen)), region))
        assert dots[0] <= dots[2]
        assert dots[2] == dots[3]  # Missing sample leaves a gap and only the marker advances.
        assert len(dots[4] - dots[3]) == 1  # No connecting stroke across the missing second.
        for start in range(0, 18, 3):
            assert result["frames"][start]["regions"] == result["frames"][start + 1]["regions"]
            assert result["frames"][start]["screen"] == result["frames"][start + 2]["screen"]
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        os.close(master)
        os.close(slave)
