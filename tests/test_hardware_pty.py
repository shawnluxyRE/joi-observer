"""Production hardware pipeline through a real local Unix PTY.

Only the NVIDIA executable is a controlled local fixture. CPU, RAM, mount IO,
worker creation, cancellation, reaping, CLI, Monitor and ncurses all run normally.
The observation wrappers call the real compose/render/spawn operations unchanged.
"""

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

import pytest


pytestmark = pytest.mark.skipif(os.name != "posix", reason="Requires a local Unix PTY; verified in WSL")


RENDER_OBSERVER = r'''
def render_observation(terminal, frame, frame_size, renderer):
    before = terminal.size()
    renderer(terminal, frame)
    after = terminal.size()
    try:
        screen = [terminal._screen.instr(row, 0).decode('utf-8') for row in range(after.rows)]
    except Exception:
        # Observation can race another resize too. Preserve that transition,
        # but never reinterpret an unrelated rendering/inspection error.
        if terminal.size() == after:
            raise
        screen = []
    final = terminal.size()
    return {
        'size': [after.columns, after.rows],
        'frame_size': [frame_size.columns, frame_size.rows],
        'size_before_render': [before.columns, before.rows],
        'size_after_render': [after.columns, after.rows],
        'size_after_observation': [final.columns, final.rows],
        'stable_size': frame_size == before == after == final,
        'too_small': frame.too_small,
        'minimum': [frame.minimum_size.columns, frame.minimum_size.rows],
        'regions': {r.name: {'row': r.row, 'height': r.height, 'column': r.column, 'width': r.width}
                    for r in frame.regions},
        'gpu_labels': [c.text for c in frame.cells if c.text.startswith('[') and c.text.endswith(']')],
        'screen': screen,
    }
'''


CHILD = RENDER_OBSERVER + r'''
import asyncio, ctypes, curses, json, os, socket, sys
from pathlib import Path
from joi_observer.cli import main
from joi_observer.tui import app as app_module
from joi_observer.tui.app import CursesTerminal

config, progress, report = map(Path, sys.argv[1:])
processes, frames, connections = [], [], []
spawn = asyncio.create_subprocess_exec
render = CursesTerminal.render
compose = app_module.compose_frame
composed_samples = {}
wide_curses = ctypes.CDLL('libncursesw.so.6')
wide_curses.mvwin_wch.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p)
wide_curses.mvwin_wch.restype = ctypes.c_int
wide_curses.getcchar.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                               ctypes.POINTER(ctypes.c_short), ctypes.c_void_p)
wide_curses.getcchar.restype = ctypes.c_int

def wide_screen_color(row, column):
    # Python's narrow inch combines Unicode character bits with attributes.
    # Read the same Ubuntu ncurses stdscr through its wide-character API instead.
    # Opaque, oversized storage avoids depending on the layout of cchar_t.
    cell = ctypes.create_string_buffer(128)
    screen = ctypes.c_void_p.in_dll(wide_curses, 'stdscr')
    if wide_curses.mvwin_wch(screen, row, column, cell) == -1:
        raise curses.error('wide screen read failed')
    characters, attributes, pair = ctypes.create_unicode_buffer(32), ctypes.c_ulong(), ctypes.c_short()
    if wide_curses.getcchar(cell, characters, ctypes.byref(attributes), ctypes.byref(pair), None) == -1:
        raise curses.error('wide screen attributes unavailable')
    foreground, background = curses.pair_content(pair.value)
    return characters.value, foreground, background, bool(attributes.value & curses.A_BOLD)

def observed_compose(snapshot, config, size, *args, **kwargs):
    frame = compose(snapshot, config, size, *args, **kwargs)
    ready_gpus = sum(obj.key.collector == 'gpu' and obj.sampled_at is not None and not obj.stale
                     for obj in snapshot.objects)
    composed_samples[id(frame)] = size, ready_gpus
    return frame

async def observed_spawn(*args, **kwargs):
    process = await spawn(*args, **kwargs)
    processes.append((process, list(args)))
    try:
        started = Path(f'/proc/{process.pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
        with report.with_suffix('.children.jsonl').open('a') as stream:
            stream.write(json.dumps({'pid': process.pid, 'started': started}) + '\n')
    except FileNotFoundError:
        pass
    return process

def observed_render(self, frame):
    frame_size, ready_gpus = composed_samples.pop(id(frame))
    observation = render_observation(self, frame, frame_size, render)
    observation['ready_gpus'] = ready_gpus
    observation['bar_colors'] = []
    if observation['stable_size'] and not frame.too_small:
        try:
            for cell in frame.cells:
                if set(cell.text) != {'▌'}:
                    continue
                character, foreground, background, bold = wide_screen_color(cell.row, cell.column)
                observation['bar_colors'].append({
                    'row': cell.row, 'column': cell.column, 'role': cell.role,
                    'character': character, 'foreground': foreground, 'background': background, 'bold': bold,
                })
        except curses.error:
            if self.size() == frame_size:
                raise
            observation['stable_size'] = False
        if self.size() != frame_size:
            observation['stable_size'] = False
    frames.append(observation)
    with progress.open('a') as stream:
        stream.write(json.dumps(observation) + '\n')

def forbidden(*args, **kwargs):
    connections.append('attempted')
    raise AssertionError('Network is forbidden in this local test')

def forbidden_palette_write(*args, **kwargs):
    raise AssertionError('Fixed palettes must not redefine terminal colors')

asyncio.create_subprocess_exec = observed_spawn
app_module.compose_frame = observed_compose
CursesTerminal.render = observed_render
socket.socket.connect = forbidden
socket.create_connection = forbidden
curses.init_color = forbidden_palette_write
try:
    result = main(['--config', str(config)])
finally:
    report.write_text(json.dumps({'frames': frames, 'connections': connections,
        'children': [{'pid': p.pid, 'returncode': p.returncode, 'argv': argv} for p, argv in processes]}))
raise SystemExit(result)
'''


