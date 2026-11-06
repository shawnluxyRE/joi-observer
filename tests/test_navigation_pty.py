"""Default application navigation and theme cycle through a real, local Unix PTY.

The child uses a fixed read-only snapshot and forbids every network connection.
Only the terminal boundary is decorated to record completed frames and publish
acknowledgements; selection, input decoding and rendering remain production code.
"""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import pytest

from test_theme_pty import sgr_at


pytestmark = pytest.mark.skipif(os.name != "posix", reason="Requires a local Unix PTY; verified in WSL")


CHILD = r'''
import asyncio, curses, json, socket, sys, time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from joi_observer.config import AppConfig, ModelConfig, ModelType
from joi_observer.data.models import Metric, ObjectKey, ObjectSnapshot, StateSnapshot
from joi_observer.data.vllm import make_vllm_spec
from joi_observer.tui.app import CursesTerminal, ObserverApp
from joi_observer.tui.layout import HostInfo

directory, report = map(Path, sys.argv[1:])
connections = []

def forbidden(*args, **kwargs):
    connections.append('attempted')
    raise AssertionError('Network forbidden in local navigation PTY test')

socket.getaddrinfo = socket.create_connection = forbidden
socket.socket.connect = socket.socket.connect_ex = forbidden

def forbidden_palette_write(*args, **kwargs):
    raise AssertionError('Fixed palettes must not redefine terminal colors')
curses.init_color = forbidden_palette_write

models = tuple(ModelConfig(kind.value, kind, kind.value.upper(), f'http://offline.invalid:{8000 + index}',
                           ('0', '1', '2', '3') if kind == ModelType.CHAT else ('4',))
               for index, kind in enumerate(ModelType))
objects = [ObjectSnapshot(ObjectKey('gpu', f'GPU-00000000-0000-0000-0000-{index:012d}'),
                          (Metric('index', index), Metric('name', 'NVIDIA GeForce RTX')),
                          sampled_at=time.monotonic()) for index in range(5)]
for model in models:
    spec = make_vllm_spec(model)
    values = dict(running=3, waiting=0, total=3, decode_rate=100, prefill_rate=500,
                  rate=3, ttft_seconds=0.2, queue_seconds=0.1,
                  latency_seconds=0.3, kv_cache_percent=25)
    metrics = tuple(replace(metric, value=values[metric.name] if metric.applicable else None)
                    for metric in spec.metrics)
    objects.append(ObjectSnapshot(spec.key, metrics, sampled_at=time.monotonic()))
snapshot = StateSnapshot(tuple(objects), 17)

class FixedReader:
    def __init__(self):
        self.reads = 0

    def snapshot(self):
        self.reads += 1
        return snapshot

class ObservedTerminal:
    def __init__(self):
        self.terminal = CursesTerminal()
        self.keys = []
        self.frames = []
        self.pending = 0
        self.entered = 0
        self.restored = 0

    def enter(self):
        self.terminal.enter()
        self.entered += 1

    def restore(self):
        self.terminal.restore()
        self.restored += 1

    def size(self):
        return self.terminal.size()

    def render(self, frame):
        self.terminal.render(frame)
        if self.pending is None:
            return
        # Read the visible Unicode glyphs. inch() mixes a multibyte glyph with
        # its attributes, so the parent checks their colors in the emitted SGR.
        screen = self.terminal._screen
        glyphs = [screen.instr(row, column, 3).decode('utf-8') for row, column in
                  ((0, 1), (0, 4), (1, 14), (1, 16), (0, 18))]
        blank = screen.inch(0, 70)
        service = next(region for region in frame.regions if region.name == 'service')
        gpu = next(region for region in frame.regions if region.name == 'gpu')
        divider = service.column + 27
        names = {model.name for model in models}
        right = [cell for cell in frame.cells
                 if service.row < cell.row < service.row + service.height - 1
                 and service.column + 30 <= cell.column < service.column + service.width - 2]
        selected_rows = {cell.row for cell in frame.cells if cell.text in names
                         and cell.column < divider and cell.role == 'primary'}
        observation = {
            'step': self.pending,
            'selected': [cell.text for cell in frame.cells if cell.text in names
                         and cell.column < divider and cell.role == 'primary'],
            'detail_name': [cell.text for cell in right
                            if cell.row == service.row + 2 and cell.text in names],
            'detail_type': [cell.text for cell in right
                            if cell.row == service.row + 2 and cell.text.startswith('[')],
            'list_type': [cell.text for cell in frame.cells if cell.column < divider
                          and cell.row - 1 in selected_rows and ' / :' in cell.text],
            'detail': ' '.join(cell.text for cell in right),
            'detail_port': screen.instr(service.row + 3, service.column + 30).decode().rstrip(' │'),
            'gpu_rows': [screen.instr(row, gpu.column + 2).decode()[:gpu.width - 4]
                         for row in range(gpu.row + 1, gpu.row + gpu.height - 1)],
            'gpu_muted_rules': [cell.row - (gpu.row + 1) for cell in frame.cells
                                if gpu.row < cell.row < gpu.row + gpu.height - 1
                                and cell.column == gpu.column + 2 and cell.role == 'muted'
                                and cell.text == '─' * (gpu.width - 4)],
            'theme': [cell.text for cell in frame.cells if cell.text.startswith('Theme:')],
            'brand_glyphs': glyphs,
            'blank': [blank & curses.A_CHARTEXT, curses.pair_content(curses.pair_number(blank))[1]],
            'switch': [cell.text for cell in frame.cells
                       if cell.row == next(region.row for region in frame.regions
                                           if region.name == 'service_switch')],
            'footer': [cell.text for cell in frame.cells
                       if cell.row == next(region.row for region in frame.regions
                                           if region.name == 'footer')],
            'regions': [(region.name, region.row, region.column, region.width, region.height)
                        for region in frame.regions],
        }
        self.frames.append(observation)
        # Publish only after the application has rendered a frame following the
        # previous key. The parent never waits for the desired business result.
        (directory / ('ack-' + str(self.pending))).touch()
        self.pending = None

    async def read_key(self, timeout):
        key = await self.terminal.read_key(timeout)
        if key is not None:
            self.keys.append(key)
            self.pending = len(self.keys)
        return key

reader, terminal = FixedReader(), ObservedTerminal()
# Deliberately omit actions: the public default application path owns navigation.
app = ObserverApp(AppConfig(models=models, mount_points=()), reader, terminal,
                  host=HostInfo('local', 'Ubuntu'),
                  wall_clock=lambda: datetime.now(timezone.utc))
try:
    asyncio.run(app.run())
finally:
    report.write_text(json.dumps({'frames': terminal.frames, 'keys': terminal.keys,
                                  'connections': connections, 'reads': reader.reads,
                                  'entered': terminal.entered, 'restored': terminal.restored}))
'''


