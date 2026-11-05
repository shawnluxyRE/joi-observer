"""Frozen vLLM snapshots through real local ncurses, without any service IO."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest


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

ready, report = map(Path, sys.argv[1:])
connections = []
def forbidden(*args, **kwargs):
    connections.append('attempted')
    raise AssertionError('Network forbidden in local vLLM PTY test')
socket.getaddrinfo = socket.create_connection = forbidden
socket.socket.connect = socket.socket.connect_ex = forbidden
terminal = CursesTerminal()
observations = []
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
                    # -1 means the terminal's unspecified default color; keep
                    # it observable as None rather than aborting before the
                    # parent can report the missing explicit RGB/background.
                    return {'foreground': curses.color_content(foreground) if foreground >= 0 else None,
                            'background': curses.color_content(background) if background >= 0 else None}
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
                    # Row 7 is now the Host border. Probe an actual ASCII blank:
                    # narrow inch() cannot separate a Unicode glyph's high bits
                    # from color attributes, so it is not a border-color oracle.
                    'blank_color': color(0, 20),
                    'blank_character': terminal._screen.inch(0, 20) & curses.A_CHARTEXT,
                    'mutable_256': curses.COLORS >= 256 and curses.can_change_color(),
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
report.write_text(json.dumps({'frames': observations, 'connections': connections, 'key': key}))
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
        result = json.loads(report.read_text())
        assert result["connections"] == [] and result["key"] == "q"
        assert len(result["frames"]) == 18
        for frame in result["frames"]:
            if checks == "colors":
                # xterm-256color in local WSL supports exact mutable colors. These
                # are the specified RGB values in curses' 0..1000 channel units,
                # independent of whichever private slots and pairs are allocated.
                assert frame["mutable_256"]
                assert frame["blank_character"] == ord(" ")
                text, amber, background = [831, 867, 922], [1000, 643, 357], [31, 55, 94]
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
            assert "-60s" in screen and "0s" in screen and "·" in screen
            assert any(character in screen for character in "▁▂▃▄▅▆▇█")
            assert "-2s" not in screen
            unit = "tok/s" if frame["kind"] == "chat" else "seq/s"
            assert f"Scale ≤ 5 {unit}" in frame["screen"][12]
            for offset in (1, 5, 11):
                assert frame["screen"][offset][30:118].strip() == ""
            chart = frame["screen"][13:lower - 4]
            visible = {(row_index, column): character for row_index, line in enumerate(chart)
                       for column, character in enumerate(line)
                       if column >= 30 and character in "·▁▂▃▄▅▆▇█"}
            assert {column for _, column in visible} == {114, 117}
            assert visible[len(chart) - 1, 114] == "·"
            assert len(chart) == lower - 17  # One row at the minimum, seven at 48 total rows.
            # Peak 3 uses the nice upper 5: 5 eighths at height 1, 34 at 7.
            assert sum("▁▂▃▄▅▆▇█".index(character) + 1
                       for (_, column), character in visible.items()
                       if column == 117) == (5 if frame["height"] == 36 else 34)
        for start in range(0, 18, 3):
            assert result["frames"][start]["regions"] == result["frames"][start + 1]["regions"]
            assert result["frames"][start]["screen"] == result["frames"][start + 2]["screen"]
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        os.close(master)
        os.close(slave)