NVIDIA = r'''
import os, sys, time
from pathlib import Path
ids = [f'GPU-00000000-0000-0000-0000-{index:012d}' for index in range(5)]
print('PRIVATE_RAW_DRIVER_STDERR', file=sys.stderr, flush=True)
if sys.argv[1] == '--query-gpu=index,uuid':
    for index, uuid in enumerate(ids):
        print(f'{index}, {uuid}')
else:
    uuid = sys.argv[-1].split('=', 1)[1]
    index = ids.index(uuid)
    if os.environ['JOI_PTY_MODE'] == 'slow' and index == 4:
        Path(os.environ['JOI_PTY_SLOW_MARKER']).write_text(str(os.getpid()))
        time.sleep(30)
    print(f'{index}, {uuid}, PTY GPU {index}, {25 * index}, {1024 * (index + 1)}, 16384, {40 + index}, {100 + index}')
'''


def _observations(path):
    if not path.exists():
        return []
    lines = path.read_text().splitlines()
    result = []
    for line in lines:
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            # The writer may still be completing its newest JSON line.
            pass
    return result


def _owned_process_is_live(record):
    """Match the process start time before acting on a recorded PID."""
    try:
        state = Path(f"/proc/{record['pid']}/stat").read_text().rsplit(')', 1)[1].split()
        return state[19] == record["started"] and state[0] != "Z"
    except FileNotFoundError:
        return False


def _terminate_owned_children(ownership):
    """Only kill live sessions recorded by this fixture's actual spawn wrapper."""
    for record in _observations(ownership):
        try:
            if _owned_process_is_live(record) and os.getpgid(record["pid"]) == record["pid"]:
                os.killpg(record["pid"], signal.SIGKILL)
        except ProcessLookupError:
            pass


def _cleanup_pty_child(child, drain, ownership):
    """Give the app a bounded normal close before forcing fixture cleanup."""
    if child.poll() is None:
        child.terminate()
        deadline = time.monotonic() + 1.0
        while child.poll() is None and time.monotonic() < deadline:
            drain()
            time.sleep(0.01)
    # IO commands have independent sessions. Killing only the app cannot stop
    # them after an assertion failure or a broken application shutdown path.
    _terminate_owned_children(ownership)
    if child.poll() is None:
        child.kill()
    child.wait(timeout=1)


