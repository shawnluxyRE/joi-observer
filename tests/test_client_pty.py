"""New client composition uses real curses and an entirely offline byte stream."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from test_ipc_protocol import large_snapshot_fixture, wire


pytestmark = pytest.mark.skipif(os.name != "posix", reason="Requires local Ubuntu/WSL PTY")


CHILD = r'''
import asyncio, json, os, socket, sys, time
from pathlib import Path
from joi_observer.cli import CommandDependencies, main
from joi_observer.data.models import Metric, ObjectKey, ObjectSnapshot, StateSnapshot
from joi_observer.ipc.client import SnapshotClient
from joi_observer.ipc.protocol import DisplayMetadata, SnapshotEnvelope, encode_envelope
from joi_observer.tui.app import CursesTerminal
from joi_observer.tui.session import TuiClientSession

scenario, progress, report, eof = sys.argv[1], *map(Path, sys.argv[2:])
events, frames, forbidden_calls = [], [], []

def publish(event):
    with progress.open('a') as output:
        output.write(json.dumps(event) + '\n')

class ByteStream:
    def __init__(self):
        now = time.monotonic()
        envelope = SnapshotEnvelope('pty-instance', 'pty-config', 1, now,
            DisplayMetadata('Offline client', 'Ubuntu 24.04'),
            StateSnapshot((ObjectSnapshot(ObjectKey('host', 'cpu'),
                (Metric('cpu_percent', 25.0, '%'),), sampled_at=now),), 1))
        self.buffer = (progress.with_name('first.frame').read_bytes() if scenario == 'large_updates'
                       else encode_envelope(envelope))
        self.closed = False
        self.reads = []
    async def readexactly(self, count):
        self.reads.append(count)
        while len(self.buffer) < count:
            if scenario == 'large_updates' and progress.with_name('updates.ready').exists():
                self.buffer += progress.with_name('updates.frame').read_bytes()
                progress.with_name('updates.ready').unlink()
                continue
            if eof.exists():
                raise asyncio.IncompleteReadError(self.buffer, count)
            await asyncio.sleep(0.005)
        value, self.buffer = self.buffer[:count], self.buffer[count:]
        return value
    async def close(self):
        self.closed = True

stream = ByteStream()
class OfflineConnector:
    calls = 0
    async def connect(self, endpoint):
        self.calls += 1
        if scenario == 'initial_failure':
            raise OSError('PRIVATE-TRANSPORT-DIAGNOSTIC')
        return stream
connector = OfflineConnector()

class ObservedTerminal(CursesTerminal):
    def enter(self):
        super().enter()
        events.append('enter')
        publish({'event': 'enter'})
        if scenario == 'enter_error':
            raise RuntimeError('PRIVATE-ENTER-DIAGNOSTIC')
    def render(self, frame):
        super().render(frame)
        frames.append(frame.theme)
        publish({'event': 'frame', 'theme': frame.theme,
                 'sequence': client.envelope().sequence})
        if scenario == 'draw_error':
            raise RuntimeError('PRIVATE-DRAW-DIAGNOSTIC')
    def restore(self):
        super().restore()
        events.append('restore')
        publish({'event': 'restore'})

def forbidden(*args, **kwargs):
    forbidden_calls.append('attempted')
    raise AssertionError('No local or remote server/config/collection boundary is allowed')
socket.socket.connect = forbidden
socket.create_connection = forbidden
import joi_observer.config as config_module
config_module.load_config = forbidden
terminal = ObservedTerminal()
client = SnapshotClient(connector=connector)
deps = CommandDependencies(Path.cwd(), Path.cwd(), sys.stdin.isatty(), sys.stdout.isatty(),
    os.environ['TERM'], sys.stdout, sys.stderr,
    lambda endpoint: TuiClientSession(client, terminal), forbidden)
try:
    result = main([], dependencies=deps)
finally:
    report.write_text(json.dumps({'events': events, 'frames': frames,
        'connector_calls': connector.calls, 'stream_closed': stream.closed,
        'forbidden_calls': forbidden_calls, 'read_sizes': stream.reads,
        'state': client.state.value}))
raise SystemExit(result)
'''


@pytest.mark.parametrize("scenario,expected", [
    ("initial_failure", 4), ("eof", 4), ("q", 0), ("large_updates", 0),
    ("sigint", 130), ("sigterm", 143), ("draw_error", 1), ("enter_error", 1),
])
def test_new_snapshot_client_cli_restores_real_terminal_and_returns_safe_exit(tmp_path, scenario, expected):
    import fcntl
    import pty
    import select
    import struct
    import termios

    progress, report, eof = (tmp_path / name for name in ("progress.jsonl", "report.json", "eof"))
    if scenario == "large_updates":
        from joi_observer.ipc.protocol import IO_CHUNK_BYTES

        _, data = large_snapshot_fixture(2)
        updates = bytearray()
        for sequence in (2, 3):
            data["sequence"] = sequence
            update = wire(data)
            assert len(update) > IO_CHUNK_BYTES
            updates.extend(update)
        (tmp_path / "updates.frame").write_bytes(updates)
        data["sequence"] = 1
        for item in data["snapshot"]["objects"]:
            item["history"] = []
        (tmp_path / "first.frame").write_bytes(wire(data))
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    original_mode = termios.tcgetattr(slave)
    environment = dict(os.environ, TERM="xterm-256color", LANG="C.UTF-8")
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    with (tmp_path / "client.stderr").open("wb") as diagnostics:
        child = subprocess.Popen(
            [sys.executable, "-c", CHILD, scenario, str(progress), str(report), str(eof)],
            stdin=slave, stdout=slave, stderr=diagnostics if scenario == "large_updates" else slave,
            env=environment, cwd=tmp_path,
        )
    output = bytearray()

    def drain():
        while select.select([master], [], [], 0)[0]:
            output.extend(os.read(master, 65536))

    def observations():
        if not progress.exists():
            return []
        result = []
        for line in progress.read_text().splitlines():
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return result

    def wait_for(predicate, seconds=3):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            drain()
            if predicate():
                return
            if child.poll() is not None:
                break
            time.sleep(0.005)
        drain()
        assert predicate(), (scenario, child.returncode, bytes(output[-6000:]))

    try:
        if scenario in ("eof", "q", "large_updates", "sigint", "sigterm"):
            wait_for(lambda: any(item["event"] == "frame" for item in observations()))
            if scenario == "large_updates":
                (tmp_path / "updates.ready").touch()
                wait_for(lambda: any(item.get("sequence") == 3 for item in observations()))
            if scenario == "q":
                # Receive is stalled after the first frame while real keyboard
                # input still changes the theme and quits promptly.
                os.write(master, b"t")
                wait_for(lambda: any(item.get("theme") == "moonlight" for item in observations()))
            before_exit = time.monotonic()
            if scenario == "eof":
                eof.touch()
            elif scenario in ("q", "large_updates"):
                os.write(master, b"q")
            else:
                child.send_signal(signal.SIGINT if scenario == "sigint" else signal.SIGTERM)
        else:
            before_exit = time.monotonic()
        wait_for(lambda: child.poll() is not None)
        elapsed = time.monotonic() - before_exit
        child.wait(timeout=1)
        drain()
        result = json.loads(report.read_text())
        assert child.returncode == expected, bytes(output)
        assert termios.tcgetattr(slave) == original_mode
        assert result["connector_calls"] == 1 and result["forbidden_calls"] == []
        assert b"PRIVATE" not in output and b"Traceback" not in output
        if scenario == "initial_failure":
            assert result["events"] == [] and b"\x1b" not in output
        else:
            assert result["events"][0] == "enter" and result["events"][-1] == "restore"
            assert result["stream_closed"]
            assert b"\x1b[?1049h" in output and b"\x1b[?1049l" in output
            assert b"\x1b[?25l" in output and b"\x1b[?25h" in output
            assert max(result["read_sizes"]) <= 65536
        if scenario == "eof":
            diagnostic = b"Cannot connect to collector service. Run joi-observer again to retry."
            assert output.find(diagnostic) > output.rfind(b"\x1b[?1049l")
        if scenario in ("draw_error", "enter_error"):
            assert output.find(b"Observer stopped unexpectedly.") > output.rfind(b"\x1b[?1049l")
        if scenario in ("eof", "q", "sigint", "sigterm"):
            assert elapsed < 1.0, (scenario, elapsed)
        if scenario == "q":
            assert set(result["frames"]) == {"hologram", "moonlight"}
        if scenario == "large_updates":
            assert not (tmp_path / "client.stderr").read_bytes()
        evidence = os.environ.get("JOI_PTY_EVIDENCE_DIR")
        if evidence:
            directory = Path(evidence)
            directory.mkdir(parents=True, exist_ok=True)
            result.update(scenario=scenario, exit_code=child.returncode, exit_seconds=elapsed,
                          termios_restored=True, source="real SnapshotClient/TuiClientSession/CLI and local PTY; offline byte stream")
            (directory / f"r4-client-pty-{scenario}.json").write_text(json.dumps(result, indent=2) + "\n")
            (directory / f"r4-client-pty-{scenario}.ansi").write_bytes(output)
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=1)
        os.close(master)
        os.close(slave)
