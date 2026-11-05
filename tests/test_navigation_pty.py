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


pytestmark = pytest.mark.skipif(os.name != "posix", reason="Requires a local Unix PTY; verified in WSL")


CHILD = r'''
import asyncio, curses, json, socket, sys, time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from joi_observer.config import AppConfig, ModelConfig, ModelType
from joi_observer.data.models import ObjectSnapshot, StateSnapshot
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
models = tuple(ModelConfig(kind.value, kind, kind.value.upper(), 'http://offline.invalid:8000')
               for kind in ModelType)
objects = []
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
        # Observe the real ncurses screen after rendering. Labels locate cells;
        # inch/pair_content/color_content supply their actual RGBs.
        def screen_colors(row, column):
            attribute = self.terminal._screen.inch(row, column)
            foreground, background = curses.pair_content(curses.pair_number(attribute))
            return {
                'character': attribute & curses.A_CHARTEXT,
                'foreground': None if foreground == -1 else curses.color_content(foreground),
                'background': None if background == -1 else curses.color_content(background),
                'dim': bool(attribute & curses.A_DIM),
            }

        colors = {}
        for role, label in (('primary', 'Observer'), ('secondary', 'Joi'), ('muted', '::')):
            cell = next(cell for cell in frame.cells if cell.text == label)
            colors[role] = screen_colors(cell.row, cell.column)
        # Between the brand and theme label, this cell is deliberately blank.
        colors['blank'] = screen_colors(0, 20)
        service = next(region for region in frame.regions if region.name == 'service')
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
            'theme': [cell.text for cell in frame.cells if cell.text.startswith('Theme:')],
            'colors': colors,
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


@pytest.mark.parametrize("checks", ("navigation", "theme-name", "colors"))
def test_real_arrows_drive_default_app_and_disabled_keys_preserve_selection(tmp_path, checks):
    import fcntl
    import pty
    import select
    import struct
    import termios

    report = tmp_path / "report.json"
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
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
        deadline = time.monotonic() + 5
        acknowledgement = tmp_path / f"ack-{step}"
        while not acknowledgement.exists() and child.poll() is None and time.monotonic() < deadline:
            if select.select([master], [], [], 0.01)[0]:
                drain()
        assert acknowledgement.exists(), (step, child.poll(), bytes(captured))
        drain()

    try:
        wait_for_ack(0)
        # Both standard CSI and application-mode SS3 arrows reach real ncurses.
        inputs = (b"\x1b[B", b"\x1bOB", b"\x1b[D", b"\x1bOC",
                  b"\x1bOA", b"t", b"t", b"\r", b"p")
        for step, sequence in enumerate(inputs, 1):
            os.write(master, sequence)
            wait_for_ack(step)
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
            if checks == "theme-name":
                assert frame["theme"] == [f"Theme: {'Moonlight' if step == 6 else 'Hologram'} [t]"]
                continue
            if checks == "colors":
                # Requirement RGBs expressed literally on ncurses' 0..1000 scale:
                # #7DDFFF/#C6A7FF or #7B9FFF/#E570D0; common #8A9DB5/#080E18.
                accents = {"primary": [490, 875, 1000], "secondary": [776, 655, 1000]} if step == 6 else {
                    "primary": [482, 624, 1000], "secondary": [898, 439, 816],
                }
                for role, character in (("primary", "O"), ("secondary", "J"), ("muted", ":")):
                    color = frame["colors"][role]
                    assert color["character"] == ord(character)
                    assert color["foreground"] == (accents[role] if role in accents else [541, 616, 710])
                    assert color["background"] == [31, 55, 94]
                    assert color["dim"] is False
                assert frame["colors"]["blank"]["character"] == ord(" ")
                assert frame["colors"]["blank"]["background"] == [31, 55, 94]
                continue
            assert frame["detail_name"] == [kind.upper()]
            assert frame["detail_type"] == []
            assert frame["list_type"] == [f"{kind.upper()} / :8000"]
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