@pytest.mark.parametrize("checks,height", [("navigation", 45), ("theme-name", 48), ("colors", 45)],
                         ids=("navigation", "theme-name", "colors"))
def test_real_arrows_drive_default_app_and_disabled_keys_preserve_selection(tmp_path, checks, height):
    import fcntl
    import pty
    import select
    import struct
    import termios

    report = tmp_path / "report.json"
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", height, 120, 0, 0))
    original = termios.tcgetattr(slave)
    env = dict(os.environ, TERM="xterm-256color", LANG="C.UTF-8")
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    child = subprocess.Popen([sys.executable, "-c", CHILD, str(tmp_path), str(report)],
                             stdin=slave, stdout=slave, stderr=slave, env=env)
    captured = bytearray()

    def drain():
        while select.select([master], [], [], 0)[0]:
            captured.extend(os.read(master, 65536))

    def wait_for_ack(step):
        start = len(captured)
        deadline = time.monotonic() + 5
        acknowledgement = tmp_path / f"ack-{step}"
        while not acknowledgement.exists() and child.poll() is None and time.monotonic() < deadline:
            if select.select([master], [], [], 0.01)[0]:
                drain()
        assert acknowledgement.exists(), (step, child.poll(), bytes(captured))
        drain()
        return bytes(captured[start:])

    try:
        output_by_step = [wait_for_ack(0)]
        # Both standard CSI and application-mode SS3 arrows reach real ncurses.
        inputs = (b"\x1b[B", b"\x1bOB", b"\x1b[D", b"\x1bOC",
                  b"\x1bOA", b"t", b"t", b"\r", b"p")
        for step, sequence in enumerate(inputs, 1):
            os.write(master, sequence)
            output_by_step.append(wait_for_ack(step))
        os.write(master, b"q")
        child.wait(timeout=5)
        drain()
        assert child.returncode == 0, bytes(captured)
        result = json.loads(report.read_text())

        # Finish the complete interaction and restoration before any navigation
        # assertion. Missing R4 wiring fails here, not at a readiness timeout.
        assert termios.tcgetattr(slave) == original
        assert result["entered"] == result["restored"] == 1
        assert result["connections"] == []
        assert result["keys"] == ["down", "down", "left", "right", "up", "t", "t", "enter", "p", "q"]
        assert b"\x1b[?1049h" in captured and b"\x1b[?1049l" in captured
        assert b"\x1b[?25l" in captured and b"\x1b[?25h" in captured
        assert b"\x1b]4;" not in captured
        assert b"\x1b[38;5;111m" in captured and b"\x1b[38;5;117m" in captured
        assert b"\x1b[48;5;233m" in captured
        mouse_modes = {b"1000", b"1002", b"1003", b"1006"}
        assert not any(mouse_modes.intersection(parameters.split(b";"))
                       for parameters in re.findall(rb"\x1b\[\?([0-9;]+)h", captured))
        frames = result["frames"]
        assert [frame["step"] for frame in frames] == list(range(10))
        assert result["reads"] >= len(frames)
        expected = ["chat", "embedding", "reranker", "reranker", "reranker",
                    "embedding", "embedding", "embedding", "embedding", "embedding"]
        assert [frame["selected"] for frame in frames] == [[kind.upper()] for kind in expected]
        for step, (frame, kind) in enumerate(zip(frames, expected)):
            gpu_rows = frame["gpu_rows"]
            main = gpu_rows[0]
            assert main.startswith("GPU 0–3") and main.endswith("TP 4")
            assert main[len("GPU 0–3"):-len("TP 4")].isspace()
            assert gpu_rows[1] == " " * len(main)
            assert gpu_rows[2].startswith("[0] NVIDIA GeForce RTX ")
            shared_row, = (row for row, line in enumerate(gpu_rows) if line.startswith("GPU 4"))
            shared = gpu_rows[shared_row]
            assert shared.endswith("SHARED") and shared[len("GPU 4"):-len("SHARED")].isspace()
            assert [row for row, line in enumerate(gpu_rows) if line == "─" * len(main)] == [shared_row - 1]
            assert frame["gpu_muted_rules"] == [shared_row - 1]
            assert gpu_rows[shared_row + 1] == " " * len(main)
            assert gpu_rows[shared_row + 2].startswith("[4] NVIDIA GeForce RTX ")
            port = {"chat": 8000, "embedding": 8001, "reranker": 8002}[kind]
            assert frame["detail_port"] == f":{port}"
            if checks == "theme-name":
                assert frame["theme"] == [f"Theme: {'Moonlight' if step == 6 else 'Hologram'} [t]"]
                continue
            if checks == "colors":
                assert frame["brand_glyphs"] == ["▀", "╷", "▀", "▀", "▄"]
                assert frame["blank"] == [ord(" "), 233]
                if step in (0, 6, 7):  # First paint and both theme changes.
                    primary, secondary = (117, 183) if step == 6 else (111, 170)
                    output = output_by_step[step]
                    for glyphs, foreground, count in (("▀▀█", secondary, 1), ("▄▀▀▄", primary, 1),
                                                     ("▀", 247, 2), ("╷", 243, 1)):
                        attributes = [sgr_at(output, match.start()) for match in
                                      re.finditer(re.escape(glyphs.encode()), output)]
                        assert attributes.count((False, False, foreground, 233)) >= count, (glyphs, output)
                continue
            assert frame["detail_name"] == [kind.upper()]
            assert frame["detail_type"] == []
            assert frame["list_type"] == [f"{kind.upper()} / :{port}"]
            assert "DECODE HISTORY / tok/s" in frame["detail"] if kind == "chat" else "RATE HISTORY / seq/s" in frame["detail"]
            assert "TTFT" in frame["detail"] if kind == "chat" else "Avg latency" in frame["detail"]
            assert frame["theme"] == [f"Theme: {'Moonlight' if step == 6 else 'Hologram'} [t]"]
            assert "vLLM" in " ".join(frame["switch"])
            assert "WebUI (disabled)" in " ".join(frame["switch"])
            assert " ".join(frame["footer"]) == "↑↓ Select model    t Theme    q Quit"
            assert frame["regions"] == frames[0]["regions"]
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        os.close(master)
        os.close(slave)
