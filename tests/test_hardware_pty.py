"""Production hardware pipeline through a real local Unix PTY.

Only the NVIDIA executable is a controlled local fixture. CPU, RAM, mount IO,
worker creation, cancellation, reaping, CLI, Monitor and ncurses all run normally.
The observation wrappers call the real render/spawn operations unchanged.
"""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest


pytestmark = pytest.mark.skipif(os.name != "posix", reason="Requires a local Unix PTY; verified in WSL")


CHILD = r'''
import asyncio, json, os, socket, sys
from pathlib import Path
from joi_observer.cli import main
from joi_observer.tui.app import CursesTerminal

config, progress, report = map(Path, sys.argv[1:])
processes, frames, connections = [], [], []
spawn = asyncio.create_subprocess_exec
render = CursesTerminal.render

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
    render(self, frame)
    size = self.size()
    observation = {
        'size': [size.columns, size.rows], 'too_small': frame.too_small,
        'minimum': [frame.minimum_size.columns, frame.minimum_size.rows],
        'regions': {r.name: {'row': r.row, 'height': r.height} for r in frame.regions},
        'gpu_labels': [c.text for c in frame.cells if c.text.startswith('GPU ')],
        'screen': [self._screen.instr(row, 0).decode('utf-8') for row in range(size.rows)],
    }
    frames.append(observation)
    with progress.open('a') as stream:
        stream.write(json.dumps(observation) + '\n')

def forbidden(*args, **kwargs):
    connections.append('attempted')
    raise AssertionError('Network is forbidden in this local test')

asyncio.create_subprocess_exec = observed_spawn
CursesTerminal.render = observed_render
socket.socket.connect = forbidden
socket.create_connection = forbidden
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

    resize(120, 44)
    original = termios.tcgetattr(slave)
    env = dict(os.environ, TERM="xterm-256color", LANG="C.UTF-8",
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
        # These strings come from ncurses' actual screen after its real refresh.
        final_index = 3 if mode == "slow" else 4
        wait_for(lambda: any(f"PTY GPU {final_index}" in "\n".join(frame["screen"])
                             and "16.0 GiB" in "\n".join(frame["screen"])
                             for frame in _observations(progress)))
        if mode == "slow":
            wait_for(slow_marker.exists)
            slow_pid = int(slow_marker.read_text())
            assert Path(f"/proc/{slow_pid}").exists()
        if scenario == "resize_quit":
            for columns, height in ((120, 36), (120, 37), (119, 44), (120, 45), (120, 48), (120, 44)):
                resize(columns, height)
                child.send_signal(signal.SIGWINCH)
                wait_for(lambda: any(frame["size"] == [columns, height]
                                     for frame in _observations(progress)))
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
        result = json.loads(report.read_text())
        assert not result["connections"]
        # A real mounted '/' must remain readable even when unrelated nsfs or
        # other special filesystem entries are present in local mountinfo.
        assert all("STALE" not in frame["screen"][10] for frame in result["frames"]
                   if not frame["too_small"])
        assert result["children"] and all(item["returncode"] is not None for item in result["children"])
        assert not [item for item in result["children"] if Path(f"/proc/{item['pid']}").exists()]
        assert any("_hardware_worker.py" in " ".join(item["argv"]) for item in result["children"])
        assert any(item["argv"][0] == "nvidia-smi" for item in result["children"])
        if mode == "slow":
            assert any(item["pid"] == slow_pid and item["returncode"] == -signal.SIGKILL
                       for item in result["children"])
        if scenario == "resize_quit":
            for size in ([120, 36], [119, 44]):
                assert any(frame["size"] == size and frame["too_small"] for frame in result["frames"])
            for height in (37, 44, 45, 48):
                frames = [frame for frame in result["frames"] if frame["size"] == [120, height]
                          and len(frame["gpu_labels"]) == 5]
                assert frames
                for frame in frames:
                    upper = height - height // 2
                    assert frame["minimum"] == [120, 37] and not frame["too_small"]
                    assert frame["regions"]["service"] == {"row": upper, "height": height // 2 - 2}
                    assert frame["regions"]["storage"] == {"row": 8, "height": 6}
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