@pytest.mark.parametrize("resize_phase", ("before-render", "during-render"))
def test_render_observer_preserves_compose_size_when_resize_races_submission(resize_phase):
    """A later physical size must not relabel an already-composed frame."""
    from datetime import datetime, timezone
    from joi_observer.config import AppConfig
    from joi_observer.data.models import StateSnapshot
    from joi_observer.tui.layout import HostInfo, TerminalSize, compose_frame

    original, resized = TerminalSize(120, 45), TerminalSize(120, 48)
    frame = compose_frame(StateSnapshot(()), AppConfig(mount_points=()), original,
                          HostInfo("offline", "Ubuntu"), datetime(2026, 11, 4, tzinfo=timezone.utc),
                          monotonic_now=100)

    class Screen:
        def instr(self, row, column):
            return f"row {row}".encode()

    class Terminal:
        _screen = Screen()
        physical = resized if resize_phase == "before-render" else original

        def size(self):
            return self.physical

    def renderer(terminal, submitted):
        assert submitted is frame
        terminal.physical = resized

    namespace = {}
    exec(RENDER_OBSERVER, namespace)
    observed = namespace["render_observation"](Terminal(), frame, original, renderer)
    assert observed["frame_size"] == [120, 45]
    assert observed["size"] == [120, 48]
    assert observed["stable_size"] is False
    assert observed["regions"]["service"] == {"row": 23, "height": 20, "column": 0, "width": 120}
    if resize_phase == "before-render":
        assert observed["size_before_render"] == observed["size_after_render"] == [120, 48]
    else:
        assert observed["size_before_render"] == [120, 45]
        assert observed["size_after_render"] == [120, 48]
    stable_terminal = Terminal()
    stable_terminal.physical = original
    stable = namespace["render_observation"](stable_terminal, frame, original,
                                             lambda terminal, submitted: None)
    assert stable["stable_size"] is True


