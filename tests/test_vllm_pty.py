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
                       HistoryPoint(99, None), HistoryPoint(100, (Metric(primary, 5, unit),)))
            for stale in (False, True, False):
                snapshot = StateSnapshot((ObjectSnapshot(spec.key, metrics, stale, 100, history),))
                frame = compose_frame(snapshot, AppConfig(models=(model,)), TerminalSize(120, height),
                                      HostInfo('local', 'Ubuntu'), datetime.now(timezone.utc),
                                      view=ViewSelection(model.id), monotonic_now=100)
                terminal.render(frame)
                service = next(region for region in frame.regions if region.name == 'service')
                right = service.column + service.width // 3 + 2
                status_cell = next(cell for cell in frame.cells
                                   if cell.row == service.row + 1 and cell.column >= right
                                   and cell.text in ('QUEUED', 'STALE'))
                waiting_label = next(cell for cell in frame.cells
                                     if cell.row == service.row + 4 and cell.column >= right
                                     and cell.text == 'WAITING:')
                waiting_value_column = waiting_label.column + len('WAITING') + 2
                def color(row, column):
                    pair = curses.pair_number(terminal._screen.inch(row, column))
                    return curses.pair_content(pair)[0]
                observations.append({
                    'kind': kind.value, 'stale': stale, 'height': height,
                    'regions': {region.name: [region.row, region.height] for region in frame.regions},
                    'screen': [terminal._screen.instr(row, 0).decode('utf-8')
                               for row in range(service.row, service.row + service.height)],
                    'status_color': color(status_cell.row, status_cell.column),
                    'waiting_label_color': color(waiting_label.row, waiting_label.column),
                    'waiting_value_color': color(waiting_label.row, waiting_value_column),
                    'yellow': curses.COLOR_YELLOW, 'white': curses.COLOR_WHITE,
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


def test_vllm_types_status_colors_resize_and_quit_in_real_curses(tmp_path):
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
            lower = frame["height"] // 2
            assert frame["regions"]["service"] == [lower, lower - 2]
            assert frame["regions"]["service_switch"] == [frame["height"] - 2, 1]
            assert frame["regions"]["footer"] == [frame["height"] - 1, 1]
            screen = "\n".join(frame["screen"])
            assert "STALE" in screen if frame["stale"] else "QUEUED" in screen
            assert "DECODE HISTORY" in screen if frame["kind"] == "chat" else "RATE HISTORY" in screen
            assert "Avg queue" in screen and "Total" in screen
            assert "-2s" in screen and "0s" in screen and "·" in screen and "█" in screen
            assert frame["waiting_label_color"] == frame["white"]
            expected = frame["white"] if frame["stale"] else frame["yellow"]
            assert frame["status_color"] == frame["waiting_value_color"] == expected
        for start in range(0, 18, 3):
            assert result["frames"][start]["regions"] == result["frames"][start + 1]["regions"]
            assert result["frames"][start]["screen"] == result["frames"][start + 2]["screen"]
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        os.close(master)
        os.close(slave)
