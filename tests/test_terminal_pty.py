"""Real local ncurses input must not stall the asyncio event loop.

These cases require a Unix PTY; run them in local WSL on Windows. No service,
driver or socket is used. The child only exercises the real terminal adapter.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest


pytestmark = pytest.mark.skipif(os.name != "posix", reason="Requires a local Unix PTY; verified in WSL")


CHILD = r'''
import asyncio, json, sys, time
from pathlib import Path
from joi_observer.tui.app import CursesTerminal

ready, report = map(Path, sys.argv[1:3])
observe_only = sys.argv[3] == "observe"
terminal = CursesTerminal()

async def scenario():
    gaps = []
    reads = []
    running = True

    async def heartbeat():
        previous = time.monotonic()
        while running:
            await asyncio.sleep(0.01)
            current = time.monotonic()
            gaps.append(current - previous)
            previous = current

    ticker = asyncio.create_task(heartbeat())
    await asyncio.sleep(0.02)
    ready.touch()
    key = None
    observation_deadline = time.monotonic() + 0.25
    while time.monotonic() < observation_deadline:
        start = time.monotonic()
        key = await terminal.read_key(0.05)
        reads.append(time.monotonic() - start)
        if key is not None and not observe_only:
            break
    await asyncio.sleep(0.02)
    running = False
    await ticker
    return {"key": key, "maximum_read_seconds": max(reads),
            "maximum_loop_gap_seconds": max(gaps)}

try:
    terminal.enter()
    result = asyncio.run(scenario())
finally:
    terminal.restore()
report.write_text(json.dumps(result))
'''


@pytest.mark.parametrize("sequence,expected", [
    (b"q", "q"),
    (b"\x1bOA", "up"),
    (b"\x1bOD", "left"),
    (b"\x1b", None),
    (b"\x1b[", None),
], ids=["quit", "up", "left", "escape", "incomplete_escape_sequence"])
def test_input_preserves_poll_deadline_and_event_loop(tmp_path, sequence, expected):
    import fcntl
    import pty
    import select
    import struct
    import termios

    ready, report = tmp_path / "ready", tmp_path / "report.json"
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    original_mode = termios.tcgetattr(slave)
    env = dict(os.environ, TERM="xterm-256color", LANG="C.UTF-8", ESCDELAY="1000")
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    mode = "observe" if expected is None else "key"
    child = subprocess.Popen([sys.executable, "-c", CHILD, str(ready), str(report), mode],
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
        os.write(master, sequence)
        child.wait(timeout=5)
        drain()
        assert child.returncode == 0, bytes(captured)
        assert termios.tcgetattr(slave) == original_mode
        result = json.loads(report.read_text())
        if expected is not None:
            assert result["key"] == expected, result
        # Allow generous local scheduling jitter around the contractual 50 ms.
        # A one-second ncurses ESCDELAY must never block all sampling and UI.
        assert result["maximum_read_seconds"] < 0.20, result
        assert result["maximum_loop_gap_seconds"] < 0.20, result
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        os.close(master)
        os.close(slave)


FRAGMENTED_CHILD = r'''
import asyncio, json, sys, time
from pathlib import Path
from joi_observer.tui.app import CursesTerminal

ready, report = map(Path, sys.argv[1:3])
settings = json.loads(sys.argv[3])
terminal = CursesTerminal()

async def scenario():
    reads, keys, gaps = [], [], []
    finished = asyncio.Event()

    async def heartbeat():
        previous = time.monotonic()
        while not finished.is_set():
            await asyncio.sleep(0.005)
            current = time.monotonic()
            gaps.append(current - previous)
            previous = current

    async def read_until_done():
        deadline = time.monotonic() + 0.4
        while time.monotonic() < deadline:
            start = time.monotonic()
            key = await terminal.read_key(settings['timeout'])
            reads.append(time.monotonic() - start)
            if key is not None:
                keys.append(key)
            if key == settings.get('expected') and key is not None:
                return

    ticker = asyncio.create_task(heartbeat())
    await asyncio.sleep(0.01)
    reader = asyncio.create_task(read_until_done())
    ready.touch()
    cancelled = False
    cancellation_seconds = None
    if settings.get('cancel'):
        await asyncio.sleep(0.02)
        started = time.monotonic()
        reader.cancel()
        try:
            await reader
        except asyncio.CancelledError:
            cancelled = True
        cancellation_seconds = time.monotonic() - started
    else:
        await reader
    finished.set()
    await ticker
    return {'keys': keys, 'maximum_read_seconds': max(reads, default=0),
            'maximum_loop_gap_seconds': max(gaps), 'cancelled': cancelled,
            'cancellation_seconds': cancellation_seconds}

try:
    terminal.enter()
    result = asyncio.run(scenario())
finally:
    terminal.restore()
report.write_text(json.dumps(result))
'''


def run_fragmented_input(tmp_path, chunks, *, timeout=0.003, expected=None, cancel=False):
    """Send timed bytes through a real PTY; inspect only public read results."""
    import fcntl
    import pty
    import select
    import struct
    import termios

    ready, report = tmp_path / "ready", tmp_path / "report.json"
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    original_mode = termios.tcgetattr(slave)
    env = dict(os.environ, TERM="xterm-256color", LANG="C.UTF-8", ESCDELAY="1000")
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    settings = json.dumps({"timeout": timeout, "expected": expected, "cancel": cancel})
    child = subprocess.Popen([sys.executable, "-c", FRAGMENTED_CHILD, str(ready), str(report), settings],
                             stdin=slave, stdout=slave, stderr=slave, env=env)
    captured = bytearray()

    def drain():
        while select.select([master], [], [], 0)[0]:
            captured.extend(os.read(master, 65536))

    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            drain()
            time.sleep(0.001)
        assert ready.exists(), bytes(captured)
        for delay, chunk in chunks:
            time.sleep(delay)
            os.write(master, chunk)
        child.wait(timeout=5)
        drain()
        assert child.returncode == 0, bytes(captured)
        assert termios.tcgetattr(slave) == original_mode
        assert b"\x1b[?1049h" in captured and b"\x1b[?1049l" in captured
        assert b"\x1b[?25l" in captured and b"\x1b[?25h" in captured
        return json.loads(report.read_text())
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        os.close(master)
        os.close(slave)


@pytest.mark.parametrize("prefix,final,expected", [
    (b"O", b"A", "up"), (b"[", b"B", "down"),
    (b"[", b"C", "right"), (b"O", b"D", "left"),
])
def test_fragmented_arrows_survive_multiple_short_poll_timeouts(tmp_path, prefix, final, expected):
    result = run_fragmented_input(tmp_path, [(0, b"\x1b"), (0.008, prefix), (0.008, final)],
                                  timeout=0.003, expected=expected)
    assert result["keys"] == [expected], result
    # A 3ms caller must not inherit a 50ms synchronous escape-decoding wait.
    assert result["maximum_read_seconds"] < 0.04, result
    assert result["maximum_loop_gap_seconds"] < 0.04, result


@pytest.mark.parametrize("chunks,expected", [
    ([(0, b"\x1b["), (0.08, b"q")], "q"),
    ([(0, b"\x1b["), (0.008, b"q")], "q"),
    ([(0, b"\xe7"), (0.008, b"q")], "q"),
    ([(0, b"\xe7\x95\x8c"), (0.008, b"t")], "t"),
], ids=["expired_escape_then_quit", "malformed_escape_then_quit", "partial_utf8_then_quit", "unicode_then_theme"])
def test_unknown_input_does_not_consume_the_next_ascii_action(tmp_path, chunks, expected):
    result = run_fragmented_input(tmp_path, chunks, expected=expected)
    assert result["keys"] == [expected], result
    assert result["maximum_read_seconds"] < 0.04, result
    assert result["maximum_loop_gap_seconds"] < 0.04, result


def test_fragment_arrival_does_not_restart_escape_expiry(tmp_path):
    result = run_fragmented_input(tmp_path, [(0, b"\x1b"), (0.035, b"["),
                                            (0.04, b"B"), (0.008, b"q")], expected="q")
    assert result["keys"][-1] == "q", result
    assert "down" not in result["keys"], result
    assert result["maximum_read_seconds"] < 0.04, result
    assert result["maximum_loop_gap_seconds"] < 0.04, result


def test_escape_wait_can_be_cancelled_without_delaying_terminal_restore(tmp_path):
    result = run_fragmented_input(tmp_path, [(0, b"\x1b[")], timeout=0.05, cancel=True)
    assert result["cancelled"], result
    assert result["cancellation_seconds"] < 0.04, result
    assert result["maximum_loop_gap_seconds"] < 0.04, result