@pytest.mark.parametrize("scenario,mode,expected", [
    ("resize_quit", "normal", 0),
    ("sigint", "normal", 130),
    ("sigterm", "normal", 143),
    ("slow_quit", "slow", 0),
    ("slow_sigint", "slow", 130),
    ("slow_sigterm", "slow", 143),
])
def test_production_hardware_pty_draw_resize_exit_and_reap(tmp_path, scenario, mode, expected):
    import fcntl
    import pty
    import select
    import struct
    import termios

    config, progress, report = (tmp_path / name for name in ("config.yaml", "progress.jsonl", "report.json"))
    slow_marker = tmp_path / "slow.pid"
    command = tmp_path / "nvidia-smi"
    command.write_text(f"#!{sys.executable}\n" + NVIDIA)
    command.chmod(0o700)
    config.write_text("sample_interval: 0.1\ncollection_timeout: 30\nmount_points: ['/']\n"
                      f"logging: {{directory: '{tmp_path / 'logs'}'}}\n")
    master, slave = pty.openpty()

    def resize(columns, rows):
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))

    resize(120, 46)
    original = termios.tcgetattr(slave)
    env = dict(os.environ, TERM="xterm", LANG="C.UTF-8",
               PATH=str(tmp_path) + os.pathsep + os.environ.get("PATH", ""),
               JOI_PTY_MODE=mode, JOI_PTY_SLOW_MARKER=str(slow_marker))
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    child = subprocess.Popen([sys.executable, "-c", CHILD, str(config), str(progress), str(report)],
                             stdin=slave, stdout=slave, stderr=slave, env=env, cwd=tmp_path)
    output = bytearray()

    def drain():
        while select.select([master], [], [], 0)[0]:
            output.extend(os.read(master, 65536))

    def wait_for(predicate, *, seconds=5):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            drain()
            if predicate():
                return
            if child.poll() is not None:
                break
            time.sleep(0.01)
        drain()
        assert predicate(), (scenario, child.returncode, bytes(output[-6000:]))

    try:
        # Each GPU has an independent worker. The highest-index GPU can finish
        # before its siblings; send q/signals only once the expected cards have
        # samples in the same rendered frame. Check their characters after exit.
        final_index = 3 if mode == "slow" else 4
        wait_for(lambda: any(frame["stable_size"] and frame["ready_gpus"] == final_index + 1
                             for frame in _observations(progress)))
        if mode == "slow":
            wait_for(slow_marker.exists)
            slow_pid = int(slow_marker.read_text())
            assert Path(f"/proc/{slow_pid}").exists()
        if scenario == "resize_quit":
            for columns, height in ((120, 38), (120, 39), (119, 46), (120, 44),
                                    (120, 45), (120, 48), (120, 46)):
                observed_before_resize = len(_observations(progress))
                resize(columns, height)
                child.send_signal(signal.SIGWINCH)
                wait_for(lambda: any(frame["stable_size"] and frame["frame_size"] == [columns, height]
                                     for frame in _observations(progress)[observed_before_resize:]))
        before_exit = time.monotonic()
        if "sigterm" in scenario:
            child.send_signal(signal.SIGTERM)
        elif "sigint" in scenario:
            child.send_signal(signal.SIGINT)
        else:
            os.write(master, b"q")
        wait_for(lambda: child.poll() is not None, seconds=2)
        elapsed = time.monotonic() - before_exit
        drain()
        assert child.returncode == expected, bytes(output)
        assert elapsed < 1.0, (scenario, elapsed)
        assert termios.tcgetattr(slave) == original
        assert b"\x1b[?1049h" in output and b"\x1b[?1049l" in output
        assert b"\x1b[?25l" in output and b"\x1b[?25h" in output
        assert b"PRIVATE_RAW_DRIVER_STDERR" not in output and b"Traceback" not in output
        assert b"PTY GPU" in output and b"GiB" in output
        assert b"\x1b]4;" not in output
        assert b"\x1b[38;5;239m" in output and b"\x1b[48;5;233m" in output
        result = json.loads(report.read_text())
        assert not result["connections"]
        # A real mounted '/' must remain readable even when unrelated nsfs or
        # other special filesystem entries are present in local mountinfo.
        assert all("STALE" not in frame["screen"][frame["regions"]["storage"]["row"]][72:]
                   for frame in result["frames"]
                   if frame["stable_size"] and not frame["too_small"])
        assert result["children"] and all(item["returncode"] is not None for item in result["children"])
        assert not [item for item in result["children"] if Path(f"/proc/{item['pid']}").exists()]
        assert any("_hardware_worker.py" in " ".join(item["argv"]) for item in result["children"])
        assert any(item["argv"][0] == "nvidia-smi" for item in result["children"])
        if mode == "slow":
            assert any(item["pid"] == slow_pid and item["returncode"] == -signal.SIGKILL
                       for item in result["children"])
        # Exact presentation is checked only after q/signal cleanup completes;
        # a layout mismatch must not be mistaken for failed startup/readiness.
        visible = [frame for frame in result["frames"] if frame["stable_size"] and not frame["too_small"]
                   and f"PTY GPU {final_index}" in "\n".join(frame["screen"])]
        assert visible
        frame = visible[-1]
        assert frame["regions"]["gpu"]["column"] == 0 and frame["regions"]["gpu"]["width"] == 71
        assert frame["regions"]["host"] == {"row": 6, "height": 6, "column": 72, "width": 48}
        host_row = frame["regions"]["host"]["row"]
        assert frame["screen"][host_row - 1] == "─" * frame["size"][0]
        cpu_value = frame["screen"][host_row + 1][78:118].strip()
        assert cpu_value == "—" or re.fullmatch(r"\d+\.\d%", cpu_value)
        ram_value = frame["screen"][host_row + 3][78:118].strip()
        assert ram_value == "— / —" or re.fullmatch(r"(?:\d+|—) / (?:\d+|—) (?:GiB|TiB)", ram_value)
        for row in (host_row + 2, host_row + 4):
            assert len(frame["screen"][row][74:96]) == 22
            assert frame["screen"][row][74:96] == "▌" * 22
            assert frame["screen"][row][96:118].strip() == ""
        assert frame["bar_colors"]
        palette_indices = {"muted": 247, "secondary": 170, "track": 239}
        for observed in frame["bar_colors"]:
            assert observed["character"] == "▌"
            assert observed["foreground"] == palette_indices[observed["role"]]
            assert observed["background"] == 233
            assert observed["bold"] is False
        for index in range(final_index + 1):
            row = frame["regions"]["gpu"]["row"] + 1 + 3 * index
            assert frame["screen"][row].startswith(f"│ [{index}] PTY GPU {index} ")
            memory = f"{index + 1}.0 / 16.0 GiB"
            assert frame["screen"][row][57 - len(memory):57] == memory
            assert frame["screen"][row][65:69] == f"{40 + index}°C"
            assert frame["screen"][row + 1][64:69] == f"{100 + index} W"
            filled = (0, 8, 17, 25, 33)[index]
            assert frame["screen"][row + 1][2:35] == "▌" * 33
            expected_spans = ([(2, "muted")] if filled else []) + ([(2 + filled, "track")] if filled < 33 else [])
            actual_spans = [(item["column"], item["role"]) for item in frame["bar_colors"]
                            if item["row"] == row + 1 and 2 <= item["column"] < 35]
            assert actual_spans == expected_spans
            percent = f"{25 * index}%"
            assert frame["screen"][row + 1][35] == " "
            assert frame["screen"][row + 1][36:36 + len(percent)] == percent
            assert "STALE" not in frame["screen"][row][:71]
        if scenario == "resize_quit":
            for size in ([120, 38], [119, 46]):
                assert any(frame["frame_size"] == size and frame["too_small"]
                           for frame in result["frames"])
            for height, header in ((39, 3), (44, 3), (45, 6), (46, 6), (48, 6)):
                # Check every generated frame against its actual compose input,
                # even if a physical resize raced its render/observation.
                frames = [frame for frame in result["frames"] if frame["frame_size"] == [120, height]
                          and len(frame["gpu_labels"]) == 5]
                assert frames
                for frame in frames:
                    upper = height - height // 2
                    assert frame["minimum"] == [120, 39] and not frame["too_small"]
                    assert frame["regions"]["service"] == {
                        "row": upper, "height": height // 2 - 2, "column": 0, "width": 120}
                    assert frame["regions"]["header"]["height"] == header
                    assert frame["regions"]["storage"] == {
                        "row": header + 6, "height": 6, "column": 72, "width": 48}
                    assert frame["regions"]["docker"]["row"] == header + 12
                    if frame["stable_size"]:
                        assert frame["screen"][header - 1] == "─" * frame["size"][0]
            assert visible[-1]["size"] == [120, 46]
        evidence = os.environ.get("JOI_PTY_EVIDENCE_DIR")
        if evidence:
            directory = Path(evidence)
            directory.mkdir(parents=True, exist_ok=True)
            result.update(scenario=scenario, exit_code=child.returncode, exit_seconds=elapsed,
                          termios_restored=True, screen_restored=True, cursor_restored=True,
                          all_local_children_reaped=True, input_mode=mode, source="real local PTY and production runtime")
            (directory / f"r4-hardware-pty-{scenario}.json").write_text(json.dumps(result, indent=2) + "\n")
            (directory / f"r4-hardware-pty-{scenario}.ansi").write_bytes(output)
    finally:
        try:
            _cleanup_pty_child(child, drain, report.with_suffix(".children.jsonl"))
        finally:
            os.close(master)
            os.close(slave)


def test_pty_observation_failure_still_stops_owned_slow_child(tmp_path, monkeypatch):
    """An assertion before q must not strand the fixture's 30-second process."""
    directory = tmp_path / "failed-observation"
    directory.mkdir()
    ownership = directory / "report.children.jsonl"
    slow_marker = directory / "slow.pid"
    original_observations = _observations

    def fail_after_slow_command_starts(path):
        if path == directory / "progress.jsonl" and slow_marker.exists():
            raise AssertionError("Injected PTY observation failure")
        return original_observations(path)

    monkeypatch.setattr(sys.modules[__name__], "_observations", fail_after_slow_command_starts)
    try:
        with pytest.raises(AssertionError, match="Injected PTY observation failure"):
            test_production_hardware_pty_draw_resize_exit_and_reap(
                directory, "slow_quit", "slow", 0)
        slow_pid = int(slow_marker.read_text())
        owned = original_observations(ownership)
        assert any(record["pid"] == slow_pid for record in owned)
        assert not any(_owned_process_is_live(record) for record in owned)
        result = json.loads((directory / "report.json").read_text())
        assert result["children"] and all(item["returncode"] is not None for item in result["children"])
        assert not [item for item in result["children"] if Path(f"/proc/{item['pid']}").exists()]
    finally:
        # Guard the regression test itself even if an implementation regression
        # makes its preceding assertions fail. Ownership is unique to directory.
        _terminate_owned_children(ownership)
