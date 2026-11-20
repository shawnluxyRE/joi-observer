"""Raw PTY output must contain only curses frames while the client is running."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(os.name != "posix", reason="Requires a local Unix PTY")


CHILD = r'''
import logging, os, sys, warnings
from pathlib import Path
from joi_observer.cli import CommandDependencies, run_command
from joi_observer.ipc.client import ConnectionFailure
from joi_observer.tui.app import CursesTerminal
from joi_observer.tui.layout import Frame, TerminalSize, TextCell

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("asyncio")

class Session:
    async def run(self):
        terminal = CursesTerminal()
        try:
            terminal.enter()
            terminal.render(Frame((TextCell(0, 0, "VISIBLE-FRAME"),), (), TerminalSize(80, 24)))
            for level in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR):
                logger.log(level, "LOGGER-%s-PROBE", logging.getLevelName(level))
            warnings.warn("WARNINGS-PROBE")
            os.write(2, b"RAW-FD-PROBE\n")
            if sys.argv[1] == "fail":
                raise ConnectionFailure("PRIVATE-FAILURE")
        finally:
            terminal.restore()

    async def close(self):
        pass

deps = CommandDependencies(Path.cwd(), Path.cwd(), True, True, os.environ["TERM"],
                           sys.stdout, sys.stderr, lambda endpoint: Session(), None)
code = run_command(["tui"], dependencies=deps)
os.write(2, b"STDERR-AFTER-SESSION\n")
sys.exit(code)
'''


@pytest.mark.parametrize("redirected", [False, True], ids=["shared-tty", "stderr-pipe"])
@pytest.mark.parametrize("outcome", ["quit", "fail"])
def test_tui_keeps_diagnostics_off_the_screen_and_restores_stderr(redirected, outcome):
    import fcntl
    import pty
    import select
    import struct
    import termios

    master, slave = pty.openpty()
    try:
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        original_mode = termios.tcgetattr(slave)
        child = subprocess.run(
            [sys.executable, "-c", CHILD, outcome],
            stdin=slave, stdout=slave, stderr=subprocess.PIPE if redirected else slave,
            env=dict(os.environ, TERM="xterm-256color", LANG="C.UTF-8",
                     PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src")),
            timeout=5, check=False,
        )
        screen = bytearray()
        while select.select([master], [], [], 0)[0]:
            screen.extend(os.read(master, 65536))
        assert termios.tcgetattr(slave) == original_mode
    finally:
        os.close(master)
        os.close(slave)

    assert child.returncode == (4 if outcome == "fail" else 0), (screen, child.stderr)
    assert screen.index(b"\x1b[?1049h") < screen.index(b"VISIBLE-FRAME") < screen.index(b"\x1b[?1049l")
    for marker in (b"LOGGER-DEBUG-PROBE", b"LOGGER-INFO-PROBE", b"LOGGER-WARNING-PROBE",
                   b"LOGGER-ERROR-PROBE", b"WARNINGS-PROBE", b"RAW-FD-PROBE"):
        assert marker not in screen
        if redirected:
            assert marker in child.stderr
    restored = screen.index(b"\x1b[?1049l")
    assert b"Cannot connect to collector service." not in screen[:restored]
    assert b"PRIVATE-FAILURE" not in screen
    diagnostics = child.stderr if redirected else screen[restored:]
    assert b"STDERR-AFTER-SESSION" in diagnostics
    assert b"PRIVATE-FAILURE" not in diagnostics
    assert (b"Cannot connect to collector service." in diagnostics) == (outcome == "fail")
